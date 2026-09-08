"""Mapeamento de nomes de times entre a The Odds API e os CSVs históricos de cada competição.

A Odds API usa nomes oficiais completos; as fontes históricas (adaoduque/Brasileirao_Dataset
e o dataset consolidado xgabora/Club-Football-Match-Data, que segue a convenção abreviada do
football-data.co.uk) usam nomes mais curtos/abreviados pro mesmo time (ex: "Manchester United"
vs. "Man United", "Borussia Monchengladbach" vs. "M'gladbach"). Sem esse mapeamento,
PoissonModel.match_probabilities() levanta KeyError e o time é pulado silenciosamente em
main.py — o que é o comportamento certo pra times sem dado nenhum, mas errado pra times que só
têm nome diferente.

Um único dict global funciona porque os nomes não colidem entre competições (nenhum time de
uma liga tem o mesmo nome de um time de outra) — não precisa ser namespaced por sport_key.

Ajuste este dict sempre que a Odds API retornar um nome que não bate com o CSV da respectiva
competição (rode o script de diagnóstico comparando os dois conjuntos de nomes pra achar novos
casos, ex: quando uma competição nova for adicionada em SPORT_KEYS). Times sem entrada aqui são
buscados pelo nome original — inclui times genuinamente sem histórico no CSV (ex: recém-
promovidos, ou clubes pequenos fora da amostra), que continuam sendo pulados como hoje.
"""
from __future__ import annotations

TEAM_ALIASES: dict[str, str] = {
    # --- Brasileirão Série A (soccer_brazil_campeonato) ---
    "Atletico Mineiro": "Atletico-MG",
    "Atletico Paranaense": "Athletico-PR",
    "Botafogo": "Botafogo-RJ",
    "Bragantino-SP": "Bragantino",
    "Grêmio": "Gremio",
    "Vasco da Gama": "Vasco",
    # --- Premier League (soccer_epl) ---
    "Brighton and Hove Albion": "Brighton",
    "Coventry City": "Coventry",
    "Hull City": "Hull",
    "Ipswich Town": "Ipswich",
    "Leeds United": "Leeds",
    "Manchester City": "Man City",
    "Manchester United": "Man United",
    "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nott'm Forest",
    "Tottenham Hotspur": "Tottenham",
    # --- La Liga (soccer_spain_la_liga) ---
    "Alavés": "Alaves",
    "Athletic Bilbao": "Ath Bilbao",
    "Atlético Madrid": "Ath Madrid",
    "CA Osasuna": "Osasuna",
    "Celta Vigo": "Celta",
    "Deportivo La Coruña": "La Coruna",
    "Elche CF": "Elche",
    "Espanyol": "Espanol",
    "Málaga": "Malaga",
    "Rayo Vallecano": "Vallecano",
    "Real Betis": "Betis",
    "Real Racing Club de Santander": "Santander",
    "Real Sociedad": "Sociedad",
    # --- Bundesliga (soccer_germany_bundesliga) ---
    "1. FC Köln": "FC Koln",
    "Bayer Leverkusen": "Leverkusen",
    "Borussia Dortmund": "Dortmund",
    "Borussia Monchengladbach": "M'gladbach",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "FC Schalke 04": "Schalke 04",
    "FSV Mainz 05": "Mainz",
    "Hamburger SV": "Hamburg",
    "SC Freiburg": "Freiburg",
    "SC Paderborn": "Paderborn",
    "TSG Hoffenheim": "Hoffenheim",
    "VfB Stuttgart": "Stuttgart",
    # --- Serie A italiana (soccer_italy_serie_a) ---
    "AC Milan": "Milan",
    "AS Roma": "Roma",
    "Atalanta BC": "Atalanta",
    "Inter Milan": "Inter",
    # --- Ligue 1 (soccer_france_ligue_one) ---
    "AS Monaco": "Monaco",
    "Le Mans FC": "Le Mans",
    "Paris Saint Germain": "Paris SG",
    "RC Lens": "Lens",
}


def normalize_team_name(name: str) -> str:
    """Traduz um nome de time da Odds API pro nome equivalente no CSV histórico da
    competição, quando houver um alias cadastrado. Times sem alias voltam inalterados."""
    return TEAM_ALIASES.get(name, name)
