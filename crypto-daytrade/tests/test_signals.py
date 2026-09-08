import pytest

from analysis.signals import RISK_REWARD_RATIO, generate_signal
from data.binance_client import Candle


def _candles_from_closes(closes: list[float]) -> list[Candle]:
    return [
        Candle(open_time_ms=i, open=c, high=c + 0.3, low=c - 0.3, close=c, volume=100.0)
        for i, c in enumerate(closes)
    ]


def _decline_then_rise(decline_candles=40, decline_step=0.1, rise_candles=9, rise_step=0.18):
    """Queda leve e prolongada seguida de alta — reproduz um cruzamento de EMA9 acima da
    EMA21 com RSI em ~63 (dentro da faixa que confirma o sinal), validado empiricamente."""
    closes = []
    price = 100.0
    for _ in range(decline_candles):
        price -= decline_step
        closes.append(price)
    for _ in range(rise_candles):
        price += rise_step
        closes.append(price)
    return closes


def _rise_then_decline(rise_candles=40, rise_step=0.1, decline_candles=9, decline_step=0.18):
    """Espelho do fixture acima — reproduz um cruzamento de EMA9 abaixo da EMA21 com RSI
    em ~37."""
    closes = []
    price = 100.0
    for _ in range(rise_candles):
        price += rise_step
        closes.append(price)
    for _ in range(decline_candles):
        price -= decline_step
        closes.append(price)
    return closes


def test_generates_long_signal_on_bullish_ema_cross_with_confirming_rsi():
    candles = _candles_from_closes(_decline_then_rise())

    signal = generate_signal("TESTUSDT", candles)

    assert signal is not None
    assert signal.direction == "long"
    assert signal.symbol == "TESTUSDT"
    assert 30 <= signal.rsi_value <= 65
    # stop abaixo da entrada, alvo acima — long aposta na alta
    assert signal.stop_loss < signal.entry < signal.target


def test_generates_short_signal_on_bearish_ema_cross_with_confirming_rsi():
    candles = _candles_from_closes(_rise_then_decline())

    signal = generate_signal("TESTUSDT", candles)

    assert signal is not None
    assert signal.direction == "short"
    assert 35 <= signal.rsi_value <= 70
    # stop acima da entrada, alvo abaixo — short aposta na queda
    assert signal.target < signal.entry < signal.stop_loss


def test_target_risk_reward_ratio_matches_configured_value():
    candles = _candles_from_closes(_decline_then_rise())
    signal = generate_signal("TESTUSDT", candles)

    risk = signal.entry - signal.stop_loss
    reward = signal.target - signal.entry
    assert reward == pytest.approx(risk * RISK_REWARD_RATIO)


def test_no_signal_on_flat_price_series():
    candles = _candles_from_closes([100.0] * 50)

    assert generate_signal("TESTUSDT", candles) is None


def test_no_signal_with_insufficient_history():
    candles = _candles_from_closes([100.0, 101.0, 99.0])

    assert generate_signal("TESTUSDT", candles) is None
