"""Modo OBSERVAÇÃO da estratégia de notícia (`analysis/news_signals.py`) — imprime o que a
lógica diria pros eventos econômicos da semana, mas NÃO manda nada pro Telegram nem grava em
`storage/`. Existe porque essa estratégia não passou pelo mesmo processo de backtest das
outras 3 (ver docstring de `analysis/news_signals.py` e README.md) — a intenção é rodar isso
por algumas semanas e comparar manualmente o que teria sido dito com o que realmente aconteceu,
antes de decidir se vira alerta de produção de verdade.

Uso:
    python news_watch.py

Pensado pra rodar manualmente (ou via cron/GitHub Actions só de observação, sem nenhum efeito
colateral) — não é chamado por `main.py`, não faz parte do fluxo de produção.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import config
from analysis.news_signals import STRATEGY_VERSION, WAIT_MINUTES_AFTER_RELEASE, generate_signal
from data.forexfactory_client import ForexFactoryClient
from data.twelvedata_client import TwelveDataClient, closed_candles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    print(f"=== Modo observação — {STRATEGY_VERSION} ===")
    print("NÃO manda alerta, NÃO grava sinal. Só mostra o que a lógica diria.\n")

    ff_client = ForexFactoryClient()
    events = ff_client.get_relevant_high_impact_events()
    print(f"{len(events)} evento(s) de alto impacto (USD/EUR/GBP) essa semana.\n")

    now = datetime.now(timezone.utc)
    price_client = TwelveDataClient(config.TWELVEDATA_API_KEY)
    candles_cache: dict[str, list] = {}

    any_signal = False
    for event in events:
        event_dt = event.datetime_utc
        status = "futuro" if event_dt and event_dt > now else ("sem 'actual' ainda" if not event.actual else "divulgado")
        print(f"- {event.date} | {event.country} | {event.title} | forecast={event.forecast} previous={event.previous} actual={event.actual} ({status})")

        if not event.has_surprise():
            continue

        for symbol in config.FOREX_SYMBOLS:
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
                continue
            any_signal = True
            print(
                f"    >>> TERIA GERADO sinal: {symbol} {signal.direction.upper()} "
                f"entrada~{signal.entry:.5f} stop~{signal.stop_loss:.5f} alvo~{signal.target:.5f}"
            )
            print(f"        motivo: {signal.reason}")

    if not any_signal:
        print(f"\nNenhum sinal gerado agora (precisa de 'actual' divulgado + {WAIT_MINUTES_AFTER_RELEASE}min de espera).")


if __name__ == "__main__":
    main()
