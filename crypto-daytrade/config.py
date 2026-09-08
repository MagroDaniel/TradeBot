"""Configurações centrais do bot de análise de novas listagens na Binance.

Todas as credenciais vêm de variáveis de ambiente (nunca hardcoded). Use um arquivo .env
local (baseado em .env.example) + python-dotenv, ou configure as variáveis diretamente no
ambiente de execução (ex: GitHub Actions secrets).
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
# Bot/grupo do Telegram separados do bot de apostas esportivas (assuntos diferentes).
TELEGRAM_BOT_TOKEN = _get_env("TELEGRAM_BOT_TOKEN", required=True)
TELEGRAM_CHAT_ID = _get_env("TELEGRAM_CHAT_ID", required=True)

# --- Fonte de dados ---
# catalogId=48 é o usado hoje pelo site da Binance pra "New Cryptocurrency Listing" — não é
# uma API oficialmente documentada (é a mesma que o site usa internamente), pode mudar sem
# aviso. Se o bot parar de achar anúncios novos, esse é o primeiro lugar a checar.
BINANCE_ANNOUNCEMENTS_CATALOG_ID = _get_env("BINANCE_ANNOUNCEMENTS_CATALOG_ID", default="48")
BINANCE_ANNOUNCEMENTS_PAGE_SIZE = int(_get_env("BINANCE_ANNOUNCEMENTS_PAGE_SIZE", default="20"))

# --- Armazenamento ---
STORAGE_PATH = _get_env("STORAGE_PATH", default="storage/seen_listings.json")
