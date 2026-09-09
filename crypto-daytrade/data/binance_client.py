"""Cliente para a API pública de mercado da Binance (`/api/v3/*`) — oficialmente documentada,
não exige chave de API. Usada pra achar os pares de maior volume e buscar candles (klines)
pra calcular os indicadores técnicos.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

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
    # A Binance informa este valor em cada kline. Mantê-lo evita tratar o candle
    # ainda aberto como dado histórico utilizável pelo modelo.
    close_time_ms: int | None = None


def closed_candles(candles: list[Candle], now: datetime | None = None) -> list[Candle]:
    """Retorna somente candles que já fecharam.

    A última kline retornada pela Binance normalmente ainda está em formação. Seus
    close/high/low podem mudar, portanto usá-la em EMA, RSI ou ATR faria o sinal
    repintar. Candles antigos sem ``close_time_ms`` continuam utilizáveis para não
    quebrar caches e fixtures legados; respostas novas da API sempre trazem o campo.
    """
    now_ms = int((now or datetime.now(timezone.utc)).timestamp() * 1000)
    return [c for c in candles if c.close_time_ms is None or c.close_time_ms <= now_ms]


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
                close_time_ms=int(c[6]),
            )
            for c in raw
        ]

    def get_historical_klines(
        self, symbol: str, interval: str, start_time_ms: int, end_time_ms: int
    ) -> list[Candle]:
        """Candles de um intervalo de tempo arbitrário (não só "os N mais recentes" como
        `get_klines`) — pagina em blocos de 1000 (o máximo por chamada da Binance) usando
        `startTime`, avançando pro `open_time` do último candle + 1ms a cada volta. Só existe
        pro backtest (`backtest/history.py`); a execução ao vivo nunca precisa de histórico
        profundo, só dos últimos N candles.
        """
        candles: list[Candle] = []
        cursor = start_time_ms
        while cursor < end_time_ms:
            response = requests.get(
                f"{BASE_URL}/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_time_ms,
                    "limit": 1000,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            raw = response.json()
            if not raw:
                break

            batch = [
                Candle(
                    open_time_ms=c[0],
                    open=float(c[1]),
                    high=float(c[2]),
                    low=float(c[3]),
                    close=float(c[4]),
                    volume=float(c[5]),
                    close_time_ms=int(c[6]),
                )
                for c in raw
            ]
            candles.extend(batch)

            if len(raw) < 1000:
                break  # última página — menos de 1000 significa que chegou no fim
            cursor = batch[-1].open_time_ms + 1

        return candles

    def get_current_price(self, symbol: str) -> float | None:
        response = requests.get(
            f"{BASE_URL}/ticker/price", params={"symbol": symbol}, timeout=self.timeout
        )
        if response.status_code != 200:
            return None
        return float(response.json()["price"])
