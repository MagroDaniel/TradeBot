"""Configurações centrais do bot de sinais técnicos (Binance).

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

# --- Escaneamento ---
TOP_SYMBOLS_COUNT = int(_get_env("TOP_SYMBOLS_COUNT", default="25"))  # top N por volume 24h
TIMEFRAME = _get_env("TIMEFRAME", default="15m")  # intervalo dos candles (day trade)
# Sinal aberto que não bate alvo nem stop dentro desse prazo é marcado "expirado" — evita
# ficar rastreando um sinal indefinidamente.
SIGNAL_EXPIRY_HOURS = float(_get_env("SIGNAL_EXPIRY_HOURS", default="24"))

# --- Armazenamento ---
STORAGE_PATH = _get_env("STORAGE_PATH", default="storage/signals.json")
