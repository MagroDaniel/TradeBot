"""Momentum intradiário de sessão (adaptação de Shen, Urquhart & Wang, 2022).

O estudo mostra que, em Bitcoin, o retorno do começo do "dia de negociação" prevê o retorno
do fim — efeito mais forte nas sessões de maior volume/volatilidade. Cripto não tem pregão,
então a adaptação é: no fechamento do candle de 1h que termina em `entry_hour_utc` (default
14h UTC = abertura da sessão americana, pico de volume), olha o retorno desde 00h UTC; se
passou de `min_move_pct`, entra na MESMA direção e sai por tempo em `exit_hour_utc`.

Pensado pra BTC/ETH (onde o efeito foi medido) — em altcoins é hipótese não testada.
Um trade por dia por par no máximo. Evidência acadêmica é de UM artigo bem citado, sem
replicação independente com custo — por isso fica como candidato de pesquisa.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tradebot.indicators import atr
from tradebot.models import LONG, SHORT, ExitPlan, Signal
from tradebot.strategies.base import Param, Strategy


class SessionMomentumStrategy(Strategy):
    name = "session_momentum"
    label = "Momentum de sessão (BTC/ETH, pesquisa)"
    description = (
        "Se o preço andou mais que X% desde 00h UTC até a abertura americana, entra na mesma "
        "direção e sai por horário no fim da sessão."
    )
    params = {
        "entry_hour_utc": Param(14, "Hora de entrada (UTC)", "int", 1, 23),
        "exit_hour_utc": Param(21, "Hora de saída (UTC)", "int", 2, 24),
        "min_move_pct": Param(0.5, "Movimento mínimo desde 00h UTC (%)", min=0, max=10),
        "atr_stop": Param(2.0, "Stop (× ATR 1h)", min=0.5, max=10),
    }

    def timeframe(self, p):
        return "1h"

    def warmup(self, p):
        return 48

    def generate(self, symbol, candles, htf_candles, p):
        if p["exit_hour_utc"] <= p["entry_hour_utc"]:
            return None
        last = candles[-1]
        close_dt = datetime.fromtimestamp((last.close_time_ms + 1) / 1000, tz=timezone.utc)
        if close_dt.hour != p["entry_hour_utc"] or close_dt.minute != 0:
            return None
        day_start_ms = int(close_dt.replace(hour=0).timestamp() * 1000)
        day_candles = [c for c in candles if c.open_time_ms >= day_start_ms]
        if len(day_candles) < p["entry_hour_utc"]:
            return None  # buraco nos dados — não decide com dia incompleto
        move_pct = (last.close / day_candles[0].open - 1) * 100
        if abs(move_pct) < p["min_move_pct"]:
            return None
        atr_values = atr([c.high for c in candles], [c.low for c in candles], [c.close for c in candles], 14)
        if not atr_values:
            return None

        direction = LONG if move_pct > 0 else SHORT
        sign = 1 if direction == LONG else -1
        stop_dist = p["atr_stop"] * atr_values[-1]
        plan = ExitPlan(
            stop_loss=last.close - sign * stop_dist,
            time_limit_minutes=(p["exit_hour_utc"] - p["entry_hour_utc"]) * 60,
        )
        reason = f"Moveu {move_pct:+.2f}% desde 00h UTC até {p['entry_hour_utc']}h UTC"
        return Signal(symbol, direction, last.close, plan, reason, self.name)
