"""Virada do Supertrend, confirmada pela tendência do timeframe maior.

Base: controller `supertrend_v1` do Hummingbot. O Supertrend já é um stop móvel por ATR —
a posição fica aberta enquanto ele não vira contra, então a saída é dinâmica (sem alvo
fixo), parecido com o Donchian, mas reage mais rápido. A confirmação do timeframe maior
reaproveita a lição do crypto-daytrade: sinal de 15m sem o 1h a favor tinha expectância
negativa.
"""
from __future__ import annotations

from tradebot.indicators import atr, ema, supertrend
from tradebot.models import LONG, SHORT, ExitPlan, Signal
from tradebot.strategies.base import TIMEFRAMES, Param, Strategy


class SupertrendStrategy(Strategy):
    name = "supertrend"
    label = "Supertrend + tendência do timeframe maior"
    description = (
        "Entra quando o Supertrend vira, se o timeframe maior concordar. Sai quando o "
        "Supertrend vira contra (ou no stop inicial)."
    )
    params = {
        "timeframe": Param("15m", "Timeframe", "choice", choices=TIMEFRAMES),
        "higher_timeframe": Param("1h", "Timeframe de confirmação", "choice", choices=TIMEFRAMES),
        "use_htf_filter": Param(True, "Exigir timeframe maior a favor", "bool"),
        "st_period": Param(10, "Período ATR do Supertrend", "int", 3, 50),
        "st_multiplier": Param(3.0, "Multiplicador do Supertrend", min=1, max=6),
        "min_stop_atr": Param(0.5, "Stop mínimo (× ATR)", min=0.1, max=5),
        "time_limit_hours": Param(48.0, "Tempo máximo da posição (h)", min=1, max=720),
    }

    def higher_timeframe(self, p):
        return p["higher_timeframe"] if p["use_htf_filter"] else None

    def warmup(self, p):
        return 150

    def generate(self, symbol, candles, htf_candles, p):
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        line, direction = supertrend(highs, lows, closes, p["st_period"], p["st_multiplier"])
        atr_values = atr(highs, lows, closes, 14)
        if len(direction) < 2 or not atr_values:
            return None
        if direction[-1] == direction[-2]:
            return None
        side = LONG if direction[-1] == 1 else SHORT

        if p["use_htf_filter"]:
            if not htf_candles:
                return None
            htf_closes = [c.close for c in htf_candles[-50:]]
            fast, slow = ema(htf_closes, 9), ema(htf_closes, 21)
            if not fast or not slow:
                return None
            if (side == LONG) != (fast[-1] > slow[-1]):
                return None

        close = closes[-1]
        sign = 1 if side == LONG else -1
        stop_dist = max(sign * (close - line[-1]), p["min_stop_atr"] * atr_values[-1])
        plan = ExitPlan(
            stop_loss=close - sign * stop_dist,
            take_profit=None,
            time_limit_minutes=int(p["time_limit_hours"] * 60),
        )
        reason = f"Supertrend virou pra {'alta' if side == LONG else 'baixa'}"
        return Signal(symbol, side, close, plan, reason, self.name)

    def should_exit(self, position, candles, p):
        _, direction = supertrend(
            [c.high for c in candles], [c.low for c in candles], [c.close for c in candles],
            p["st_period"], p["st_multiplier"],
        )
        if not direction:
            return False
        return direction[-1] == (-1 if position.direction == LONG else 1)
