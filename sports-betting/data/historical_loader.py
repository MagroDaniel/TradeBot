"""Carrega resultados históricos para calibrar as forças de ataque/defesa dos times.

Reconhece automaticamente duas fontes gratuitas (nenhuma exige API key), detectando
o formato pelas colunas do cabeçalho do CSV:

- https://www.football-data.co.uk/data.php — ligas europeias (Inglaterra, Espanha,
  Alemanha, Itália, França etc.). Colunas: HomeTeam, AwayTeam, FTHG (gols do
  mandante), FTAG (gols do visitante). Não cobre o Brasileirão.
- https://github.com/adaoduque/Brasileirao_Dataset — Campeonato Brasileiro
  (2003-2024), fonte recomendada para o SPORT_KEYS padrão (soccer_brazil_campeonato).
  Colunas: mandante, visitante, mandante_Placar, visitante_Placar.

Se o CSV tiver uma coluna de data (Date ou data), ela é usada para habilitar a
ponderação temporal do PoissonModel (jogos recentes pesam mais). Sem essa coluna,
ou com data ilegível numa linha específica, o jogo entra sem ponderação — não é
descartado.

Baixe o(s) CSV(s) da liga desejada, junte as temporadas que quiser considerar
e aponte HISTORICAL_DATA_PATH (em config.py / .env) para o arquivo resultante.
"""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from model.poisson_model import MatchResult

# Cada dict mapeia os nomes de campo do MatchResult para o nome da coluna no CSV.
# A primeira lista cujas colunas (obrigatórias) estão todas presentes no cabeçalho é usada.
_COLUMN_ALIASES: list[dict[str, str]] = [
    # football-data.co.uk (ligas europeias)
    {"home_team": "HomeTeam", "away_team": "AwayTeam", "home_goals": "FTHG", "away_goals": "FTAG"},
    # adaoduque/Brasileirao_Dataset (Campeonato Brasileiro)
    {
        "home_team": "mandante",
        "away_team": "visitante",
        "home_goals": "mandante_Placar",
        "away_goals": "visitante_Placar",
    },
]

# Coluna de data é opcional (habilita a ponderação temporal do PoissonModel) — procurada
# à parte das colunas obrigatórias acima, já que seu nome não amarra a um formato específico.
_DATE_COLUMN_ALIASES = ("Date", "data")
_DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y")


def _detect_columns(fieldnames: list[str] | None) -> dict[str, str]:
    fields = set(fieldnames or [])
    for mapping in _COLUMN_ALIASES:
        if set(mapping.values()) <= fields:
            return mapping
    raise ValueError(
        f"Formato de CSV não reconhecido (colunas encontradas: {sorted(fields)}). "
        "Formatos suportados: football-data.co.uk (HomeTeam/AwayTeam/FTHG/FTAG) ou "
        "adaoduque/Brasileirao_Dataset (mandante/visitante/mandante_Placar/visitante_Placar)."
    )


def _detect_date_column(fieldnames: list[str] | None) -> str | None:
    fields = set(fieldnames or [])
    for candidate in _DATE_COLUMN_ALIASES:
        if candidate in fields:
            return candidate
    return None


def _parse_date(value: str) -> date | None:
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None  # data ausente/ilegível: o jogo entra sem ponderação temporal


def load_matches_from_csv(path: str | Path) -> list[MatchResult]:
    matches: list[MatchResult] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = _detect_columns(reader.fieldnames)
        date_column = _detect_date_column(reader.fieldnames)
        for row in reader:
            try:
                matches.append(
                    MatchResult(
                        home_team=row[columns["home_team"]].strip(),
                        away_team=row[columns["away_team"]].strip(),
                        home_goals=int(row[columns["home_goals"]]),
                        away_goals=int(row[columns["away_goals"]]),
                        match_date=_parse_date(row[date_column]) if date_column else None,
                    )
                )
            except (KeyError, ValueError):
                continue  # ignora linhas mal formatadas ou incompletas
    return matches
