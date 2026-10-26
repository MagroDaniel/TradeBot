"""EMA9/EMA21 + RSI + confirmação do 1h + filtro de range — a estratégia de PRODUÇÃO do
`crypto-daytrade`, portada sem mudar a regra (mesmos parâmetros default, mesma ordem de
filtros). Ver `crypto-daytrade/CLAUDE.md` pro histórico de backtests que levou a cada filtro.

Diferença deliberada: no bot de alertas o sinal "expira" após 24h; aqui isso vira o
`time_limit` da posição (fecha a mercado), porque agora existe posição de verdade.
O trailing stop é opcional e começa DESLIGADO — só ligue depois de validar no backtest.
"""
from __future__ import annotations

from tradebot.indicators import atr, ema, rsi
from tradebot.models import LONG, SHORT, ExitPlan, Signal
from tradebot.strategies.base import TIMEFRAMES, Param, Strategy


class EmaCrossStrategy(Strategy):
    name = "ema_cross"
    label = "Cruzamento EMA 9/21 + RSI (a do bot de alertas)"
    description = (
        "EMA rápida cruza a lenta, RSI fora dos extremos, tendência do timeframe maior a favor "
        "e mercado fora de range apertado. Stop por ATR, alvo fixo em R."
    )
    params = {
        "timeframe": Param("15m", "Timeframe do sinal", "choice", choices=TIMEFRAMES),
        "higher_timeframe": Param("1h", "Timeframe de confirmação", "choice", choices=TIMEFRAMES),
        "ema_fast": Param(9, "EMA rápida", "int", 2, 50),
        "ema_slow": Param(21, "EMA lenta", "int", 5, 200),
        "long_rsi_min": Param(30.0, "RSI mín. (long)", min=0, max=100),
        "long_rsi_max": Param(65.0, "RSI máx. (long)", min=0, max=100),
        "short_rsi_min": Param(35.0, "RSI mín. (short)", min=0, max=100),
        "short_rsi_max": Param(70.0, "RSI máx. (short)", min=0, max=100),
        "atr_stop": Param(1.5, "Stop (× ATR)", min=0.3, max=10),
        "reward_risk": Param(2.0, "Alvo (× risco)", min=0.5, max=10),
        "range_expansion": Param(6.0, "Filtro de range (0 = desligado)", min=0, max=20,
                                 help="Amplitude dos últimos 20 candles ÷ amplitude média de 1 candle"),
        "time_limit_hours": Param(24.0, "Tempo máximo da posição (h)", min=0.25, max=240),
        "trailing_atr": Param(0.0, "Trailing stop (× ATR, 0 = desligado)", min=0, max=10),
    }

    RANGE_LOOKBACK = 20
    HTF_WINDOW = 50

    def higher_timeframe(self, p):
        return p["higher_timeframe"]

    def warmup(self, p):
        return 100  # mesmo `limit=100` de produção — a semente SMA da EMA depende do tamanho da janela

    def generate(self, symbol, candles, htf_candles, p):
        closes = [c.close for c in candles]
        fast = ema(closes, p["ema_fast"])
        slow = ema(closes, p["ema_slow"])
        rsi_values = rsi(closes, 14)
        atr_values = atr([c.high for c in candles], [c.low for c in candles], closes, 14)
        if len(fast) < 2 or len(slow) < 2 or not rsi_values or not atr_values:
            return None

        crossed_up = fast[-2] <= slow[-2] and fast[-1] > slow[-1]
        crossed_down = fast[-2] >= slow[-2] and fast[-1] < slow[-1]
        rsi_now = rsi_values[-1]
        if crossed_up and p["long_rsi_min"] <= rsi_now <= p["long_rsi_max"]:
            direction = LONG
        elif crossed_down and p["short_rsi_min"] <= rsi_now <= p["short_rsi_max"]:
            direction = SHORT
        else:
            return None

        if not self._htf_confirms(htf_candles, direction, p):
            return None
        if p["range_expansion"] > 0 and not self._out_of_range(candles, p["range_expansion"]):
            return None

        entry = closes[-1]
        atr_now = atr_values[-1]
        sign = 1 if direction == LONG else -1
        stop_dist = p["atr_stop"] * atr_now
        plan = ExitPlan(
            stop_loss=entry - sign * stop_dist,
            take_profit=entry + sign * p["reward_risk"] * stop_dist,
            time_limit_minutes=int(p["time_limit_hours"] * 60),
            trailing_activation=stop_dist if p["trailing_atr"] > 0 else None,
            trailing_distance=p["trailing_atr"] * atr_now if p["trailing_atr"] > 0 else None,
        )
        arrow = "acima" if direction == LONG else "abaixo"
        reason = f"EMA{p['ema_fast']} cruzou {arrow} da EMA{p['ema_slow']}, RSI {rsi_now:.0f}, {p['higher_timeframe']} a favor"
        return Signal(symbol, direction, entry, plan, reason, self.name)

    def _htf_confirms(self, htf_candles, direction, p) -> bool:
        if not htf_candles:
            return False  # não confirma na dúvida, igual produção
        closes = [c.close for c in htf_candles[-self.HTF_WINDOW:]]
        fast = ema(closes, p["ema_fast"])
        slow = ema(closes, p["ema_slow"])
        if not fast or not slow:
            return False
        return fast[-1] > slow[-1] if direction == LONG else fast[-1] < slow[-1]

    def _out_of_range(self, candles, min_expansion: float) -> bool:
        if len(candles) < self.RANGE_LOOKBACK:
            return False
        recent = candles[-self.RANGE_LOOKBACK:]
        avg_bar = sum(c.high - c.low for c in recent) / len(recent)
        if avg_bar <= 0:
            return False
        return (max(c.high for c in recent) - min(c.low for c in recent)) / avg_bar >= min_expansion
