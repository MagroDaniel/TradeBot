"""Cliente para a API pública de mercado da Binance (`/api/v3/*`) — oficialmente documentada,
não exige chave de API. Usada pra achar os pares de maior volume e buscar candles (klines)
pra calcular os indicadores técnicos.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import requests

# Lido direto de os.getenv (não de config.py) de propósito — config.py levanta RuntimeError na
# importação se faltar credencial do Telegram, e este módulo precisa continuar importável sem
# nenhuma credencial pra suíte de testes rodar sem .env (ver CLAUDE.md, seção "Comandos").
#
# BINANCE_API_BASE_URL normalmente fica vazia (usa a Binance direto) — só é setada no GitHub
# Actions, apontando pro binance-proxy/ (ver README daquele diretório): a Binance devolve HTTP
# 451 pra requisições vindas de infraestrutura dos EUA, onde o runner do Actions roda, então lá
# a chamada precisa passar por um proxy fora dos EUA. Localmente (Brasil) isso não é necessário.
BASE_URL = os.getenv("BINANCE_API_BASE_URL", "https://api.binance.com/api/v3")

# Stablecoins pareadas com USDT (ex: USDCUSDT) têm volume alto mas preço travado em ~1.00 —
# nunca geram cruzamento de médias de verdade, só desperdiçam uma chamada de klines por
# execução. Filtradas na origem em vez de deixar o gerador de sinal descartar depois.
_STABLECOIN_BASES = {"USDC", "USD1", "FDUSD", "TUSD", "DAI", "RLUSD", "BUSD", "USDP", "GUSD"}


@dataclass(frozen=True)
class Candle:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class BinanceClient:
    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout

    def get_top_symbols_by_volume(self, quote_asset: str = "USDT", limit: int = 25) -> list[str]:
        """Pares {X}{quote_asset} com maior volume nas últimas 24h — usa uma chamada só
        (ticker/24hr sem `symbol` devolve todos os pares), sem precisar de exchangeInfo."""
        response = requests.get(f"{BASE_URL}/ticker/24hr", timeout=self.timeout)
        response.raise_for_status()
        tickers = response.json()

        candidates = [
            t
            for t in tickers
            if t["symbol"].endswith(quote_asset)
            and t["symbol"][: -len(quote_asset)] not in _STABLECOIN_BASES
        ]
        candidates.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
        return [t["symbol"] for t in candidates[:limit]]

    def get_klines(self, symbol: str, interval: str = "15m", limit: int = 100) -> list[Candle]:
        """Candles mais recentes primeiro na ordem que a Binance devolve (mais antigo
        primeiro) — não inverte, quem usa decide a ordem que precisa."""
        response = requests.get(
            f"{BASE_URL}/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=self.timeout,
        )
        response.raise_for_status()
        raw = response.json()
        return [
            Candle(
                open_time_ms=c[0],
                open=float(c[1]),
                high=float(c[2]),
                low=float(c[3]),
                close=float(c[4]),
                volume=float(c[5]),
            )
            for c in raw
        ]

    def get_current_price(self, symbol: str) -> float | None:
        response = requests.get(
            f"{BASE_URL}/ticker/price", params={"symbol": symbol}, timeout=self.timeout
        )
        if response.status_code != 200:
            return None
        return float(response.json()["price"])
