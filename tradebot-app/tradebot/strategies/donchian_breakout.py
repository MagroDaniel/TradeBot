"""Rompimento de canal Donchian com saída por trailing — seguidor de tendência "Turtle".

Por que testar: o crypto-daytrade usa alvo FIXO em 2R, o que corta justamente os poucos
trades enormes de que estratégias de tendência dependem (retornos de cripto têm cauda gorda).
Aqui não há alvo: o lucro corre até o trailing de ATR ou o canal de saída (mais curto)
encerrar. Espera-se win rate baixo (~30-40%) compensado por ganhos grandes.

Literatura: rompimento Donchian com stop ATR em BTC (Poluri, SSRN) foi positivo, porém
sensível a custo e parâmetro — por isso o filtro de tendência longa e o timeframe de 1h
(menos trades, menos custo) como default. Precisa de validação walk-forward antes de uso.
"""
from __future__ import annotations

from tradebot.indicators import atr, ema
from tradebot.models import LONG, SHORT, ExitPlan, Signal
from tradebot.strategies.base import TIMEFRAMES, Param, Strategy


class DonchianBreakoutStrategy(Strategy):
    name = "donchian_breakout"
    label = "Rompimento Donchian + trailing (tendência)"
    description = (
        "Entra quando o fechamento rompe a máxima/mínima dos últimos N candles, a favor da "
        "média longa. Sem alvo fixo: sai no trailing de ATR ou no rompimento do canal curto."
    )
    params = {
        "timeframe": Param("1h", "Timeframe", "choice", choices=TIMEFRAMES),
        "entry_channel": Param(20, "Canal de entrada (candles)", "int", 5, 200),
        "exit_channel": Param(10, "Canal de saída (candles)", "int", 3, 200),
        "trend_ema": Param(200, "Média de tendência (0 = sem filtro)", "int", 0, 400),
        "atr_stop": Param(2.0, "Stop inicial (× ATR)", min=0.5, max=10),
        "trailing_atr": Param(3.0, "Trailing (× ATR)", min=0.5, max=10),
        "trailing_activation_r": Param(1.0, "Liga trailing após (R)", min=0, max=10),
        "time_limit_hours": Param(96.0, "Tempo máximo da posição (h)", min=1, max=720),
    }

    def warmup(self, p):
        return max(p["entry_channel"], p["exit_channel"], p["trend_ema"]) + 50

    def generate(self, symbol, candles, htf_candles, p):
        n = p["entry_channel"]
        if len(candles) < n + 2:
            return None
        closes = [c.close for c in candles]
        atr_values = atr([c.high for c in candles], [c.low for c in candles], closes, 14)
        if not atr_values:
            return None

        # canal formado pelos N candles ANTERIORES ao atual
        prev_high = max(c.high for c in candles[-n - 1 : -1])
        prev_low = min(c.low for c in candles[-n - 1 : -1])
        # e o canal do candle anterior, pra só entrar no PRIMEIRO fechamento fora do canal
        before_high = max(c.high for c in candles[-n - 2 : -2])
        before_low = min(c.low for c in candles[-n - 2 : -2])

        close = closes[-1]
        if close > prev_high and closes[-2] <= before_high:
            direction = LONG
        elif close < prev_low and closes[-2] >= before_low:
            direction = SHORT
        else:
            return None

        if p["trend_ema"] > 0:
            trend = ema(closes, p["trend_ema"])
            if not trend:
                return None
            if (direction == LONG and close < trend[-1]) or (direction == SHORT and close > trend[-1]):
                return None

        atr_now = atr_values[-1]
        sign = 1 if direction == LONG else -1
        stop_dist = p["atr_stop"] * atr_now
        plan = ExitPlan(
            stop_loss=close - sign * stop_dist,
            take_profit=None,
            time_limit_minutes=int(p["time_limit_hours"] * 60),
            trailing_activation=p["trailing_activation_r"] * stop_dist,
            trailing_distance=p["trailing_atr"] * atr_now,
        )
        side = "máxima" if direction == LONG else "mínima"
        reason = f"Fechou além da {side} de {n} candles ({prev_high if direction == LONG else prev_low:.6g})"
        return Signal(symbol, direction, close, plan, reason, self.name)

    def should_exit(self, position, candles, p):
        m = p["exit_channel"]
        if len(candles) < m + 1:
            return False
        close = candles[-1].close
        if position.direction == LONG:
            return close < min(c.low for c in candles[-m - 1 : -1])
        return close > max(c.high for c in candles[-m - 1 : -1])
