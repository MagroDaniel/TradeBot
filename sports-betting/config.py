"""Configurações centrais do bot de apostas esportivas.

Todas as credenciais vêm de variáveis de ambiente (nunca hardcoded).
Use um arquivo .env local (baseado em .env.example) + python-dotenv,
ou configure as variáveis diretamente no ambiente de execução
(ex: GitHub Actions secrets).
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _get_env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Variável de ambiente obrigatória não definida: {name}")
    return value  # type: ignore[return-value]


# --- Credenciais ---
ODDS_API_KEY = _get_env("ODDS_API_KEY", required=True)
# Chaves extras da The Odds API, separadas por vírgula — usadas em sequência quando a
# anterior fica sem crédito/limite (soma o free tier de várias contas). Opcional.
_extra_keys_raw = _get_env("ODDS_API_KEYS_EXTRA", default="")
ODDS_API_KEYS: list[str] = [ODDS_API_KEY] + [
    k.strip() for k in _extra_keys_raw.split(",") if k.strip()
]
TELEGRAM_BOT_TOKEN = _get_env("TELEGRAM_BOT_TOKEN", required=True)
TELEGRAM_CHAT_ID = _get_env("TELEGRAM_CHAT_ID", required=True)

# --- Esporte / mercado ---
# Chaves de liga da The Odds API, separadas por vírgula (uma chamada = 1 crédito x região x
# mercado, por liga). Lista completa: https://the-odds-api.com/sports-odds-data/soccer-odds.html
# Cada sport_key precisa de um CSV histórico próprio em HISTORICAL_DATA_DIR (ver abaixo) —
# times de ligas diferentes não podem compartilhar um modelo calibrado junto.
SPORT_KEYS = _get_env(
    "SPORT_KEYS",
    default=(
        "soccer_brazil_campeonato,soccer_epl,soccer_spain_la_liga,"
        "soccer_germany_bundesliga,soccer_italy_serie_a,soccer_france_ligue_one,"
        "soccer_uefa_champs_league,soccer_uefa_europa_league,"
        "soccer_uefa_europa_conference_league"
    ),
)
REGIONS = _get_env("REGIONS", default="eu")  # eu, uk, us, au
MARKETS = _get_env("MARKETS", default="h2h,totals")
# Mercados adicionais (ambas marcam, dupla chance) — cobrados por evento, só buscados pros
# jogos de hoje já filtrados (não pra todos os jogos futuros da liga). Vazio/"none" desativa.
_additional_markets_raw = _get_env("ADDITIONAL_MARKETS", default="btts,double_chance")
ADDITIONAL_MARKETS = (
    "" if _additional_markets_raw.strip().lower() in ("", "none") else _additional_markets_raw.strip()
)
ODDS_FORMAT = "decimal"

# --- Estratégia ---
EV_THRESHOLD = float(_get_env("EV_THRESHOLD", default="0.05"))  # EV mínimo (5%) para virar pick
KELLY_FRACTION = float(_get_env("KELLY_FRACTION", default="0.25"))  # Kelly fracionário (25%)
MAX_STAKE_FRACTION = float(_get_env("MAX_STAKE_FRACTION", default="0.03"))  # trava: 3% da banca por aposta

# --- Dados históricos (para calibrar o modelo de Poisson) ---
# Um CSV por competição, em HISTORICAL_DATA_DIR/{sport_key}.csv (ex:
# data/historical/soccer_epl.csv) — formato football-data.co.uk ou adaoduque/Brasileirao_Dataset,
# historical_loader.py detecta automaticamente. Competição em SPORT_KEYS sem CSV correspondente
# é pulada (log de aviso), não derruba a execução das demais.
HISTORICAL_DATA_DIR = _get_env("HISTORICAL_DATA_DIR", default="data/historical")
# Meia-vida (em dias) da ponderação temporal do modelo: jogos com essa idade pesam metade
# de um jogo de hoje na calibração. Evita que times historicamente fortes mas em fase
# ruim atualmente (ou vice-versa) distorçam a força estimada. Deixe em branco/"none"
# para desativar (média simples sobre todo o histórico, comportamento anterior).
_half_life_raw = _get_env("MODEL_HALF_LIFE_DAYS", default="1095")
MODEL_HALF_LIFE_DAYS: float | None = (
    None if _half_life_raw.strip().lower() in ("", "none") else float(_half_life_raw)
)

# --- Armazenamento ---
STORAGE_PATH = _get_env("STORAGE_PATH", default="storage/picks.json")
