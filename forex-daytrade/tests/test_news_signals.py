from datetime import datetime, timedelta, timezone

import pytest

from analysis.news_signals import (
    WAIT_MINUTES_AFTER_RELEASE,
    classify_indicator,
    currency_strengthens,
    direction_for_pair,
    generate_signal,
    reprice_signal_for_entry,
)
from data.forexfactory_client import EconomicEvent
from data.twelvedata_client import Candle

_RELEASE_DT = datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc)


def _event(**overrides) -> EconomicEvent:
    base = dict(
        title="Non-Farm Payrolls",
        country="USD",
        date=_RELEASE_DT.isoformat(),
        impact="High",
        forecast="180K",
        previous="150K",
        actual="220K",
    )
    base.update(overrides)
    return EconomicEvent(**base)


def _candles(n=30, base=1.1000, step=0.0001) -> list[Candle]:
    return [
        Candle(
            open_time_ms=i, open=base + i * step, high=base + i * step + 0.0005,
            low=base + i * step - 0.0005, close=base + i * step, volume=0.0,
        )
        for i in range(n)
    ]


def test_classify_indicator_recognizes_higher_is_stronger():
    assert classify_indicator("Non-Farm Payrolls") is True
    assert classify_indicator("CPI m/m") is True
    assert classify_indicator("Core CPI y/y") is True


def test_classify_indicator_recognizes_lower_is_stronger():
    assert classify_indicator("Unemployment Rate") is False
    assert classify_indicator("Initial Jobless Claims") is False


def test_classify_indicator_returns_none_for_unknown_title():
    assert classify_indicator("ANZ Job Advertisements m/m") is None


def test_currency_strengthens_true_when_higher_is_stronger_and_beats_forecast():
    event = _event(title="Non-Farm Payrolls", actual="220K", forecast="180K")
    assert currency_strengthens(event) is True


def test_currency_strengthens_false_when_higher_is_stronger_and_misses_forecast():
    event = _event(title="Non-Farm Payrolls", actual="140K", forecast="180K")
    assert currency_strengthens(event) is False


def test_currency_strengthens_inverts_for_lower_is_stronger_indicator():
    # desemprego ACIMA do previsto -> enfraquece a moeda (não fortalece)
    event = _event(title="Unemployment Rate", actual="4.5%", forecast="4.1%")
    assert currency_strengthens(event) is False

    # desemprego ABAIXO do previsto -> fortalece
    event2 = _event(title="Unemployment Rate", actual="3.9%", forecast="4.1%")
    assert currency_strengthens(event2) is True


def test_currency_strengthens_none_for_unrecognized_indicator():
    event = _event(title="ANZ Job Advertisements m/m", actual="1.0%", forecast="0.8%")
    assert currency_strengthens(event) is None


def test_currency_strengthens_none_without_actual_yet():
    event = _event(actual=None)
    assert currency_strengthens(event) is None


def test_currency_strengthens_none_when_actual_equals_forecast():
    event = _event(actual="180K", forecast="180K")
    assert currency_strengthens(event) is None


def test_direction_for_pair_long_when_base_currency_strengthens():
    assert direction_for_pair("EUR", strengthens=True, symbol="EUR/USD") == "long"
    assert direction_for_pair("EUR", strengthens=False, symbol="EUR/USD") == "short"


def test_direction_for_pair_inverted_when_quote_currency_strengthens():
    # USD é a cotação de EUR/USD — USD fortalecendo significa EUR/USD cai (short)
    assert direction_for_pair("USD", strengthens=True, symbol="EUR/USD") == "short"
    assert direction_for_pair("USD", strengthens=False, symbol="EUR/USD") == "long"


def test_direction_for_pair_none_when_currency_does_not_affect_the_symbol():
    assert direction_for_pair("JPY", strengthens=True, symbol="EUR/USD") is None


def test_generate_signal_returns_none_before_wait_window_closes():
    event = _event()
    too_early = _RELEASE_DT + timedelta(minutes=WAIT_MINUTES_AFTER_RELEASE - 1)

    signal = generate_signal(event, "EUR/USD", _candles(), now=too_early)

    assert signal is None


def test_generate_signal_returns_short_after_wait_window_for_usd_beat():
    # NFP dos EUA veio acima do esperado -> USD fortalece -> EUR/USD cai -> short
    event = _event(title="Non-Farm Payrolls", country="USD", actual="220K", forecast="180K")
    after_wait = _RELEASE_DT + timedelta(minutes=WAIT_MINUTES_AFTER_RELEASE)

    signal = generate_signal(event, "EUR/USD", _candles(), now=after_wait)

    assert signal is not None
    assert signal.direction == "short"
    assert signal.target < signal.entry < signal.stop_loss


def test_generate_signal_returns_long_when_base_currency_beats_forecast():
    event = _event(title="GDP", country="EUR", actual="0.8%", forecast="0.5%")
    after_wait = _RELEASE_DT + timedelta(minutes=WAIT_MINUTES_AFTER_RELEASE)

    signal = generate_signal(event, "EUR/USD", _candles(), now=after_wait)

    assert signal is not None
    assert signal.direction == "long"
    assert signal.stop_loss < signal.entry < signal.target


def test_generate_signal_returns_none_for_unrelated_currency():
    event = _event(title="Non-Farm Payrolls", country="JPY", actual="220K", forecast="180K")
    after_wait = _RELEASE_DT + timedelta(minutes=WAIT_MINUTES_AFTER_RELEASE)

    assert generate_signal(event, "EUR/USD", _candles(), now=after_wait) is None


def test_generate_signal_returns_none_without_enough_candle_history():
    event = _event()
    after_wait = _RELEASE_DT + timedelta(minutes=WAIT_MINUTES_AFTER_RELEASE)

    assert generate_signal(event, "EUR/USD", _candles(n=3), now=after_wait) is None


def test_reprice_signal_for_entry_preserves_risk_and_target_distance():
    event = _event()
    after_wait = _RELEASE_DT + timedelta(minutes=WAIT_MINUTES_AFTER_RELEASE)
    signal = generate_signal(event, "EUR/USD", _candles(), now=after_wait)
    assert signal is not None

    risk = abs(signal.entry - signal.stop_loss)
    target_distance = abs(signal.target - signal.entry)
    gapped_entry = signal.entry - 0.0010
    repriced = reprice_signal_for_entry(signal, gapped_entry)

    assert repriced.entry == pytest.approx(gapped_entry)
    assert abs(repriced.entry - repriced.stop_loss) == pytest.approx(risk)
    assert abs(repriced.target - repriced.entry) == pytest.approx(target_distance)


def test_reprice_signal_for_entry_rejects_non_positive_price():
    event = _event()
    after_wait = _RELEASE_DT + timedelta(minutes=WAIT_MINUTES_AFTER_RELEASE)
    signal = generate_signal(event, "EUR/USD", _candles(), now=after_wait)
    assert signal is not None

    with pytest.raises(ValueError):
        reprice_signal_for_entry(signal, 0.0)
