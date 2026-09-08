"""Orquestração do bot: checa anúncios novos de listagem na Binance, avalia risco/momentum
e manda alerta pro Telegram.

Pensado pra rodar a cada 15-30 min via cron / GitHub Actions — diferente do bot de apostas
(1x/dia, jogo tem horário certo), cripto lista a qualquer hora, não tem "dia certo" pra
checar. Só analisa e alerta — não compra nada sozinho, mesma filosofia do bot de apostas.
"""
from __future__ import annotations

import logging

import config
from alerts.telegram_notifier import TelegramNotifier
from analysis.scoring import assess
from data.binance_client import BinanceClient
from storage.seen_listings import SeenListingsStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    client = BinanceClient()
    store = SeenListingsStore(config.STORAGE_PATH)
    notifier = TelegramNotifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)

    try:
        announcements = client.get_new_listing_announcements(
            config.BINANCE_ANNOUNCEMENTS_CATALOG_ID, config.BINANCE_ANNOUNCEMENTS_PAGE_SIZE
        )
    except Exception:
        logger.exception("Falha ao buscar anúncios de listagem")
        return

    seen = store.seen_ids()
    new_ones = [a for a in announcements if a.article_id not in seen]

    if not new_ones:
        logger.info("Nenhum anúncio novo desde a última checagem (%d conhecidos)", len(seen))
        return

    logger.info("%d anúncio(s) novo(s) encontrado(s)", len(new_ones))
    for ann in new_ones:
        ticker_24hr = None
        if ann.ticker:
            symbol = client.find_trading_usdt_pair(ann.ticker)
            if symbol:
                ticker_24hr = client.get_24hr_ticker(symbol)

        assessment = assess(ann.title, ticker_24hr)
        try:
            notifier.send_listing_alert(ann.title, ann.ticker, assessment)
        except Exception:
            logger.exception("Falha ao enviar alerta pro Telegram: %s", ann.title)

    # marca como visto só depois de tentar mandar todos — se o processo cair no meio, os que
    # falharam continuam "não vistos" e são retentados na próxima execução
    store.mark_seen([a.article_id for a in new_ones])


if __name__ == "__main__":
    main()
