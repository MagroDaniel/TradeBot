"""Cliente para a The Odds API (https://the-odds-api.com/).

Custo de créditos: cada chamada consome `regions x markets` créditos,
INDEPENDENTE do número de jogos retornados (uma chamada já traz todos
os jogos futuros de uma liga). Por isso o bot faz poucas chamadas por dia
— dá pra rodar 1x/dia dentro do free tier (500 créditos/mês) com folga.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"


@dataclass
class OddsAPIClient:
    api_key: str
    regions: str = "eu"
    markets: str = "h2h,totals"
    odds_format: str = "decimal"
    timeout: int = 15

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        params = dict(params or {})
        params["apiKey"] = self.api_key
        response = requests.get(f"{BASE_URL}{path}", params=params, timeout=self.timeout)
        response.raise_for_status()

        used = response.headers.get("x-requests-used")
        remaining = response.headers.get("x-requests-remaining")
        if remaining is not None:
            logger.info("The Odds API — créditos usados: %s | restantes: %s", used, remaining)

        return response.json()

    def get_upcoming_odds(self, sport_key: str) -> list[dict]:
        """Odds de todos os jogos futuros de uma liga (1 chamada = todos os jogos)."""
        return self._request(
            f"/sports/{sport_key}/odds",
            params={
                "regions": self.regions,
                "markets": self.markets,
                "oddsFormat": self.odds_format,
                "dateFormat": "iso",
            },
        )

    def get_scores(self, sport_key: str, days_from: int = 3) -> list[dict]:
        """Placares de jogos recentes/finalizados, usado para conferir resultados dos picks."""
        return self._request(
            f"/sports/{sport_key}/scores",
            params={"daysFrom": days_from, "dateFormat": "iso"},
        )
