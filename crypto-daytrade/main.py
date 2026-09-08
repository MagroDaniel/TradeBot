"""Orquestração do bot: resolve sinais abertos (checa se bateu stop/alvo desde a última
execução), depois escaneia os pares de maior volume em busca de sinal técnico novo.

Ordem de execução — resolver antes de escanear — é deliberada, mesmo raciocínio do bot de
apostas (resultado de ontem antes dos picks de hoje): confirma o resultado do que já foi
alertado antes de gerar coisa nova. Pensado pra rodar a cada 15-30 min via cron/GitHub
Actions — cripto não tem "horário de jogo" como futebol.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import config
from alerts.telegram_notifier import TelegramNotifier
from analysis.signals import generate_signal
from data.binance_client import BinanceClient, Candle
from storage.signals_store import SignalRecord, SignalsStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _check_outcome(signal: SignalRecord, candles: list[Candle]) -> tuple[str, float] | None:
    """Retorna (status, preço de fechamento) se o alvo ou o stop foi tocado em algum candle
    desde a abertura do sinal — checa o stop primeiro em cada candle (padrão conservador de
    backtest: evita superestimar acerto quando os dois seriam tocados no mesmo candle)."""
    for c in candles:
        if signal.direction == "long":
            if c.low <= signal.stop_loss:
                return "stop_hit", signal.stop_loss
            if c.high >= signal.target:
                return "target_hit", signal.target
        else:
            if c.high >= signal.stop_loss:
                return "stop_hit", signal.stop_loss
            if c.low <= signal.target:
                return "target_hit", signal.target
    return None


def resolve_open_signals(client: BinanceClient, store: SignalsStore, notifier: TelegramNotifier) -> None:
    open_signals = store.open_signals()
    if not open_signals:
        logger.info("Nenhum sinal aberto pra resolver")
        return

    now = datetime.now(timezone.utc)
    updated: list[SignalRecord] = []
    for signal in open_signals:
        opened_at = datetime.fromisoformat(signal.opened_at)
        try:
            candles = client.get_klines(signal.symbol, interval=config.TIMEFRAME, limit=200)
        except Exception:
            logger.exception("Falha ao buscar candles pra resolver %s", signal.symbol)
            continue

        opened_at_ms = int(opened_at.timestamp() * 1000)
        relevant = [c for c in candles if c.open_time_ms >= opened_at_ms]

        outcome = _check_outcome(signal, relevant)
        if outcome is None and now - opened_at > timedelta(hours=config.SIGNAL_EXPIRY_HOURS):
            last_close = relevant[-1].close if relevant else signal.entry
            outcome = ("expired", last_close)

        if outcome is None:
            continue

        status, close_price = outcome
        signal.status = status
        signal.closed_at = now.isoformat()
        signal.close_price = close_price
        updated.append(signal)

        try:
            notifier.send_result(signal)
        except Exception:
            logger.exception("Falha ao enviar resultado pro Telegram: %s", signal.symbol)

    if updated:
        store.update(updated)
    logger.info("%d/%d sinal(is) aberto(s) resolvido(s)", len(updated), len(open_signals))


def scan_for_new_signals(client: BinanceClient, store: SignalsStore, notifier: TelegramNotifier) -> None:
    try:
        symbols = client.get_top_symbols_by_volume(limit=config.TOP_SYMBOLS_COUNT)
    except Exception:
        logger.exception("Falha ao buscar pares de maior volume")
        return

    new_signals = 0
    for symbol in symbols:
        if store.has_open_signal_for(symbol):
            continue  # não empilha sinal novo em cima de um já aberto pro mesmo par

        try:
            candles = client.get_klines(symbol, interval=config.TIMEFRAME, limit=100)
        except Exception:
            logger.exception("Falha ao buscar candles pra %s", symbol)
            continue

        signal = generate_signal(symbol, candles)
        if signal is None:
            continue

        record = SignalRecord(
            symbol=signal.symbol,
            direction=signal.direction,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            target=signal.target,
            rsi_value=signal.rsi_value,
            reason=signal.reason,
            opened_at=datetime.now(timezone.utc).isoformat(),
        )
        try:
            notifier.send_signal_alert(record)
        except Exception:
            logger.exception("Falha ao enviar sinal pro Telegram: %s", symbol)
            continue

        store.add(record)
        new_signals += 1

    logger.info("%d sinal(is) novo(s) entre %d par(es) escaneado(s)", new_signals, len(symbols))


def main() -> None:
    client = BinanceClient()
    store = SignalsStore(config.STORAGE_PATH)
    notifier = TelegramNotifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)

    resolve_open_signals(client, store, notifier)
    scan_for_new_signals(client, store, notifier)


if __name__ == "__main__":
    main()
