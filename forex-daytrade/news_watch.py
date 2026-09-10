"""Orquestração da estratégia de notícia/surpresa de calendário econômico
(`analysis/news_signals.py`) — a quarta abordagem testada no projeto, e a única que NÃO passou
pelo backtest contra histórico real das outras 3 (não existe fonte gratuita com valor `actual`
histórico — ver `data/forexfactory_client.py` e README.md).

**Modo observação, não produção validada**: manda pro Telegram (`send_experimental_signal_alert`/
`send_experimental_result`), mas toda mensagem carrega o aviso explícito de que essa estratégia
ainda não foi validada — decisão do usuário (2026-09-10) pra poder acompanhar em tempo real em
vez de só olhar log, sabendo do risco. Persiste em `config.NEWS_STORAGE_PATH`, um arquivo
SEPARADO de `config.STORAGE_PATH` (nunca mistura com as estratégias de preço). Resolve outcome
(bateu alvo/stop/expirou) do mesmo jeito que as outras estratégias — a ideia é medir expectância
real com o tempo, pra decidir com dado (não só sensação) se vira sinal de produção de verdade.

Pensado pra rodar a cada 30 min via cron/GitHub Actions (`.github/workflows/forex_news_alert.yml`)
— não é chamado por `main.py`, que continua só com as estratégias de preço (hoje sem nenhuma em
produção, ver README.md).

Uso:
    python news_watch.py
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import config
from alerts.telegram_notifier import TelegramNotifier
from analysis.news_signals import (
    STRATEGY_VERSION,
    generate_signal,
    reprice_signal_for_entry,
)
from analysis.outcomes import check_outcome
from analysis.performance import summarize
from data.forexfactory_client import EconomicEvent, ForexFactoryClient
from data.schedule import date_brt, today_brt
from data.twelvedata_client import TwelveDataClient, closed_candles
from storage.signals_store import SignalRecord, SignalsStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _event_symbol_key(event: EconomicEvent, symbol: str) -> str:
    """Chave (evento, símbolo) — não só evento, porque no futuro um mesmo evento pode gerar
    sinal pra mais de um par (`config.FOREX_SYMBOLS` com mais de um símbolo)."""
    return f"{event.country}|{event.title}|{event.date}|{symbol}"


def send_weekly_report_if_needed(store: SignalsStore, notifier: TelegramNotifier) -> None:
    today = today_brt()
    if today.weekday() != 0:  # 0 = segunda-feira
        return
    today_iso = today.isoformat()
    if store.get_last_weekly_report_date() == today_iso:
        return

    period_end = today
    period_start = today - timedelta(days=7)
    records = [
        r for r in store.all_signals()
        if r.closed_at and period_start <= date_brt(r.closed_at) < period_end
    ]
    summary = summarize(records)

    try:
        notifier.send_weekly_report(
            period_start.isoformat(), (period_end - timedelta(days=1)).isoformat(), summary, records
        )
    except Exception:
        logger.exception("Falha ao enviar relatório semanal (notícia)")
        return
    store.set_last_weekly_report_date(today_iso)


def send_monthly_report_if_needed(store: SignalsStore, notifier: TelegramNotifier) -> None:
    today = today_brt()
    if today.day != 1:
        return
    today_iso = today.isoformat()
    if store.get_last_monthly_report_date() == today_iso:
        return

    this_month_start = today.replace(day=1)
    prev_month_end = this_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    records = [
        r for r in store.all_signals()
        if r.closed_at and prev_month_start <= date_brt(r.closed_at) < this_month_start
    ]
    summary = summarize(records)
    month_label = f"{prev_month_start.year}-{prev_month_start.month:02d}"

    try:
        notifier.send_monthly_report(month_label, summary, records)
    except Exception:
        logger.exception("Falha ao enviar relatório mensal (notícia)")
        return
    store.set_last_monthly_report_date(today_iso)


def resolve_open_news_signals(
    price_client: TwelveDataClient, store: SignalsStore, notifier: TelegramNotifier
) -> None:
    open_signals = store.open_signals()
    if not open_signals:
        logger.info("Nenhum sinal de notícia aberto pra resolver")
        return

    now = datetime.now(timezone.utc)
    updated: list[SignalRecord] = []
    for signal in open_signals:
        opened_at = datetime.fromisoformat(signal.opened_at)
        try:
            candles = price_client.get_candles(signal.symbol, interval="1h", outputsize=200)
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
            notifier.send_experimental_result(signal)
        except Exception:
            logger.exception("Falha ao enviar resultado experimental pro Telegram: %s", signal.symbol)

    if updated:
        store.update(updated)
    logger.info("%d/%d sinal(is) de notícia resolvido(s)", len(updated), len(open_signals))


def scan_for_news_signals(
    ff_client: ForexFactoryClient,
    price_client: TwelveDataClient,
    store: SignalsStore,
    notifier: TelegramNotifier,
    now: datetime | None = None,
) -> None:
    events = ff_client.get_relevant_high_impact_events()
    now = now or datetime.now(timezone.utc)
    candles_cache: dict[str, list] = {}

    new_signals = 0
    for event in events:
        if not event.has_surprise():
            continue

        for symbol in config.FOREX_SYMBOLS:
            key = _event_symbol_key(event, symbol)
            if store.has_seen_news_event(key):
                continue  # já mandamos sinal (ou já sabemos que não gera) pra esse par antes

            if symbol not in candles_cache:
                try:
                    candles_cache[symbol] = closed_candles(
                        price_client.get_candles(symbol, interval="1h", outputsize=100)
                    )
                except Exception:
                    logger.exception("Falha ao buscar candles pra %s", symbol)
                    candles_cache[symbol] = []

            signal = generate_signal(event, symbol, candles_cache[symbol], now=now)
            if signal is None:
                # Pode ser só a janela de espera de 15min ainda não ter fechado — não marca
                # como visto, pra tentar de novo na próxima execução (roda a cada 30min).
                continue

            try:
                execution_price = price_client.get_current_price(symbol) or signal.entry
            except Exception:
                logger.exception("Falha ao buscar preço executável pra %s; usando fechamento", symbol)
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
                opened_at=now.isoformat(),
                strategy_version=STRATEGY_VERSION,
                timeframe="1h",
                entry_mode="market_after_wait_window",
                market_mode="forex_experimental",
            )
            try:
                notifier.send_experimental_signal_alert(record)
            except Exception:
                logger.exception("Falha ao enviar sinal experimental pro Telegram: %s", symbol)
                continue  # não marca como visto — tenta mandar de novo na próxima execução

            store.add(record)
            store.mark_news_event_seen(key)
            new_signals += 1

    logger.info("%d sinal(is) de notícia novo(s) entre %d evento(s) da semana", new_signals, len(events))


def main() -> None:
    ff_client = ForexFactoryClient()
    price_client = TwelveDataClient(config.TWELVEDATA_API_KEY)
    store = SignalsStore(config.NEWS_STORAGE_PATH)
    notifier = TelegramNotifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)

    send_weekly_report_if_needed(store, notifier)
    send_monthly_report_if_needed(store, notifier)
    resolve_open_news_signals(price_client, store, notifier)
    scan_for_news_signals(ff_client, price_client, store, notifier)


if __name__ == "__main__":
    main()
