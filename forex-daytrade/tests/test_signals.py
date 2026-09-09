import pytest

from analysis.signals import (
    ATR_STOP_MULTIPLIER,
    RISK_REWARD_RATIO,
    confirms_higher_timeframe_trend,
    confirms_price_structure_range,
    generate_signal,
)
from data.twelvedata_client import Candle

_UNREACHABLE_RSI_RANGE = (200.0, 300.0)  # nunca bate — usado pra provar que o parâmetro é respeitado


def _candles_from_closes(closes: list[float]) -> list[Candle]:
    return [
        Candle(open_time_ms=i, open=c, high=c + 0.0003, low=c - 0.0003, close=c, volume=0.0)
        for i, c in enumerate(closes)
    ]


def _decline_then_rise(decline_candles=40, decline_step=0.0001, rise_candles=9, rise_step=0.00018):
    """Queda leve e prolongada seguida de alta — reproduz um cruzamento de EMA9 acima da
    EMA21 com RSI dentro da faixa que confirma o sinal. Mesmo espírito do fixture usado em
    crypto-daytrade, só escalado pra magnitude de preço típica de forex (~1.1000)."""
    closes = []
    price = 1.1000
    for _ in range(decline_candles):
        price -= decline_step
        closes.append(price)
    for _ in range(rise_candles):
        price += rise_step
        closes.append(price)
    return closes


def _rise_then_decline(rise_candles=40, rise_step=0.0001, decline_candles=9, decline_step=0.00018):
    """Espelho do fixture acima — reproduz um cruzamento de EMA9 abaixo da EMA21."""
    closes = []
    price = 1.1000
    for _ in range(rise_candles):
        price += rise_step
        closes.append(price)
    for _ in range(decline_candles):
        price -= decline_step
        closes.append(price)
    return closes


def test_generates_long_signal_on_bullish_ema_cross_with_confirming_rsi():
    candles = _candles_from_closes(_decline_then_rise())

    signal = generate_signal("EUR/USD", candles)

    assert signal is not None
    assert signal.direction == "long"
    assert signal.symbol == "EUR/USD"
    assert 30 <= signal.rsi_value <= 65
    assert signal.stop_loss < signal.entry < signal.target


def test_generates_short_signal_on_bearish_ema_cross_with_confirming_rsi():
    candles = _candles_from_closes(_rise_then_decline())

    signal = generate_signal("EUR/USD", candles)

    assert signal is not None
    assert signal.direction == "short"
    assert 35 <= signal.rsi_value <= 70
    assert signal.target < signal.entry < signal.stop_loss


def test_target_risk_reward_ratio_matches_configured_value():
    candles = _candles_from_closes(_decline_then_rise())
    signal = generate_signal("EUR/USD", candles)

    risk = signal.entry - signal.stop_loss
    reward = signal.target - signal.entry
    assert reward == pytest.approx(risk * RISK_REWARD_RATIO)


def test_atr_stop_multiplier_parameter_widens_stop_and_target_proportionally():
    candles = _candles_from_closes(_decline_then_rise())
    default_signal = generate_signal("EUR/USD", candles)
    wider_signal = generate_signal("EUR/USD", candles, atr_stop_multiplier=3.0)

    assert default_signal is not None and wider_signal is not None
    default_risk = default_signal.entry - default_signal.stop_loss
    wider_risk = wider_signal.entry - wider_signal.stop_loss
    assert wider_risk == pytest.approx(default_risk * (3.0 / ATR_STOP_MULTIPLIER))
    assert (wider_signal.target - wider_signal.entry) == pytest.approx(
        wider_risk * RISK_REWARD_RATIO
    )


def test_long_rsi_range_parameter_blocks_signal_outside_custom_range():
    candles = _candles_from_closes(_decline_then_rise())
    assert generate_signal("EUR/USD", candles) is not None

    blocked = generate_signal("EUR/USD", candles, long_rsi_range=_UNREACHABLE_RSI_RANGE)
    assert blocked is None


def test_short_rsi_range_parameter_blocks_signal_outside_custom_range():
    candles = _candles_from_closes(_rise_then_decline())
    assert generate_signal("EUR/USD", candles) is not None

    blocked = generate_signal("EUR/USD", candles, short_rsi_range=_UNREACHABLE_RSI_RANGE)
    assert blocked is None


def test_no_signal_on_flat_price_series():
    candles = _candles_from_closes([1.1000] * 50)

    assert generate_signal("EUR/USD", candles) is None


def test_no_signal_with_insufficient_history():
    candles = _candles_from_closes([1.1000, 1.1010, 1.0990])

    assert generate_signal("EUR/USD", candles) is None


def test_confirms_higher_timeframe_trend_for_long_in_an_uptrend():
    htf_candles = _candles_from_closes([1.1000 + i * 0.0005 for i in range(30)])

    assert confirms_higher_timeframe_trend(htf_candles, "long") is True
    assert confirms_higher_timeframe_trend(htf_candles, "short") is False


def test_confirms_higher_timeframe_trend_for_short_in_a_downtrend():
    htf_candles = _candles_from_closes([1.1000 - i * 0.0005 for i in range(30)])

    assert confirms_higher_timeframe_trend(htf_candles, "short") is True
    assert confirms_higher_timeframe_trend(htf_candles, "long") is False


def test_confirms_higher_timeframe_trend_false_when_not_enough_history():
    assert confirms_higher_timeframe_trend(_candles_from_closes([1.1000]), "long") is False


def test_higher_timeframe_filter_is_off_by_default():
    # ao contrário de crypto-daytrade, generate_signal aqui não filtra por tendência de
    # timeframe maior a menos que higher_tf_candles seja passado explicitamente — ainda não
    # validado via backtest pra forex (ver docstring de analysis/signals.py)
    candles = _candles_from_closes(_decline_then_rise())
    assert generate_signal("EUR/USD", candles) is not None


def test_higher_timeframe_filter_blocks_long_signal_against_the_bigger_trend_when_passed():
    candles = _candles_from_closes(_decline_then_rise())
    downtrend_htf = _candles_from_closes([2.0000 - i * 0.0005 for i in range(30)])

    assert generate_signal("EUR/USD", candles, higher_tf_candles=downtrend_htf) is None


def test_price_structure_range_filter_is_off_by_default():
    # mesma razão do teste acima — min_range_expansion=None é o default aqui
    candles = _candles_from_closes(_decline_then_rise())
    assert generate_signal("EUR/USD", candles) is not None


def test_price_structure_range_parameter_blocks_when_passed_and_range_is_tight():
    candles = _candles_from_closes(_decline_then_rise())
    signal = generate_signal("EUR/USD", candles, min_range_expansion=6.0)
    assert signal is None


def test_confirms_price_structure_range_passes_for_a_steady_uptrend():
    closes = [1.1000 + i * 0.001 for i in range(20)]
    assert confirms_price_structure_range(_candles_from_closes(closes)) is True


def test_confirms_price_structure_range_blocks_a_tight_overlapping_range():
    closes = [1.1000 + (0.001 if i % 2 == 0 else -0.001) for i in range(20)]  # candles se sobrepõem
    assert confirms_price_structure_range(_candles_from_closes(closes)) is False


def test_confirms_price_structure_range_blocks_when_not_enough_history():
    closes = [1.1000 + i * 0.001 for i in range(10)]
    assert confirms_price_structure_range(_candles_from_closes(closes)) is False
