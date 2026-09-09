import pytest

from analysis.signals import (
    ATR_STOP_MULTIPLIER,
    RISK_REWARD_RATIO,
    confirms_higher_timeframe_trend,
    generate_signal,
)
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


def test_atr_stop_multiplier_parameter_widens_stop_and_target_proportionally():
    candles = _candles_from_closes(_decline_then_rise())
    default_signal = generate_signal("TESTUSDT", candles)
    wider_signal = generate_signal("TESTUSDT", candles, atr_stop_multiplier=3.0)

    assert default_signal is not None and wider_signal is not None
    default_risk = default_signal.entry - default_signal.stop_loss
    wider_risk = wider_signal.entry - wider_signal.stop_loss
    # dobrar o múltiplo (1.5 -> 3.0) dobra a distância do risco, e o alvo escala junto (R:R
    # continua fixo em RISK_REWARD_RATIO)
    assert wider_risk == pytest.approx(default_risk * (3.0 / ATR_STOP_MULTIPLIER))
    assert (wider_signal.target - wider_signal.entry) == pytest.approx(
        wider_risk * RISK_REWARD_RATIO
    )


def test_no_signal_on_flat_price_series():
    candles = _candles_from_closes([100.0] * 50)

    assert generate_signal("TESTUSDT", candles) is None


def test_no_signal_with_insufficient_history():
    candles = _candles_from_closes([100.0, 101.0, 99.0])

    assert generate_signal("TESTUSDT", candles) is None


def test_confirms_higher_timeframe_trend_for_long_in_an_uptrend():
    htf_candles = _candles_from_closes([100.0 + i * 0.5 for i in range(30)])

    assert confirms_higher_timeframe_trend(htf_candles, "long") is True
    assert confirms_higher_timeframe_trend(htf_candles, "short") is False


def test_confirms_higher_timeframe_trend_for_short_in_a_downtrend():
    htf_candles = _candles_from_closes([100.0 - i * 0.5 for i in range(30)])

    assert confirms_higher_timeframe_trend(htf_candles, "short") is True
    assert confirms_higher_timeframe_trend(htf_candles, "long") is False


def test_confirms_higher_timeframe_trend_false_when_not_enough_history():
    assert confirms_higher_timeframe_trend(_candles_from_closes([100.0]), "long") is False


def test_higher_timeframe_filter_blocks_long_signal_against_the_bigger_trend():
    candles = _candles_from_closes(_decline_then_rise())
    downtrend_htf = _candles_from_closes([200.0 - i * 0.5 for i in range(30)])

    assert generate_signal("TESTUSDT", candles) is not None  # sem filtro, dispara normalmente
    assert generate_signal("TESTUSDT", candles, higher_tf_candles=downtrend_htf) is None


def test_higher_timeframe_filter_allows_long_signal_with_the_bigger_trend():
    candles = _candles_from_closes(_decline_then_rise())
    uptrend_htf = _candles_from_closes([50.0 + i * 0.5 for i in range(30)])

    signal = generate_signal("TESTUSDT", candles, higher_tf_candles=uptrend_htf)

    assert signal is not None
    assert signal.direction == "long"
