"""Barreiras de saída de uma posição — stop, alvo, tempo-limite e trailing stop.

Uma função só (`evaluate_bar`) usada pelo backtest (um candle por vez) E pelo motor ao vivo
(cada leitura de preço vira um "candle" de preço único). Mesma regra nos dois modos: o
backtest não pode ser mais otimista que a execução real.

Ordem conservadora dentro de um candle (igual ao `check_outcome` do crypto-daytrade):
1. stop (inclusive o trailing já armado) — se o candle tocou o stop, assume que foi primeiro;
2. alvo;
3. só DEPOIS atualiza o melhor preço / trailing — o stop novo vale a partir do próximo candle
   (não dá pra saber se a máxima veio antes ou depois da mínima dentro do candle);
4. tempo-limite, no fechamento.

Gap: se o candle já ABRE além do stop, a saída é no preço de abertura (pior que o stop),
não no stop — senão o backtest esconderia o prejuízo de gaps.
"""
from __future__ import annotations

from dataclasses import dataclass

from tradebot.models import LONG, Position


@dataclass(frozen=True)
class ExitDecision:
    reason: str  # stop_loss | trailing_stop | take_profit | time_limit
    price: float


def evaluate_bar(
    position: Position, open_: float, high: float, low: float, close: float, bar_end_ms: int
) -> ExitDecision | None:
    long = position.direction == LONG
    stop = position.stop_loss
    stop_reason = "trailing_stop" if _trailing_armed(position) else "stop_loss"

    if long and low <= stop:
        return ExitDecision(stop_reason, min(open_, stop))
    if not long and high >= stop:
        return ExitDecision(stop_reason, max(open_, stop))

    tp = position.take_profit
    if tp is not None:
        # gap a favor: abriu além do alvo, a ordem a mercado sai na abertura
        if long and high >= tp:
            return ExitDecision("take_profit", open_ if open_ >= tp else tp)
        if not long and low <= tp:
            return ExitDecision("take_profit", open_ if open_ <= tp else tp)

    _update_trailing(position, high if long else low)

    if position.time_limit_minutes is not None:
        if bar_end_ms >= position.opened_at_ms + position.time_limit_minutes * 60_000:
            return ExitDecision("time_limit", close)
    return None


def _trailing_armed(position: Position) -> bool:
    if position.trailing_distance is None or position.best_price is None:
        return False
    activation = position.trailing_activation or 0.0
    sign = 1 if position.direction == LONG else -1
    return sign * (position.best_price - position.entry_price) >= activation


def _update_trailing(position: Position, extreme: float) -> None:
    long = position.direction == LONG
    if position.best_price is None or (extreme > position.best_price if long else extreme < position.best_price):
        position.best_price = extreme
    if not _trailing_armed(position):
        return
    candidate = (
        position.best_price - position.trailing_distance
        if long
        else position.best_price + position.trailing_distance
    )
    # trailing só aperta, nunca afrouxa o stop
    if (long and candidate > position.stop_loss) or (not long and candidate < position.stop_loss):
        position.stop_loss = candidate
