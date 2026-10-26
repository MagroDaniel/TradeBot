"""Portão de risco: TODA entrada passa por aqui antes de virar ordem. Falha = nega (fail-closed).

Junta três ideias:
- **Kill switch** (Vibe-Trading, `live/halt.py`): um arquivo `HALT` na pasta de dados. Se
  existir, nenhuma entrada passa — vale mesmo se o motor/painel travar, e dá pra acionar
  criando o arquivo na mão. Saídas continuam permitidas (sair nunca é bloqueado).
- **Limites por ordem/dia** (Vibe-Trading, `order_guard.py`): posições abertas, por direção,
  trades por dia, tamanho máximo.
- **Proteções** (Freqtrade, `plugins/protections`): perda diária, sequência de stops,
  cooldown por par e drawdown máximo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tradebot.models import Position, Signal
from tradebot.settings import Settings

STOP_REASONS = {"stop_loss"}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""
    qty: float = 0.0


def utc_day_start_ms(now_ms: int) -> int:
    day = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(day.timestamp() * 1000)


# --- kill switch ---
def halt_path(data_dir: Path) -> Path:
    return data_dir / "HALT"


def is_halted(data_dir: Path) -> bool:
    return halt_path(data_dir).exists()


def set_halt(data_dir: Path, reason: str, by: str = "painel") -> None:
    payload = {"tripped_at": datetime.now(timezone.utc).isoformat(), "by": by, "reason": reason}
    halt_path(data_dir).write_text(json.dumps(payload), encoding="utf-8")


def clear_halt(data_dir: Path) -> None:
    halt_path(data_dir).unlink(missing_ok=True)


# --- proteções (só bloqueiam ENTRADA) ---
def active_protection(settings: Settings, closed_today_and_recent: list[Position], equity: float,
                      peak_equity: float, day_start_equity: float, now_ms: int) -> str | None:
    """Motivo do bloqueio global de entradas num mercado, ou None se liberado.

    `closed_today_and_recent` = posições fechadas nas últimas 24h deste mercado.
    """
    pr = settings.protections
    day_start = utc_day_start_ms(now_ms)
    realized_today = sum(p.net_pnl() for p in closed_today_and_recent if p.closed_at_ms >= day_start)
    if day_start_equity > 0 and realized_today <= -pr.daily_loss_limit_pct / 100 * day_start_equity:
        return f"Limite de perda diária atingido ({realized_today:.2f} USDT hoje)"

    if peak_equity > 0 and equity < peak_equity * (1 - pr.max_drawdown_pct / 100):
        return f"Drawdown máximo atingido ({(1 - equity / peak_equity):.1%} abaixo do pico) — libere no painel"

    window_start = now_ms - pr.stoploss_guard_window_min * 60_000
    recent = sorted((p for p in closed_today_and_recent if p.closed_at_ms >= window_start),
                    key=lambda p: p.closed_at_ms)
    streak = 0
    for p in reversed(recent):
        if p.exit_reason in STOP_REASONS:
            streak += 1
        else:
            break
    if streak >= pr.stoploss_guard_count:
        last = recent[-1].closed_at_ms
        resume = last + pr.stoploss_guard_pause_min * 60_000
        if now_ms < resume:
            minutes = (resume - now_ms) // 60_000 + 1
            return f"{streak} stops seguidos — entradas pausadas por mais {minutes} min"
    return None


def symbol_in_cooldown(settings: Settings, symbol: str, recent_closed: list[Position], now_ms: int) -> bool:
    limit = settings.protections.symbol_cooldown_min * 60_000
    return any(p.symbol == symbol and now_ms - p.closed_at_ms < limit for p in recent_closed)


# --- tamanho da posição ---
def position_size(signal: Signal, equity: float, cash: float, settings: Settings) -> float:
    """Quantidade tal que bater o stop custe `risk_per_trade_pct` do patrimônio, limitada pelo
    tamanho máximo da posição e pelo caixa disponível (sem alavancagem: nunca mais que o caixa)."""
    risk_per_unit = signal.risk_per_unit
    if risk_per_unit <= 0 or signal.entry <= 0:
        return 0.0
    qty = equity * settings.risk.risk_per_trade_pct / 100 / risk_per_unit
    max_notional = min(equity * settings.risk.max_position_pct / 100, cash * 0.98)  # 2% de folga pra taxa/slippage
    return max(0.0, min(qty, max_notional / signal.entry))


def check_entry(signal: Signal, market: str, settings: Settings, open_positions: list[Position],
                trades_today: int) -> Decision:
    """Limites estruturais (não dependem de saldo). Tamanho é calculado depois, no motor."""
    r = settings.risk
    if market == "spot" and signal.direction != "long":
        return Decision(False, "Spot não permite short")
    if any(p.symbol == signal.symbol for p in open_positions):
        return Decision(False, "Já existe posição aberta neste par")
    if len(open_positions) >= r.max_open_positions:
        return Decision(False, f"Limite de {r.max_open_positions} posições abertas atingido")
    if sum(1 for p in open_positions if p.direction == signal.direction) >= r.max_open_per_direction:
        return Decision(False, f"Limite de {r.max_open_per_direction} posições {signal.direction} atingido")
    if trades_today >= r.max_trades_per_day:
        return Decision(False, f"Limite de {r.max_trades_per_day} trades/dia atingido")
    return Decision(True)
