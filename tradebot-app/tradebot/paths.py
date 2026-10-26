"""Onde o app guarda dados: banco SQLite, kill switch (HALT), cache de candles e logs.

Windows: %APPDATA%\\TradeBot. Outros: ~/.tradebot. `TRADEBOT_DATA_DIR` sobrescreve (testes,
ou rodar duas instâncias separadas). Fica FORA da pasta do programa de propósito: atualizar
ou apagar o .exe não apaga histórico nem carteira demo.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    override = os.getenv("TRADEBOT_DATA_DIR")
    if override:
        path = Path(override)
    elif sys.platform == "win32" and os.getenv("APPDATA"):
        path = Path(os.environ["APPDATA"]) / "TradeBot"
    else:
        path = Path.home() / ".tradebot"
    path.mkdir(parents=True, exist_ok=True)
    return path
