"""Estratégia baseada em surpresa de calendário econômico (NFP, CPI, PIB, taxa de juros...) —
quarta abordagem testada no projeto, depois que tendência (EMA), reversão à média (Bollinger+
RSI) e rompimento do range asiático não mostraram expectância positiva consistente contra
preço puro (ver README.md).

**AVISO — exceção deliberada à regra de validação do projeto**: as outras 3 estratégias só
foram pra produção depois de backtest contra histórico real (ver `crypto-daytrade/CLAUDE.md` e
este README). Essa aqui NÃO passou por esse processo — a fonte de dado gratuita disponível
(`data/forexfactory_client.py`, feed da Forex Factory) só cobre a semana atual/próxima, sem
valor histórico realizado; validar de verdade exigiria uma API paga (~US$25/mês), e o usuário
decidiu explicitamente (2026-09-09) seguir só com dado grátis, sabendo da troca. Ou seja: essa
lógica é baseada em pesquisa/literatura (ver docstring de cada constante abaixo), não em
backtest próprio. Antes de qualquer alerta real pro usuário, a intenção é rodar em modo
"observação" por algumas semanas, comparando o que a lógica teria dito com o que aconteceu de
verdade — só então decidir se vira alerta de produção.

**Lógica**: o mercado reage à SURPRESA (diferença entre valor realizado e previsto pelo
mercado), não ao nível absoluto do indicador — bem documentado na literatura de trading de
notícia. Pra um pequeno conjunto de indicadores onde a direção "surpresa positiva -> moeda
fortalece" é bem estabelecida (NFP, CPI, PIB, vendas no varejo, PMI, decisão de juros — todos
"quanto maior/mais forte que o esperado, mais a moeda tende a fortalecer"; taxa de desemprego e
pedidos de seguro-desemprego são o oposto, "quanto menor que o esperado, mais a moeda tende a
fortalecer"), calcula a direção implícita e gera um sinal SÓ depois que o primeiro candle de 15
minutos após a divulgação fecha (regra documentada na pesquisa — filtra o solavanco inicial de
volatilidade, que costuma ser ruído, não a reação institucional real).

NUNCA sugere alavancagem — mesma regra do resto do projeto.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from analysis.indicators import atr
from data.forexfactory_client import EconomicEvent
from data.twelvedata_client import Candle

WAIT_MINUTES_AFTER_RELEASE = 15
ATR_PERIOD = 14
ATR_STOP_MULTIPLIER = 1.5
RISK_REWARD_RATIO = 2.0

STRATEGY_VERSION = "news-surprise-v1-EXPERIMENTAL-not-backtested"

# Indicadores onde "resultado real ACIMA do previsto" costuma fortalecer a moeda — convenção
# bem documentada (crescimento/inflação surpreendendo pra cima -> expectativa de juro mais
# alto/economia mais forte -> moeda fortalece). Casamento por substring, case-insensitive, no
# título do evento (o feed não dá um código de indicador estruturado, só o título em texto).
_HIGHER_IS_STRONGER = (
    "non-farm payrolls", "nonfarm payrolls", "nfp", "employment change",
    "cpi", "consumer price index", "core cpi",
    "gdp",
    "retail sales",
    "pmi", "ism manufacturing", "ism services",
    "interest rate decision", "rate decision", "official bank rate",
)
# Indicadores onde "resultado real ABAIXO do previsto" costuma fortalecer a moeda (desemprego
# menor que o esperado = economia mais forte).
_LOWER_IS_STRONGER = (
    "unemployment rate",
    "jobless claims", "initial claims", "continuing claims",
)


@dataclass(frozen=True)
class Signal:
    symbol: str
    direction: str  # "long" ou "short"
    entry: float
    stop_loss: float
    target: float
    rsi_value: float  # não usado por esta estratégia — sempre 0.0, mantido só por
    # compatibilidade com SignalRecord/relatório (mesmo padrão de breakout_signals.py)
    reason: str


def reprice_signal_for_entry(signal: Signal, entry: float) -> Signal:
    """Mesma lógica das outras 3 estratégias — preserva a distância de risco (ATR) e a
    distância até o alvo em torno do preço executável real."""
    if entry <= 0:
        raise ValueError("Preço de entrada deve ser positivo")
    risk = abs(signal.entry - signal.stop_loss)
    target_distance = abs(signal.target - signal.entry)
    if signal.direction == "long":
        return Signal(
            signal.symbol, signal.direction, entry, entry - risk, entry + target_distance,
            signal.rsi_value, signal.reason,
        )
    return Signal(
        signal.symbol, signal.direction, entry, entry + risk, entry - target_distance,
        signal.rsi_value, signal.reason,
    )


def _parse_numeric(raw: str) -> float | None:
    """"180K" -> 180000.0, "3.5%" -> 3.5, "-0.2%" -> -0.2, "1.1M" -> 1100000.0. None se não
    conseguir parsear (formato inesperado do feed — não inventa número)."""
    text = raw.strip().replace(",", "")
    if not text:
        return None
    multiplier = 1.0
    if text.endswith("%"):
        text = text[:-1].strip()
    elif text and text[-1] in "KMB":
        multiplier = {"K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0}[text[-1]]
        text = text[:-1].strip()
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def classify_indicator(title: str) -> bool | None:
    """True se "acima do previsto" fortalece a moeda, False se "abaixo do previsto" fortalece,
    None se o indicador não está no conjunto conhecido (ver `_HIGHER_IS_STRONGER`/
    `_LOWER_IS_STRONGER`) — não adivinha pra indicador desconhecido, melhor não gerar sinal do
    que gerar na direção errada."""
    lowered = title.lower()
    if any(keyword in lowered for keyword in _HIGHER_IS_STRONGER):
        return True
    if any(keyword in lowered for keyword in _LOWER_IS_STRONGER):
        return False
    return None


def currency_strengthens(event: EconomicEvent) -> bool | None:
    """True se a surpresa do evento (`actual` vs `forecast`) indica que `event.country`
    fortalece, False se enfraquece, None se não dá pra calcular (indicador desconhecido, sem
    surpresa disponível ainda, ou valores não numéricos)."""
    if not event.has_surprise():
        return None
    higher_is_stronger = classify_indicator(event.title)
    if higher_is_stronger is None:
        return None

    actual = _parse_numeric(event.actual)
    forecast = _parse_numeric(event.forecast)
    if actual is None or forecast is None or actual == forecast:
        return None

    beat_forecast = actual > forecast
    return beat_forecast if higher_is_stronger else not beat_forecast


def direction_for_pair(event_currency: str, strengthens: bool, symbol: str) -> str | None:
    """"long"/"short" pro `symbol` (ex: "EUR/USD") se `event_currency` for a base ou a
    cotação do par; None se o evento não afeta esse par."""
    parts = symbol.split("/")
    if len(parts) != 2:
        return None
    base, quote = parts
    if event_currency == base:
        return "long" if strengthens else "short"
    if event_currency == quote:
        return "short" if strengthens else "long"
    return None


def generate_signal(
    event: EconomicEvent,
    symbol: str,
    candles: list[Candle],
    now: datetime | None = None,
) -> Signal | None:
    """None se o evento não tem surpresa calculável ainda, se o indicador não é reconhecido,
    se `event.country` não afeta `symbol`, se o candle de 15min pós-divulgação ainda não
    fechou (`WAIT_MINUTES_AFTER_RELEASE`), ou se não há histórico suficiente pra ATR(14).

    `candles` deve ser histórico recente já FECHADO (ver `data/twelvedata_client.py::
    closed_candles`) — o preço de entrada usado é `candles[-1].close`, igual às outras
    estratégias; quem chamar reprice via `reprice_signal_for_entry` com o preço executável
    real antes de abrir posição de verdade (mesmo padrão de `main.py`)."""
    event_dt = event.datetime_utc
    if event_dt is None:
        return None

    strengthens = currency_strengthens(event)
    if strengthens is None:
        return None

    direction = direction_for_pair(event.country, strengthens, symbol)
    if direction is None:
        return None

    now = now or datetime.now(timezone.utc)
    if now < event_dt + timedelta(minutes=WAIT_MINUTES_AFTER_RELEASE):
        return None

    if not candles:
        return None
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]
    atr_values = atr(highs, lows, closes, ATR_PERIOD)
    if not atr_values:
        return None

    entry = closes[-1]
    atr_now = atr_values[-1]
    if atr_now <= 0:
        return None

    if direction == "long":
        stop_loss = entry - ATR_STOP_MULTIPLIER * atr_now
        target = entry + RISK_REWARD_RATIO * (entry - stop_loss)
    else:
        stop_loss = entry + ATR_STOP_MULTIPLIER * atr_now
        target = entry - RISK_REWARD_RATIO * (stop_loss - entry)

    reason = (
        f"{event.title} ({event.country}): real {event.actual} vs. previsto {event.forecast} "
        f"— surpresa {'fortalece' if strengthens else 'enfraquece'} {event.country}"
    )
    return Signal(symbol, direction, entry, stop_loss, target, 0.0, reason)
