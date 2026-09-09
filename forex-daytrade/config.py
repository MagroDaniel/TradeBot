"""Configurações centrais do bot de sinais técnicos (forex, Twelve Data).

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
TWELVEDATA_API_KEY = _get_env("TWELVEDATA_API_KEY", required=True)
# Mesmo bot/grupo do crypto-daytrade (decisão do usuário, 2026-09-09) — não são credenciais
# novas, é o TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID que já existe pro bot de cripto.
TELEGRAM_BOT_TOKEN = _get_env("TELEGRAM_BOT_TOKEN", required=True)
TELEGRAM_CHAT_ID = _get_env("TELEGRAM_CHAT_ID", required=True)

# --- Escaneamento ---
# Só EUR/USD pra começar (decisão do usuário, 2026-09-09) — free tier da Twelve Data tem cota
# de 800 chamadas/dia; cada par escaneado custa 2 chamadas por execução (timeframe do sinal +
# timeframe maior), então dá pra expandir a lista depois com folga (ver docs/).
FOREX_SYMBOLS = tuple(
    s.strip().upper() for s in _get_env("FOREX_SYMBOLS", default="EUR/USD").split(",") if s.strip()
)
TIMEFRAME = _get_env("TIMEFRAME", default="15min")  # intervalo dos candles (day trade)
HIGHER_TIMEFRAME = _get_env("HIGHER_TIMEFRAME", default="1h")
# Ainda não validados via backtest pra forex (ver analysis/signals.py) — None/False = filtro
# desligado, comportamento baseline. Não mude sem antes rodar backtest/run.py contra histórico
# real de forex, mesma regra do bot de cripto.
USE_HIGHER_TIMEFRAME_FILTER = _get_env("USE_HIGHER_TIMEFRAME_FILTER", default="false").strip().lower() == "true"
MIN_RANGE_EXPANSION = _get_env("MIN_RANGE_EXPANSION", default="")
MIN_RANGE_EXPANSION = float(MIN_RANGE_EXPANSION) if MIN_RANGE_EXPANSION else None

# Só um par por padrão, mas os limites continuam existindo pra quando a lista crescer.
MAX_OPEN_POSITIONS = int(_get_env("MAX_OPEN_POSITIONS", default="1"))
MAX_OPEN_PER_DIRECTION = int(_get_env("MAX_OPEN_PER_DIRECTION", default="1"))
if MAX_OPEN_POSITIONS < 1 or MAX_OPEN_PER_DIRECTION < 1:
    raise RuntimeError("Limites de posições abertas devem ser pelo menos 1")

# Sinal aberto que não bate alvo nem stop dentro desse prazo é marcado "expirado".
SIGNAL_EXPIRY_HOURS = float(_get_env("SIGNAL_EXPIRY_HOURS", default="24"))

# --- Hipóteses do backtest ---
# Forex não cobra taxa por lado como exchange de cripto — o custo real é majoritariamente o
# spread, que a Twelve Data não devolve. BACKTEST_SLIPPAGE_RATE funciona como proxy do spread
# (ver backtest/engine.py::ExecutionCosts); 0.00015 ≈ 1.5 pip em EUR/USD por volta (entrada +
# saída), estimativa conservadora pra major — ajuste pra corretora/par reais antes de confiar.
BACKTEST_TAKER_FEE_RATE = float(_get_env("BACKTEST_TAKER_FEE_RATE", default="0.0"))
BACKTEST_SLIPPAGE_RATE = float(_get_env("BACKTEST_SLIPPAGE_RATE", default="0.00015"))
BACKTEST_FUNDING_RATE_PER_8H = float(_get_env("BACKTEST_FUNDING_RATE_PER_8H", default="0.0"))
# Universo fixo pro backtest — hoje é só FOREX_SYMBOLS (EUR/USD), mas fica configurável em
# separado pra quando a lista ao vivo crescer sem precisar re-testar todo mundo de novo.
BACKTEST_SYMBOLS = tuple(
    s.strip().upper()
    for s in _get_env("BACKTEST_SYMBOLS", default="EUR/USD").split(",")
    if s.strip()
)

# --- Armazenamento ---
STORAGE_PATH = _get_env("STORAGE_PATH", default="storage/signals.json")
