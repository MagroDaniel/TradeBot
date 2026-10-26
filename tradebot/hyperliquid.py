"""Leitura de carteiras da Hyperliquid (corretora de futuros on-chain) para copy trading.

Na Hyperliquid as posições e o histórico de qualquer carteira são públicos, pela API oficial
`POST https://api.hyperliquid.xyz/info` (sem chave). É isso que torna o copy trading possível
sem depender de endpoint não oficial — diferente da Binance, cuja API de copy trading só
atende o próprio trader copiado, não quem segue.

Só leitura: nenhuma ordem é enviada pra Hyperliquid. A cópia é executada na Binance (conta
demo hoje), mapeando a moeda (BTC → BTCUSDT).
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

import requests

from tradebot.models import LONG, SHORT

INFO_URL = "https://api.hyperliquid.xyz/info"
LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def valid_address(address: str) -> bool:
    return bool(ADDRESS_RE.match(address or ""))


def binance_symbol(coin: str) -> str | None:
    """BTC → BTCUSDT; kPEPE (lote de 1000 na Hyperliquid) → 1000PEPEUSDT (mesmo lote na Binance).
    Ativos de DEX de terceiros (`dex:ATIVO`, ex: ações tokenizadas) não têm equivalente → None."""
    if not coin or ":" in coin or "/" in coin or coin.startswith("@"):
        return None
    if len(coin) > 1 and coin[0] == "k" and coin[1:].isupper():
        return f"1000{coin[1:]}USDT"
    return f"{coin.upper()}USDT"


@dataclass(frozen=True)
class LeaderPosition:
    coin: str
    direction: str  # LONG ou SHORT
    size: float  # em unidades da moeda (sempre positivo)
    entry_price: float
    notional: float  # valor da posição em USD
    leverage: float
    unrealized_pnl: float


@dataclass
class LeaderState:
    address: str
    account_value: float
    positions: dict[str, LeaderPosition] = field(default_factory=dict)

    @property
    def total_notional(self) -> float:
        return sum(p.notional for p in self.positions.values())

    @property
    def effective_leverage(self) -> float:
        return self.total_notional / self.account_value if self.account_value > 0 else 0.0


def parse_state(address: str, raw: dict) -> LeaderState:
    positions = {}
    for item in raw.get("assetPositions") or []:
        p = item.get("position") or {}
        size = float(p.get("szi") or 0)
        if size == 0:
            continue
        positions[p["coin"]] = LeaderPosition(
            coin=p["coin"],
            direction=LONG if size > 0 else SHORT,
            size=abs(size),
            entry_price=float(p.get("entryPx") or 0),
            notional=abs(float(p.get("positionValue") or 0)),
            leverage=float((p.get("leverage") or {}).get("value") or 0),
            unrealized_pnl=float(p.get("unrealizedPnl") or 0),
        )
    account_value = float((raw.get("marginSummary") or {}).get("accountValue") or 0)
    return LeaderState(address.lower(), account_value, positions)


class HyperliquidClient:
    def __init__(self, url: str = INFO_URL, timeout: int = 15, session: requests.Session | None = None) -> None:
        self.url = url
        self.timeout = timeout
        self.http = session or requests.Session()
        self._leaderboard: tuple[float, list] | None = None
        self._lock = threading.Lock()

    def _post(self, payload: dict):
        response = self.http.post(self.url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def state(self, address: str) -> LeaderState:
        return parse_state(address, self._post({"type": "clearinghouseState", "user": address}))

    def fills(self, address: str) -> list[dict]:
        """Até as 2000 execuções mais recentes."""
        return self._post({"type": "userFills", "user": address})

    def portfolio(self, address: str) -> dict:
        """{'day'|'week'|'month'|'allTime'|'perp...': {'accountValueHistory': [[ms, v]], 'pnlHistory': [[ms, v]]}}"""
        return {name: data for name, data in self._post({"type": "portfolio", "user": address})}

    def leaderboard(self, limit: int = 30, window: str = "month", min_account: float = 50_000) -> list[dict]:
        """Ranking público usado pelo próprio site da Hyperliquid (endpoint de estatísticas, não
        documentado na API — se mudar, só a sugestão de carteiras some, a cópia continua)."""
        with self._lock:
            if self._leaderboard is None or time.time() - self._leaderboard[0] > 1800:
                response = self.http.get(LEADERBOARD_URL, timeout=60)
                response.raise_for_status()
                self._leaderboard = (time.time(), response.json().get("leaderboardRows") or [])
            rows = self._leaderboard[1]
        out = []
        for r in rows:
            perf = dict(r.get("windowPerformances") or [])
            if window not in perf or float(r.get("accountValue") or 0) < min_account:
                continue
            out.append({"address": r["ethAddress"], "name": r.get("displayName"),
                        "account_value": float(r["accountValue"]), "pnl": float(perf[window]["pnl"]),
                        "roi": float(perf[window]["roi"]),
                        "all_time_pnl": float(dict(r["windowPerformances"]).get("allTime", {}).get("pnl") or 0)})
        out.sort(key=lambda x: x["pnl"], reverse=True)
        return out[:limit]


# --- análise de uma carteira antes de copiar ---
def analyze(address: str, state: LeaderState, fills: list[dict], portfolio: dict) -> dict:
    """Números pra decidir se vale copiar, a partir do histórico REAL (não do print de lucro).

    - Operações fechadas: execuções com `closedPnl` (cada fechamento/redução de posição).
    - Drawdown: pela curva de P&L acumulado (`pnlHistory`), que não é distorcida por
      depósitos/saques como a de patrimônio.
    """
    closes = [f for f in fills if f.get("dir", "").startswith("Close") or float(f.get("closedPnl") or 0) != 0]
    pnls = [float(f.get("closedPnl") or 0) for f in closes]
    fees = sum(float(f.get("fee") or 0) for f in fills)
    wins = sum(1 for x in pnls if x > 0)
    times = [int(f["time"]) for f in fills if "time" in f]
    span_days = (max(times) - min(times)) / 86_400_000 if len(times) > 1 else 0.0
    coins: dict[str, int] = {}
    for f in fills:
        coins[f["coin"]] = coins.get(f["coin"], 0) + 1

    periods = {}
    for name in ("day", "week", "month", "allTime"):
        data = portfolio.get(f"perp{name[0].upper()}{name[1:]}") or portfolio.get(name) or {}
        pnl_hist = [(int(t), float(v)) for t, v in data.get("pnlHistory") or []]
        av_hist = [(int(t), float(v)) for t, v in data.get("accountValueHistory") or []]
        peak, dd = float("-inf"), 0.0
        for _, v in pnl_hist:
            peak = max(peak, v)
            dd = max(dd, peak - v)
        ref = max((v for _, v in av_hist), default=0.0)
        periods[name] = {
            "pnl": pnl_hist[-1][1] - pnl_hist[0][1] if len(pnl_hist) > 1 else (pnl_hist[0][1] if pnl_hist else 0.0),
            "max_drawdown": dd, "max_drawdown_pct": dd / ref * 100 if ref > 0 else None,
            "pnl_history": pnl_hist,
        }

    warnings = []
    if state.effective_leverage > 5:
        warnings.append(f"Alavancagem atual alta ({state.effective_leverage:.1f}x). O robô copia a 1x, então o "
                        "resultado em % será bem menor que o dele (e o risco também).")
    if len(closes) < 30:
        warnings.append(f"Poucas operações fechadas no histórico disponível ({len(closes)}): o resultado pode ser sorte.")
    if span_days and len(fills) / max(span_days, 1e-9) > 200:
        warnings.append("Opera com muita frequência (centenas de execuções por dia): o atraso da cópia e as taxas "
                        "tendem a comer o lucro. Prefira traders de posições mais longas.")
    if periods["allTime"]["pnl"] < 0:
        warnings.append("Prejuízo no histórico completo.")
    unmapped = [c for c in state.positions if binance_symbol(c) is None]
    if unmapped:
        warnings.append(f"Posições sem equivalente na Binance (não serão copiadas): {', '.join(unmapped)}.")

    return {
        "address": address.lower(), "account_value": state.account_value,
        "effective_leverage": state.effective_leverage, "positions": list(state.positions.values()),
        "closed_trades": len(closes), "wins": wins, "win_rate": wins / len(closes) * 100 if closes else None,
        "closed_pnl": sum(pnls), "fees": fees, "fills": len(fills), "span_days": span_days,
        "fills_per_day": len(fills) / span_days if span_days else None,
        "top_coins": sorted(coins.items(), key=lambda kv: -kv[1])[:6],
        "periods": periods, "warnings": warnings,
    }
