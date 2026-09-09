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
# Spot não permite short sem margem; futuros permite os dois lados. O default preserva
# o comportamento histórico do bot, que já gera sinais long e short.
TRADING_MODE = _get_env("TRADING_MODE", default="futures").strip().lower()
if TRADING_MODE not in {"spot", "futures"}:
    raise RuntimeError("TRADING_MODE deve ser 'spot' ou 'futures'")
ALLOWED_DIRECTIONS = frozenset({"long"}) if TRADING_MODE == "spot" else frozenset({"long", "short"})
# Exposição é limitada no alerta, não só no backtest: pares cripto se movem juntos
# com frequência, então vários sinais na mesma direção não são diversificação real.
MAX_OPEN_POSITIONS = int(_get_env("MAX_OPEN_POSITIONS", default="3"))
MAX_OPEN_PER_DIRECTION = int(_get_env("MAX_OPEN_PER_DIRECTION", default="2"))
if MAX_OPEN_POSITIONS < 1 or MAX_OPEN_PER_DIRECTION < 1:
    raise RuntimeError("Limites de posições abertas devem ser pelo menos 1")
# Timeframe maior usado só pra confirmar a direção do sinal de TIMEFRAME (ver
# analysis/signals.py::confirms_higher_timeframe_trend) — cruzamento de EMA sozinho no 15m tem
# expectância negativa (backtest de 60 e 180 dias confirmou nas duas janelas); exigir que o 1h
# concorde reverteu isso pra expectância positiva. Ver CLAUDE.md, "Backtest walk-forward".
HIGHER_TIMEFRAME = _get_env("HIGHER_TIMEFRAME", default="1h")
# Sinal aberto que não bate alvo nem stop dentro desse prazo é marcado "expirado" — evita
# ficar rastreando um sinal indefinidamente.
SIGNAL_EXPIRY_HOURS = float(_get_env("SIGNAL_EXPIRY_HOURS", default="24"))

# --- Hipóteses do backtest ---
# Valores por lado, em fração decimal. São estimativas conservadoras iniciais para
# comparação; ajuste-os para o nível de taxa e a liquidez reais da sua conta/par.
BACKTEST_TAKER_FEE_RATE = float(_get_env("BACKTEST_TAKER_FEE_RATE", default="0.0004"))
BACKTEST_SLIPPAGE_RATE = float(_get_env("BACKTEST_SLIPPAGE_RATE", default="0.0002"))
# Funding pode ser pago ou recebido em futuros. O padrão zero evita assumir uma
# direção; use um custo conservador se quiser stressar posições mais longas.
BACKTEST_FUNDING_RATE_PER_8H = float(
    _get_env("BACKTEST_FUNDING_RATE_PER_8H", default="0.0")
)
# Universo fixo, líquido e editável para testes históricos. Diferente de escolher os
# maiores volumes de HOJE e projetá-los para trás, este conjunto não muda por causa
# de informação futura. Ainda não reconstrói a composição diária da Binance, mas é
# um benchmark bem menos enviesado.
BACKTEST_SYMBOLS = tuple(
    s.strip().upper()
    for s in _get_env(
        "BACKTEST_SYMBOLS",
        default="BTCUSDT,ETHUSDT,BNBUSDT,XRPUSDT,SOLUSDT,ADAUSDT,DOGEUSDT,LINKUSDT",
    ).split(",")
    if s.strip()
)

# --- Armazenamento ---
STORAGE_PATH = _get_env("STORAGE_PATH", default="storage/signals.json")
