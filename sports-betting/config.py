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
TELEGRAM_BOT_TOKEN = _get_env("TELEGRAM_BOT_TOKEN", required=True)
TELEGRAM_CHAT_ID = _get_env("TELEGRAM_CHAT_ID", required=True)

# --- Esporte / mercado ---
# Chaves de liga da The Odds API (uma chamada = 1 crédito x região x mercado, por liga).
# Lista completa: https://the-odds-api.com/sports-odds-data/soccer-odds.html
SPORT_KEYS = _get_env("SPORT_KEYS", default="soccer_brazil_campeonato")
REGIONS = _get_env("REGIONS", default="eu")  # eu, uk, us, au
MARKETS = _get_env("MARKETS", default="h2h,totals")
ODDS_FORMAT = "decimal"

# --- Estratégia ---
EV_THRESHOLD = float(_get_env("EV_THRESHOLD", default="0.05"))  # EV mínimo (5%) para virar pick
KELLY_FRACTION = float(_get_env("KELLY_FRACTION", default="0.25"))  # Kelly fracionário (25%)
MAX_STAKE_FRACTION = float(_get_env("MAX_STAKE_FRACTION", default="0.03"))  # trava: 3% da banca por aposta

# --- Dados históricos (para calibrar o modelo de Poisson) ---
# CSV no formato football-data.co.uk (ligas europeias) ou adaoduque/Brasileirao_Dataset
# (Brasileirão) — historical_loader.py detecta o formato automaticamente.
HISTORICAL_DATA_PATH = _get_env(
    "HISTORICAL_DATA_PATH", default="data/historical/brasileirao.csv"
)
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
