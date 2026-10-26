"""Registro das estratégias disponíveis no painel e no backtest."""
from __future__ import annotations

from tradebot.strategies.base import Strategy
from tradebot.strategies.bollinger_reversion import BollingerReversionStrategy
from tradebot.strategies.donchian_breakout import DonchianBreakoutStrategy
from tradebot.strategies.ema_cross import EmaCrossStrategy
from tradebot.strategies.session_momentum import SessionMomentumStrategy
from tradebot.strategies.supertrend import SupertrendStrategy

STRATEGIES: dict[str, Strategy] = {
    s.name: s
    for s in (
        EmaCrossStrategy(),
        DonchianBreakoutStrategy(),
        SupertrendStrategy(),
        BollingerReversionStrategy(),
        SessionMomentumStrategy(),
    )
}

DEFAULT_STRATEGY = EmaCrossStrategy.name


def get_strategy(name: str) -> Strategy:
    try:
        return STRATEGIES[name]
    except KeyError:
        raise ValueError(f"Estratégia desconhecida: {name}") from None
