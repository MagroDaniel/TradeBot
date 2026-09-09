"""Orquestração do bot: manda o relatório do dia anterior (1x/dia), resolve sinais abertos,
depois escaneia os pares configurados (`config.FOREX_SYMBOLS`) em busca de sinal técnico novo.
Mesma estrutura/ordem de `crypto-daytrade/main.py` — ver docstring lá pro raciocínio completo.

**Diferença em relação ao cripto**: forex fecha no fim de semana
(`data/schedule.py::is_forex_market_open`) — escanear fora da janela de mercado é
desperdício de cota da API (candle sem negociação real por trás) e resolver sinal aberto
também não teria novidade nenhuma pra checar.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import config
from alerts.telegram_notifier import TelegramNotifier
from analysis.outcomes import check_outcome
from analysis.performance import summarize
from analysis.signals import STRATEGY_VERSION, generate_signal, reprice_signal_for_entry
from data.schedule import date_brt, is_forex_market_open, today_brt
from data.twelvedata_client import TwelveDataClient, closed_candles
from storage.signals_store import SignalRecord, SignalsStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def send_daily_report_if_needed(store: SignalsStore, notifier: TelegramNotifier) -> None:
    today = today_brt().isoformat()
    if store.get_last_report_date() == today:
        return

    yesterday = today_brt() - timedelta(days=1)
    todays_records = [
        r for r in store.all_signals() if r.closed_at and date_brt(r.closed_at) == yesterday
    ]
    summary = summarize(todays_records)

    try:
        notifier.send_daily_report(yesterday.isoformat(), summary, todays_records)
    except Exception:
        logger.exception("Falha ao enviar relatório diário")
        return

    logger.info(
        "Relatório diário de %s enviado (%d sinal(is) resolvido(s))",
        yesterday.isoformat(), len(todays_records),
    )
    store.set_last_report_date(today)


def resolve_open_signals(client: TwelveDataClient, store: SignalsStore, notifier: TelegramNotifier) -> None:
    open_signals = store.open_signals()
    if not open_signals:
        logger.info("Nenhum sinal aberto pra resolver")
        return

    now = datetime.now(timezone.utc)
    updated: list[SignalRecord] = []
    for signal in open_signals:
        opened_at = datetime.fromisoformat(signal.opened_at)
        try:
            candles = client.get_candles(signal.symbol, interval=config.TIMEFRAME, outputsize=200)
        except Exception:
            logger.exception("Falha ao buscar candles pra resolver %s", signal.symbol)
            continue

        opened_at_ms = int(opened_at.timestamp() * 1000)
        relevant = [c for c in candles if c.open_time_ms >= opened_at_ms]

        outcome = check_outcome(signal, relevant)
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


def scan_for_new_signals(client: TwelveDataClient, store: SignalsStore, notifier: TelegramNotifier) -> None:
    new_signals = 0
    open_signals = store.open_signals()
    for symbol in config.FOREX_SYMBOLS:
        if any(s.symbol == symbol for s in open_signals):
            continue
        if len(open_signals) >= config.MAX_OPEN_POSITIONS:
            logger.info("Limite total de %d posições abertas atingido", config.MAX_OPEN_POSITIONS)
            break

        try:
            candles = closed_candles(client.get_candles(symbol, interval=config.TIMEFRAME, outputsize=100))
            higher_tf_candles = (
                closed_candles(client.get_candles(symbol, interval=config.HIGHER_TIMEFRAME, outputsize=50))
                if config.USE_HIGHER_TIMEFRAME_FILTER
                else None
            )
        except Exception:
            logger.exception("Falha ao buscar candles pra %s", symbol)
            continue

        signal = generate_signal(
            symbol,
            candles,
            higher_tf_candles=higher_tf_candles,
            min_range_expansion=config.MIN_RANGE_EXPANSION,
        )
        if signal is None:
            continue
        if sum(s.direction == signal.direction for s in open_signals) >= config.MAX_OPEN_PER_DIRECTION:
            logger.info(
                "Limite de %d posições %s abertas atingido",
                config.MAX_OPEN_PER_DIRECTION,
                signal.direction,
            )
            continue

        try:
            execution_price = client.get_current_price(symbol) or signal.entry
        except Exception:
            logger.exception("Falha ao buscar preço executável para %s; usando fechamento", symbol)
            execution_price = signal.entry
        signal = reprice_signal_for_entry(signal, execution_price)

        record = SignalRecord(
            symbol=signal.symbol,
            direction=signal.direction,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            target=signal.target,
            rsi_value=signal.rsi_value,
            reason=signal.reason,
            opened_at=datetime.now(timezone.utc).isoformat(),
            strategy_version=STRATEGY_VERSION,
            timeframe=config.TIMEFRAME,
            signal_candle_closed_at=(
                datetime.fromtimestamp(candles[-1].close_time_ms / 1000, tz=timezone.utc).isoformat()
                if candles[-1].close_time_ms is not None
                else None
            ),
            entry_mode="market_after_closed_candle",
            market_mode="forex",
        )
        try:
            notifier.send_signal_alert(record)
        except Exception:
            logger.exception("Falha ao enviar sinal pro Telegram: %s", symbol)
            continue

        store.add(record)
        open_signals.append(record)
        new_signals += 1

    logger.info("%d sinal(is) novo(s) entre %d par(es) escaneado(s)", new_signals, len(config.FOREX_SYMBOLS))


def main() -> None:
    if not is_forex_market_open():
        logger.info("Mercado de forex fechado agora — nada a fazer")
        return

    client = TwelveDataClient(config.TWELVEDATA_API_KEY)
    store = SignalsStore(config.STORAGE_PATH)
    notifier = TelegramNotifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)

    send_daily_report_if_needed(store, notifier)
    resolve_open_signals(client, store, notifier)
    scan_for_new_signals(client, store, notifier)


if __name__ == "__main__":
    main()
