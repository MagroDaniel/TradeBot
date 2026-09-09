"""Cliente para a API da Twelve Data (`time_series`) — usada pra buscar candles de pares de
moedas. Ao contrário da Binance (cripto), forex não tem uma exchange central nem volume real
por par (é mercado OTC), então `Candle.volume` aqui é sempre 0.0 — mantido no dataclass só pra
manter a mesma interface que `analysis/indicators.py` e `analysis/signals.py` esperam (nenhum
dos dois usa volume, então isso não muda nenhum comportamento).

Diferente da Binance, a Twelve Data cobra por chamada: free tier tem cota de 800
chamadas/dia e 8/minuto (ver `docs/`). Por isso o escaneamento ao vivo (`main.py`) começa
com um par só (EUR/USD) — dá folga grande na cota mesmo rodando a cada 10 minutos.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

# Lido direto de os.getenv (não de config.py) de propósito, mesmo padrão de
# `crypto-daytrade/data/binance_client.py`: config.py levanta RuntimeError na importação se
# faltar credencial do Telegram, e este módulo precisa continuar importável sem nenhuma
# credencial pra suíte de testes rodar sem .env.
BASE_URL = "https://api.twelvedata.com"

# Duração de cada intervalo suportado, em milissegundos — usado só pra calcular
# `close_time_ms` (a Twelve Data não devolve isso pronto como a Binance devolve).
_INTERVAL_MS = {
    "1min": 60_000,
    "5min": 5 * 60_000,
    "15min": 15 * 60_000,
    "30min": 30 * 60_000,
    "45min": 45 * 60_000,
    "1h": 60 * 60_000,
    "2h": 2 * 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1day": 24 * 60 * 60_000,
}


@dataclass(frozen=True)
class Candle:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time_ms: int | None = None


def closed_candles(candles: list[Candle], now: datetime | None = None) -> list[Candle]:
    """Mesma função de `crypto-daytrade/data/binance_client.py` — descarta candle ainda em
    formação (repintaria EMA/RSI/ATR se usado)."""
    now_ms = int((now or datetime.now(timezone.utc)).timestamp() * 1000)
    return [c for c in candles if c.close_time_ms is None or c.close_time_ms <= now_ms]


class TwelveDataError(Exception):
    """A API respondeu com `status: error` (chave inválida, símbolo inválido, cota
    estourada etc.) — corpo completo do erro fica em `str(exc)` pra facilitar log/debug."""


def _parse_datetime_utc(value: str) -> int:
    """Twelve Data devolve `datetime` como string sem fuso (ex: "2026-09-10 07:00:00");
    pedimos `timezone=UTC` explicitamente na chamada, então tratamos como UTC aqui."""
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _parse_values(raw_values: list[dict], interval: str) -> list[Candle]:
    interval_ms = _INTERVAL_MS.get(interval)
    candles = []
    for v in raw_values:
        open_time_ms = _parse_datetime_utc(v["datetime"])
        candles.append(
            Candle(
                open_time_ms=open_time_ms,
                open=float(v["open"]),
                high=float(v["high"]),
                low=float(v["low"]),
                close=float(v["close"]),
                volume=float(v.get("volume") or 0.0),
                close_time_ms=(open_time_ms + interval_ms) if interval_ms else None,
            )
        )
    # A API devolve mais recente primeiro por padrão; pedimos order=ASC, mas reordena aqui
    # também como garantia — o resto do código (analysis/signals.py) espera mais antigo
    # primeiro, mesma convenção da Binance.
    candles.sort(key=lambda c: c.open_time_ms)
    return candles


class TwelveDataClient:
    def __init__(self, api_key: str | None = None, timeout: int = 15) -> None:
        self.api_key = api_key or os.getenv("TWELVEDATA_API_KEY", "")
        self.timeout = timeout

    def _get(self, params: dict) -> dict:
        response = requests.get(
            f"{BASE_URL}/time_series",
            params={**params, "apikey": self.api_key, "timezone": "UTC"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("status") == "error":
            raise TwelveDataError(str(payload))
        return payload

    def get_candles(self, symbol: str, interval: str = "15min", outputsize: int = 100) -> list[Candle]:
        """Candles mais recentes — equivalente a `BinanceClient.get_klines`. Uma chamada
        só (a API já devolve `outputsize` candles numa resposta)."""
        payload = self._get(
            {"symbol": symbol, "interval": interval, "outputsize": outputsize, "order": "ASC"}
        )
        return _parse_values(payload.get("values", []), interval)

    def get_historical_candles(
        self, symbol: str, interval: str, start_time_ms: int, end_time_ms: int
    ) -> list[Candle]:
        """Candles de um intervalo arbitrário — só pro backtest (`backtest/history.py`), igual
        `BinanceClient.get_historical_klines`. Pagina em blocos de 5000 (o máximo por chamada
        no free tier da Twelve Data) usando `start_date`/`end_date`, avançando o cursor pro
        `open_time` do último candle da página + 1 intervalo a cada volta.
        """
        interval_ms = _INTERVAL_MS.get(interval)
        if interval_ms is None:
            raise ValueError(f"Intervalo não suportado: {interval}")

        candles: list[Candle] = []
        cursor_ms = start_time_ms
        page_size = 5000
        page_count = 0
        while cursor_ms < end_time_ms:
            if page_count > 0:
                # free tier: 8 chamadas/minuto — espaça as páginas pra não estourar o limite
                # num backtest que precisa de várias (365 dias de 15min passa de 5000 candles).
                time.sleep(8)
            page_count += 1

            start_str = datetime.fromtimestamp(cursor_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            end_str = datetime.fromtimestamp(end_time_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            payload = self._get(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "start_date": start_str,
                    "end_date": end_str,
                    "outputsize": page_size,
                    "order": "ASC",
                }
            )
            raw = payload.get("values", [])
            if not raw:
                break

            batch = _parse_values(raw, interval)
            candles.extend(batch)

            if len(raw) < page_size:
                break  # última página — menos que o máximo significa que chegou no fim
            cursor_ms = batch[-1].open_time_ms + interval_ms

        # dedup por open_time_ms (a página seguinte pode repetir o candle de borda) e reordena
        by_time = {c.open_time_ms: c for c in candles}
        return sorted(by_time.values(), key=lambda c: c.open_time_ms)

    def get_current_price(self, symbol: str) -> float | None:
        response = requests.get(
            f"{BASE_URL}/price", params={"symbol": symbol, "apikey": self.api_key}, timeout=self.timeout
        )
        if not response.ok:
            return None
        payload = response.json()
        if not isinstance(payload, dict) or "price" not in payload:
            return None
        try:
            return float(payload["price"])
        except (TypeError, ValueError):
            return None
