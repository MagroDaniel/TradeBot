"""Cliente do feed público de calendário econômico da Forex Factory
(`nfs.faireconomy.media`) — gratuito, sem chave de API nem login, usado amplamente pela
comunidade de trading algorítmico (feed oficial por trás de vários indicadores de MT4/MT5).

**Limitação importante, documentada pra não ser esquecida**: esse feed só cobre a semana
atual/próxima — não tem valor "realizado" (actual) de datas passadas, só previsto/anterior.
Ou seja, **não dá pra backtestar uma estratégia de notícia contra histórico real com essa
fonte** (as APIs que dariam isso são pagas — ver README.md). Por isso `analysis/news_signals.py`
não passou pelo mesmo processo de validação por backtest que as outras 3 estratégias desse
projeto — é uma exceção deliberada, documentada, decidida explicitamente pelo usuário
(2026-09-09), não um descuido.

Rate limit conhecido (desde ago/2024): no máximo 2 downloads a cada 5 minutos, valendo pra
qualquer formato (.json/.xml/.ics/.csv) — cachear localmente e não buscar de novo com mais
frequência que isso.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import requests

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Moedas que os pares hoje cobertos (EUR/USD, GBP/USD) reagem diretamente.
RELEVANT_CURRENCIES = frozenset({"USD", "EUR", "GBP"})


@dataclass(frozen=True)
class EconomicEvent:
    title: str
    country: str  # código de moeda: "USD", "EUR", "GBP" etc.
    date: str  # ISO 8601 como vem no feed (geralmente com timezone)
    impact: str  # "High" | "Medium" | "Low" | "Holiday" (valores exatos do feed)
    forecast: str | None
    previous: str | None
    actual: str | None  # normalmente None pra eventos futuros

    @property
    def datetime_utc(self) -> datetime | None:
        """Parseia `date` pra um datetime UTC — None se o formato vier inesperado (não
        derruba o resto do parsing por causa de um evento malformado)."""
        try:
            dt = datetime.fromisoformat(self.date)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def has_surprise(self) -> bool:
        """True só se `actual` já foi divulgado E `forecast` existe pra comparar — sem os
        dois, não dá pra calcular surpresa (ver `analysis/news_signals.py`)."""
        return bool(self.actual) and bool(self.forecast)


class ForexFactoryClient:
    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout

    def get_week_events(self) -> list[EconomicEvent]:
        """Todos os eventos da semana atual/próxima, sem filtrar — quem usa decide o que
        filtrar (moeda, impacto). Levanta a exceção do `requests` se a chamada falhar; não
        engole erro silenciosamente (calendário errado é pior que sem calendário)."""
        response = requests.get(FEED_URL, timeout=self.timeout)
        response.raise_for_status()
        raw = response.json()
        events = []
        for item in raw:
            events.append(
                EconomicEvent(
                    title=item.get("title", ""),
                    country=item.get("country", ""),
                    date=item.get("date", ""),
                    impact=item.get("impact", ""),
                    forecast=item.get("forecast") or None,
                    previous=item.get("previous") or None,
                    actual=item.get("actual") or None,
                )
            )
        return events

    def get_relevant_high_impact_events(self) -> list[EconomicEvent]:
        """Só eventos de alto impacto pras moedas relevantes (`RELEVANT_CURRENCIES`) — o
        filtro que `main.py` usa de verdade, evita processar ruído de país/indicador que
        nenhum par hoje coberto reage."""
        return [
            e for e in self.get_week_events()
            if e.impact == "High" and e.country in RELEVANT_CURRENCIES
        ]
