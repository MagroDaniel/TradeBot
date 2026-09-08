"""Avalia risco/momentum de uma nova listagem — NÃO é uma previsão de "vai subir".

Diferente do bot de apostas (que compara a probabilidade do modelo contra a odd do mercado,
um número objetivo), não existe uma fórmula matemática confiável equivalente pra "essa moeda
nova vai bombar". Este módulo se limita a dois sinais objetivos e honestos:

- **Risco**: tags de risco que a própria Binance aplica no anúncio (Seed Tag, Innovation
  Zone, Monitoring Tag) — sinal mais confiável que qualquer heurística nossa, porque é a
  exchange avisando que o projeto é mais volátil/arriscado. Ausência de tag NÃO significa
  "seguro", só significa que a Binance não aplicou um aviso extra.
- **Momentum**: variação de preço e volume nas primeiras horas de negociação, se já estiver
  listado — puramente descritivo do que já aconteceu, não uma previsão do que vai acontecer.

Por isso `assess()` nunca produz uma recomendação binária "compra"/"não compra" — só resume
os dois sinais pra você decidir.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RISK_TAGS = ("Seed Tag", "Innovation Zone", "Monitoring Tag")


@dataclass(frozen=True)
class Assessment:
    risk_tags: list[str]
    price_change_percent: float | None  # None se ainda não tem dado de mercado (não listado)
    quote_volume: float | None  # volume nas últimas 24h, na moeda de cotação (ex: USDT)

    @property
    def is_high_risk(self) -> bool:
        return bool(self.risk_tags)

    def summary(self) -> str:
        if self.is_high_risk:
            risk = f"⚠️ Risco sinalizado pela Binance: {', '.join(self.risk_tags)}"
        else:
            risk = "Sem tag de risco da própria Binance (não significa que é seguro)"

        if self.price_change_percent is None:
            momentum = "ainda sem dado de mercado — o par não está sendo negociado ainda"
        else:
            sign = "+" if self.price_change_percent >= 0 else ""
            volume_str = f", volume 24h: {self.quote_volume:,.0f}" if self.quote_volume else ""
            momentum = f"{sign}{self.price_change_percent:.1f}% nas últimas 24h{volume_str}"

        return f"{risk}\n{momentum}"


def assess(title: str, ticker_24hr: dict[str, Any] | None) -> Assessment:
    """`ticker_24hr` é a resposta crua de `BinanceClient.get_24hr_ticker` (ou None se o par
    ainda não está sendo negociado)."""
    risk_tags = [tag for tag in RISK_TAGS if tag.lower() in title.lower()]
    price_change = float(ticker_24hr["priceChangePercent"]) if ticker_24hr else None
    quote_volume = float(ticker_24hr["quoteVolume"]) if ticker_24hr else None
    return Assessment(
        risk_tags=risk_tags,
        price_change_percent=price_change,
        quote_volume=quote_volume,
    )
