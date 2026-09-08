"""Modelo de probabilidade para partidas de futebol baseado em distribuição de Poisson.

Abordagem clássica (Maher, 1982 — base do modelo Dixon-Coles):
- Cada time tem uma força de ataque e uma força de defesa, relativas à média da liga.
- Gols esperados do mandante = média_gols_mandante_liga * ataque(mandante) * defesa(visitante)
- Gols esperados do visitante = média_gols_visitante_liga * ataque(visitante) * defesa(mandante)
- A partir dos gols esperados (lambda), calcula-se P(placar) via Poisson e agrega-se
  para 1X2, over/under, etc.

É um modelo simples e transparente — bom ponto de partida. Fica fácil evoluir depois
para Dixon-Coles completo (correção para placares baixos) ou um modelo de ML.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class MatchResult:
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int


@dataclass(frozen=True)
class TeamStrength:
    attack: float
    defense: float


def _poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


class PoissonModel:
    """Calibra forças de ataque/defesa a partir de resultados históricos e prevê partidas."""

    def __init__(self, max_goals: int = 8) -> None:
        self.max_goals = max_goals
        self.team_strength: dict[str, TeamStrength] = {}
        self.league_avg_home_goals: float = 1.5
        self.league_avg_away_goals: float = 1.2

    def fit(self, matches: list[MatchResult]) -> "PoissonModel":
        if not matches:
            raise ValueError("Não é possível calibrar o modelo sem partidas históricas")

        teams = {m.home_team for m in matches} | {m.away_team for m in matches}

        n = len(matches)
        self.league_avg_home_goals = sum(m.home_goals for m in matches) / n
        self.league_avg_away_goals = sum(m.away_goals for m in matches) / n

        raw: dict[str, dict[str, float]] = {
            t: {
                "scored_home": 0.0, "conceded_home": 0.0, "games_home": 0,
                "scored_away": 0.0, "conceded_away": 0.0, "games_away": 0,
            }
            for t in teams
        }
        for m in matches:
            h, a = raw[m.home_team], raw[m.away_team]
            h["scored_home"] += m.home_goals
            h["conceded_home"] += m.away_goals
            h["games_home"] += 1
            a["scored_away"] += m.away_goals
            a["conceded_away"] += m.home_goals
            a["games_away"] += 1

        strengths: dict[str, TeamStrength] = {}
        for team, s in raw.items():
            games_h = max(s["games_home"], 1)
            games_a = max(s["games_away"], 1)

            attack_home = (s["scored_home"] / games_h) / self.league_avg_home_goals
            attack_away = (s["scored_away"] / games_a) / self.league_avg_away_goals
            defense_home = (s["conceded_home"] / games_h) / self.league_avg_away_goals
            defense_away = (s["conceded_away"] / games_a) / self.league_avg_home_goals

            strengths[team] = TeamStrength(
                attack=(attack_home + attack_away) / 2,
                defense=(defense_home + defense_away) / 2,
            )

        self.team_strength = strengths
        return self

    def expected_goals(self, home_team: str, away_team: str) -> tuple[float, float]:
        home = self.team_strength.get(home_team)
        away = self.team_strength.get(away_team)
        if home is None or away is None:
            missing = home_team if home is None else away_team
            raise KeyError(f"Time sem histórico calibrado: {missing}")

        home_xg = self.league_avg_home_goals * home.attack * away.defense
        away_xg = self.league_avg_away_goals * away.attack * home.defense
        return home_xg, away_xg

    def match_probabilities(self, home_team: str, away_team: str) -> dict[str, float]:
        """Probabilidades de resultado 1X2 e over/under 2.5 gols."""
        home_xg, away_xg = self.expected_goals(home_team, away_team)

        home_win = draw = away_win = 0.0
        over_2_5 = 0.0

        for hg in range(self.max_goals + 1):
            for ag in range(self.max_goals + 1):
                p = _poisson_pmf(hg, home_xg) * _poisson_pmf(ag, away_xg)
                if hg > ag:
                    home_win += p
                elif hg == ag:
                    draw += p
                else:
                    away_win += p
                if hg + ag > 2:
                    over_2_5 += p

        return {
            "home_win": home_win,
            "draw": draw,
            "away_win": away_win,
            "over_2_5": over_2_5,
            "under_2_5": 1 - over_2_5,
        }
