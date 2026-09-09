"""Orquestração do bot: manda o relatório do dia anterior (1x/dia, na primeira execução após
meia-noite BRT), resolve sinais abertos (checa se bateu stop/alvo desde a última execução),
depois escaneia os pares de maior volume em busca de sinal técnico novo.

Ordem de execução — relatório, depois resolver, depois escanear — é deliberada, mesmo
raciocínio do bot de apostas (resultado de ontem antes dos picks de hoje): fecha o que já
aconteceu antes de gerar coisa nova. Pensado pra rodar a cada 10 min via cron/GitHub
Actions — cripto não tem "horário de jogo" como futebol, mas o relatório diário só sai 1x/dia
mesmo assim (ver `send_daily_report_if_needed`).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import config
from alerts.telegram_notifier import TelegramNotifier
from analysis.outcomes import check_outcome
from analysis.performance import summarize
from analysis.signals import STRATEGY_VERSION, generate_signal, reprice_signal_for_entry
from data.binance_client import BinanceClient, closed_candles
from data.schedule import date_brt, today_brt
from storage.signals_store import SignalRecord, SignalsStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def send_daily_report_if_needed(store: SignalsStore, notifier: TelegramNotifier) -> None:
    """Manda o relatório do dia anterior (corte em meia-noite BRT) na primeira execução do
    dia — não a cada run, então checa `last_report_date` antes de fazer qualquer coisa.
    Mesma ordem do bot de apostas: resultado fechado antes de qualquer coisa nova."""
    today = today_brt().isoformat()
    if store.get_last_report_date() == today:
        return  # já mandou hoje, não repete a cada execução de 10 em 10 min

    yesterday = today_brt() - timedelta(days=1)
    todays_records = [
        r for r in store.all_signals() if r.closed_at and date_brt(r.closed_at) == yesterday
    ]
    summary = summarize(todays_records)

    try:
        notifier.send_daily_report(yesterday.isoformat(), summary, todays_records)
    except Exception:
        logger.exception("Falha ao enviar relatório diário")
        return  # não marca como enviado — tenta de novo na próxima execução

    logger.info(
        "Relatório diário de %s enviado (%d sinal(is) resolvido(s))",
        yesterday.isoformat(), len(todays_records),
    )

    store.set_last_report_date(today)


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


def scan_for_new_signals(client: BinanceClient, store: SignalsStore, notifier: TelegramNotifier) -> None:
    try:
        symbols = client.get_top_symbols_by_volume(limit=config.TOP_SYMBOLS_COUNT)
    except Exception:
        logger.exception("Falha ao buscar pares de maior volume")
        return

    new_signals = 0
    open_signals = store.open_signals()
    for symbol in symbols:
        if any(s.symbol == symbol for s in open_signals):
            continue  # não empilha sinal novo em cima de um já aberto pro mesmo par
        if len(open_signals) >= config.MAX_OPEN_POSITIONS:
            logger.info("Limite total de %d posições abertas atingido", config.MAX_OPEN_POSITIONS)
            break

        try:
            candles = closed_candles(client.get_klines(symbol, interval=config.TIMEFRAME, limit=100))
            # 50 candles de 1h só pra confirmar tendência (EMA9/EMA21 precisa de pelo menos
            # 21) — ver analysis/signals.py::confirms_higher_timeframe_trend
            higher_tf_candles = closed_candles(
                client.get_klines(symbol, interval=config.HIGHER_TIMEFRAME, limit=50)
            )
        except Exception:
            logger.exception("Falha ao buscar candles pra %s", symbol)
            continue

        signal = generate_signal(symbol, candles, higher_tf_candles=higher_tf_candles)
        if signal is None:
            continue
        if signal.direction not in config.ALLOWED_DIRECTIONS:
            logger.info("Sinal %s em %s ignorado no modo %s", signal.direction, symbol, config.TRADING_MODE)
            continue
        if sum(s.direction == signal.direction for s in open_signals) >= config.MAX_OPEN_PER_DIRECTION:
            logger.info(
                "Limite de %d posições %s abertas atingido",
                config.MAX_OPEN_PER_DIRECTION,
                signal.direction,
            )
            continue

        # O indicador foi confirmado no candle já fechado. O preço de execução é o
        # preço atual, não o fechamento histórico que originou o gatilho; em caso de
        # gap, stop/alvo são reposicionados para preservar o risco ATR planejado.
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
            market_mode=config.TRADING_MODE,
        )
        try:
            notifier.send_signal_alert(record)
        except Exception:
            logger.exception("Falha ao enviar sinal pro Telegram: %s", symbol)
            continue

        store.add(record)
        open_signals.append(record)
        new_signals += 1

    logger.info("%d sinal(is) novo(s) entre %d par(es) escaneado(s)", new_signals, len(symbols))


def main() -> None:
    client = BinanceClient()
    store = SignalsStore(config.STORAGE_PATH)
    notifier = TelegramNotifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)

    send_daily_report_if_needed(store, notifier)
    resolve_open_signals(client, store, notifier)
    scan_for_new_signals(client, store, notifier)


if __name__ == "__main__":
    main()
