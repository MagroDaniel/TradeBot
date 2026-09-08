"""Cliente para APIs públicas da Binance — nenhuma delas exige chave de API.

- `/api/v3/*` (`MARKET_BASE_URL`) é a API pública de mercado, oficialmente documentada.
- O feed de anúncios (`ANNOUNCEMENTS_URL`) é o endpoint que o próprio site da Binance usa
  internamente pra listar comunicados — **não é uma API oficialmente documentada/suportada**,
  pode mudar de formato ou parar de funcionar sem aviso. Se o bot parar de achar anúncios
  novos, confira se `catalogId=48` ainda corresponde a "New Cryptocurrency Listing"
  (confirmado manualmente em 2026-09; testado batendo o retorno contra o site).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

MARKET_BASE_URL = "https://api.binance.com/api/v3"
ANNOUNCEMENTS_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query"

# Extrai o ticker entre parênteses do título do anúncio, ex:
# "Binance Will List MarsCoin (MARSCOIN) with Seed Tag Applied" -> "MARSCOIN"
_TITLE_TICKER_RE = re.compile(r"\(([A-Z0-9]{2,15})\)")


@dataclass(frozen=True)
class Announcement:
    article_id: int
    title: str
    ticker: str | None  # extraído do título via regex — pode não achar em títulos atípicos


class BinanceClient:
    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout

    def get_new_listing_announcements(
        self, catalog_id: str, page_size: int = 20
    ) -> list[Announcement]:
        """Últimos anúncios da categoria de novas listagens, mais recente primeiro (é a
        ordem que a Binance já devolve)."""
        response = requests.get(
            ANNOUNCEMENTS_URL,
            params={"catalogId": catalog_id, "pageNo": 1, "pageSize": page_size},
            timeout=self.timeout,
        )
        response.raise_for_status()
        articles = response.json().get("data", {}).get("articles", []) or []

        announcements = []
        for article in articles:
            title = article.get("title", "")
            match = _TITLE_TICKER_RE.search(title)
            announcements.append(
                Announcement(
                    article_id=article["id"],
                    title=title,
                    ticker=match.group(1) if match else None,
                )
            )
        return announcements

    def find_trading_usdt_pair(self, ticker: str) -> str | None:
        """Confere se {ticker}USDT já existe e está operando (status TRADING) na Binance —
        None se ainda não foi listado, se o símbolo não existe, ou está em pausa (BREAK)."""
        symbol = f"{ticker}USDT"
        response = requests.get(
            f"{MARKET_BASE_URL}/exchangeInfo", params={"symbol": symbol}, timeout=self.timeout
        )
        if response.status_code != 200:
            return None  # símbolo inválido/inexistente — Binance responde 400 nesse caso
        symbols = response.json().get("symbols", [])
        if symbols and symbols[0].get("status") == "TRADING":
            return symbol
        return None

    def get_24hr_ticker(self, symbol: str) -> dict[str, Any] | None:
        """Estatísticas de preço/volume das últimas 24h — usado como sinal de momentum
        (pouco depois de listar, a janela de 24h é essencialmente "desde a listagem")."""
        response = requests.get(
            f"{MARKET_BASE_URL}/ticker/24hr", params={"symbol": symbol}, timeout=self.timeout
        )
        if response.status_code != 200:
            return None
        return response.json()
