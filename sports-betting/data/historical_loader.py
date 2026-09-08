"""Carrega resultados históricos para calibrar as forças de ataque/defesa dos times.

Fonte recomendada (gratuita, sem necessidade de API key):
https://www.football-data.co.uk/data.php — arquivos CSV por liga/temporada,
com colunas HomeTeam, AwayTeam, FTHG (gols do mandante), FTAG (gols do visitante).

Baixe o(s) CSV(s) da liga desejada, junte as temporadas que quiser considerar
e aponte HISTORICAL_DATA_PATH (em config.py / .env) para o arquivo resultante.
"""
from __future__ import annotations

import csv
from pathlib import Path

from model.poisson_model import MatchResult


def load_matches_from_csv(path: str | Path) -> list[MatchResult]:
    matches: list[MatchResult] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                matches.append(
                    MatchResult(
                        home_team=row["HomeTeam"].strip(),
                        away_team=row["AwayTeam"].strip(),
                        home_goals=int(row["FTHG"]),
                        away_goals=int(row["FTAG"]),
                    )
                )
            except (KeyError, ValueError):
                continue  # ignora linhas mal formatadas ou incompletas
    return matches
