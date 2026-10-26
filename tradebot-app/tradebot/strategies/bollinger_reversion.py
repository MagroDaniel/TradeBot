"""Reversão à média com Bandas de Bollinger, só em mercado SEM tendência (ADX baixo).

Por que testar: é o oposto do cruzamento de EMA — lucra justamente no "chop" que gera
whipsaw nas estratégias de tendência. Base: controllers `bollinger_v1`/`dman_v3` do
Hummingbot (entrada por %B fora das bandas), acrescido de RSI extremo e filtro de regime
por ADX pra não "pegar faca caindo" em tendência forte. Alvo = média central no momento do
sinal. No forex, a pesquisa já tinha apontado mean-reversion como candidato (70-80% do
tempo em range); aqui é o primeiro teste em cripto.
"""
from __future__ import annotations

from tradebot.indicators import adx, atr, bollinger, rsi
from tradebot.models import LONG, SHORT, ExitPlan, Signal
from tradebot.strategies.base import TIMEFRAMES, Param, Strategy


class BollingerReversionStrategy(Strategy):
    name = "bollinger_reversion"
    label = "Reversão à média Bollinger (mercado lateral)"
    description = (
        "Compra abaixo da banda inferior / vende acima da superior com RSI extremo, só com ADX "
        "baixo (sem tendência). Alvo na média central, stop por ATR."
    )
    params = {
        "timeframe": Param("15m", "Timeframe", "choice", choices=TIMEFRAMES),
        "bb_period": Param(20, "Período das bandas", "int", 5, 100),
        "bb_std": Param(2.0, "Desvios padrão", min=1, max=4),
        "rsi_low": Param(30.0, "RSI máximo pra comprar", min=5, max=50),
        "rsi_high": Param(70.0, "RSI mínimo pra vender", min=50, max=95),
        "max_adx": Param(20.0, "ADX máximo (regime lateral)", min=5, max=60),
        "atr_stop": Param(1.5, "Stop (× ATR)", min=0.3, max=10),
        "min_reward_risk": Param(0.8, "Alvo mínimo (× risco)", min=0.1, max=5),
        "time_limit_hours": Param(12.0, "Tempo máximo da posição (h)", min=0.5, max=240),
    }

    def warmup(self, p):
        return max(p["bb_period"], 28) + 72

    def generate(self, symbol, candles, htf_candles, p):
        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        lower, middle, upper = bollinger(closes, p["bb_period"], p["bb_std"])
        rsi_values = rsi(closes, 14)
        adx_values = adx(highs, lows, closes, 14)
        atr_values = atr(highs, lows, closes, 14)
        if not lower or not rsi_values or not adx_values or not atr_values:
            return None
        if adx_values[-1] > p["max_adx"]:
            return None

        close = closes[-1]
        if close < lower[-1] and rsi_values[-1] <= p["rsi_low"]:
            direction = LONG
        elif close > upper[-1] and rsi_values[-1] >= p["rsi_high"]:
            direction = SHORT
        else:
            return None

        sign = 1 if direction == LONG else -1
        stop_dist = p["atr_stop"] * atr_values[-1]
        target = middle[-1]
        reward = sign * (target - close)
        if stop_dist <= 0 or reward < p["min_reward_risk"] * stop_dist:
            return None
        plan = ExitPlan(
            stop_loss=close - sign * stop_dist,
            take_profit=target,
            time_limit_minutes=int(p["time_limit_hours"] * 60),
        )
        band = "inferior" if direction == LONG else "superior"
        reason = f"Fechou fora da banda {band}, RSI {rsi_values[-1]:.0f}, ADX {adx_values[-1]:.0f} (lateral)"
        return Signal(symbol, direction, close, plan, reason, self.name)
