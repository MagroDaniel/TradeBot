"""Cliente para a The Odds API (https://the-odds-api.com/).

Custo de créditos: cada chamada de odds em lote (`get_upcoming_odds`) consome
`regions x markets` créditos, INDEPENDENTE do número de jogos retornados (uma chamada já traz
todos os jogos futuros de uma liga). Mercados adicionais por evento (`get_event_odds` — ex:
ambas marcam, dupla chance) custam créditos por partida, não por liga: mesma fórmula
`regions x markets`, só que uma chamada por evento em vez de uma por liga.

Suporta múltiplas chaves de API (`api_keys`) com rotação automática: se uma chave ficar sem
crédito (ou o limite for atingido), tenta a próxima automaticamente antes de desistir — útil
pra somar o free tier de mais de uma conta quando o volume de competições/jogos crescer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"

# Status HTTP que indicam "essa chave não dá mais conta" (crédito esgotado, limite de taxa,
# ou pagamento pendente) — vale tentar a próxima chave em vez de falhar a chamada inteira.
_KEY_EXHAUSTED_STATUS = {401, 402, 429}


@dataclass
class OddsAPIClient:
    api_keys: list[str]
    regions: str = "eu"
    markets: str = "h2h,totals"
    odds_format: str = "decimal"
    timeout: int = 15
    _key_index: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.api_keys:
            raise ValueError("Pelo menos uma ODDS_API_KEY é necessária")

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        params = dict(params or {})
        last_response: requests.Response | None = None

        while self._key_index < len(self.api_keys):
            params["apiKey"] = self.api_keys[self._key_index]
            response = requests.get(f"{BASE_URL}{path}", params=params, timeout=self.timeout)
            last_response = response

            if response.status_code in _KEY_EXHAUSTED_STATUS and self._key_index < len(self.api_keys) - 1:
                logger.warning(
                    "Chave da Odds API #%d sem crédito/limite atingido (HTTP %d) — trocando pra próxima",
                    self._key_index + 1,
                    response.status_code,
                )
                self._key_index += 1
                continue

            break

        assert last_response is not None  # sempre entra no loop pelo menos uma vez
        last_response.raise_for_status()

        used = last_response.headers.get("x-requests-used")
        remaining = last_response.headers.get("x-requests-remaining")
        if remaining is not None:
            logger.info(
                "The Odds API (chave #%d) — créditos usados: %s | restantes: %s",
                self._key_index + 1, used, remaining,
            )

        return last_response.json()

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

    def get_event_odds(self, sport_key: str, event_id: str, markets: str) -> dict:
        """Odds de mercados adicionais (ex: btts, double_chance) pra um evento específico —
        cobrado por evento, não por liga (ver custo de créditos no docstring do módulo)."""
        return self._request(
            f"/sports/{sport_key}/events/{event_id}/odds",
            params={
                "regions": self.regions,
                "markets": markets,
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
