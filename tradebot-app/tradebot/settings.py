"""Configurações: globais do app (`AppSettings`) e de cada robô (`BotConfig`).

Cada robô é uma estratégia com seus parâmetros, pares, risco, proteções e carteira demo
PRÓPRIA — vários robôs rodando ao mesmo tempo nunca dividem saldo nem limite de posições, então
dá pra comparar estratégias lado a lado de forma justa (um não "rouba" a vaga do outro).

Defaults conservadores: risco de 1% do patrimônio por trade, no máximo 3 posições por
mercado, e proteções ligadas (perda diária, sequência de stops, cooldown, drawdown) —
inspiradas nas `protections` do Freqtrade.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from tradebot.models import FUTURES, MARKETS, SPOT
from tradebot.strategies import DEFAULT_STRATEGY, STRATEGIES, get_strategy

ACCOUNTS = ("paper",)  # "demo" (Binance Demo Mode) e "live" entram nas próximas fases
MAX_BOTS = 10


@dataclass
class MarketSettings:
    enabled: bool = True
    initial_balance: float = 1000.0  # USDT da carteira demo
    fee_rate: float = 0.001  # taxa taker por lado (spot 0,10%; futuros 0,05% no VIP0)


@dataclass
class RiskSettings:
    risk_per_trade_pct: float = 1.0  # quanto do patrimônio perder se bater o stop
    max_position_pct: float = 25.0  # teto do tamanho da posição (% do patrimônio do mercado)
    max_open_positions: int = 3  # por mercado
    max_open_per_direction: int = 2  # cripto anda junto: 3 longs ao mesmo tempo ≈ 1 aposta só
    max_trades_per_day: int = 12  # por mercado
    max_slippage_pct: float = 0.5


@dataclass
class ProtectionSettings:
    daily_loss_limit_pct: float = 3.0  # perdeu isso hoje (UTC) → sem entradas até amanhã
    stoploss_guard_count: int = 3  # N stops seguidos...
    stoploss_guard_window_min: int = 120  # ...dentro desta janela...
    stoploss_guard_pause_min: int = 120  # ...pausam entradas por este tempo
    symbol_cooldown_min: int = 60  # após fechar um par, espera antes de reentrar nele
    max_drawdown_pct: float = 15.0  # queda desde o pico → pausa entradas até liberar no painel


@dataclass
class BotConfig:
    name: str = "EMA 9/21"
    strategy: str = DEFAULT_STRATEGY
    strategy_params: dict[str, Any] = field(default_factory=dict)  # só os da estratégia deste robô
    markets: dict[str, MarketSettings] = field(default_factory=lambda: {
        SPOT: MarketSettings(fee_rate=0.001),
        FUTURES: MarketSettings(fee_rate=0.0005),
    })
    top_symbols: int = 25
    symbols: list[str] = field(default_factory=list)  # se preenchido, substitui o top-N
    risk: RiskSettings = field(default_factory=RiskSettings)
    protections: ProtectionSettings = field(default_factory=ProtectionSettings)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "BotConfig":
        """Tolerante a config antiga: campo desconhecido é ignorado, faltante usa default."""
        data = data or {}
        c = cls()
        if str(data.get("name", "")).strip():
            c.name = str(data["name"]).strip()[:40]
        if data.get("strategy") in STRATEGIES:
            c.strategy = data["strategy"]
        params = data.get("strategy_params") or {}
        # formato da versão 1 (um app = uma estratégia): {nome_estrategia: {params}}
        if c.strategy in params and isinstance(params[c.strategy], dict):
            params = params[c.strategy]
        c.strategy_params = {k: v for k, v in params.items() if k in get_strategy(c.strategy).params}
        for market, raw in (data.get("markets") or {}).items():
            if market in MARKETS:
                c.markets[market] = _fill(MarketSettings(fee_rate=c.markets[market].fee_rate), raw)
        if "top_symbols" in data:
            c.top_symbols = int(data["top_symbols"])
        c.symbols = [str(x).upper().strip() for x in data.get("symbols") or [] if str(x).strip()]
        c.risk = _fill(RiskSettings(), data.get("risk") or {})
        c.protections = _fill(ProtectionSettings(), data.get("protections") or {})
        c.validate()
        return c

    def params(self) -> dict[str, Any]:
        return get_strategy(self.strategy).resolve(self.strategy_params)

    def validate(self) -> None:
        r, pr = self.risk, self.protections
        checks = [
            (0 < r.risk_per_trade_pct <= 5, "Risco por trade deve ficar entre 0 e 5%"),
            (0 < r.max_position_pct <= 100, "Tamanho máximo da posição deve ficar entre 0 e 100%"),
            (r.max_open_positions >= 1 and r.max_open_per_direction >= 1, "Limites de posição devem ser ≥ 1"),
            (r.max_trades_per_day >= 1, "Trades por dia deve ser ≥ 1"),
            (0 < r.max_slippage_pct <= 5, "Slippage máximo deve ficar entre 0 e 5%"),
            (pr.daily_loss_limit_pct > 0 and pr.max_drawdown_pct > 0, "Limites de perda devem ser > 0"),
            (1 <= self.top_symbols <= 100, "Quantidade de pares deve ficar entre 1 e 100"),
            (any(m.enabled for m in self.markets.values()), "Habilite pelo menos um mercado"),
            (all(m.initial_balance > 0 and 0 <= m.fee_rate < 0.01 for m in self.markets.values()),
             "Saldo inicial deve ser > 0 e taxa < 1%"),
        ]
        for ok, message in checks:
            if not ok:
                raise ValueError(message)
        self.params()  # valida os parâmetros da estratégia


@dataclass
class AppSettings:
    account: str = "paper"
    poll_seconds: int = 10

    @classmethod
    def from_dict(cls, data: dict | None) -> "AppSettings":
        data = data or {}
        s = cls()
        if data.get("account") in ACCOUNTS:
            s.account = data["account"]
        if "poll_seconds" in data:
            s.poll_seconds = int(float(data["poll_seconds"]))
        if not 3 <= s.poll_seconds <= 300:
            raise ValueError("Intervalo do ciclo deve ficar entre 3 e 300 s")
        return s

    def to_dict(self) -> dict:
        return asdict(self)


def _fill(obj, raw: dict):
    for key, value in raw.items():
        if hasattr(obj, key):
            current = getattr(obj, key)
            if isinstance(current, bool):
                value = value if isinstance(value, bool) else str(value).lower() in {"1", "true", "on"}
            elif isinstance(current, int):
                value = int(float(value))
            elif isinstance(current, float):
                value = float(value)
            setattr(obj, key, value)
    return obj
