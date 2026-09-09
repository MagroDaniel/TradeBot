import pytest

from analysis.mean_reversion_signals import generate_signal, reprice_signal_for_entry
from data.twelvedata_client import Candle


def _candles_from_closes(closes: list[float]) -> list[Candle]:
    return [
        Candle(open_time_ms=i, open=c, high=c + 0.05, low=c - 0.05, close=c, volume=0.0)
        for i, c in enumerate(closes)
    ]


def _flat_then_drop(flat_candles=40, flat_price=1.1000, drop_step=0.0015, drop_candles=3):
    """Preço estável (RSI neutro, bandas apertadas), seguido de queda abrupta — empurra o
    fechamento pra fora/na banda inferior com RSI sobrevendido, validado empiricamente."""
    closes = [flat_price] * flat_candles
    price = flat_price
    for _ in range(drop_candles):
        price -= drop_step
        closes.append(price)
    return closes


def _flat_then_rise(flat_candles=40, flat_price=1.1000, rise_step=0.0015, rise_candles=3):
    closes = [flat_price] * flat_candles
    price = flat_price
    for _ in range(rise_candles):
        price += rise_step
        closes.append(price)
    return closes


def test_generates_long_signal_on_oversold_touch_of_lower_band():
    candles = _candles_from_closes(_flat_then_drop())

    signal = generate_signal("EUR/USD", candles)

    assert signal is not None
    assert signal.direction == "long"
    assert signal.symbol == "EUR/USD"
    assert signal.rsi_value <= 30.0
    # stop abaixo da entrada, alvo (banda central) acima — aposta na volta pra média
    assert signal.stop_loss < signal.entry < signal.target


def test_generates_short_signal_on_overbought_touch_of_upper_band():
    candles = _candles_from_closes(_flat_then_rise())

    signal = generate_signal("EUR/USD", candles)

    assert signal is not None
    assert signal.direction == "short"
    assert signal.rsi_value >= 70.0
    assert signal.target < signal.entry < signal.stop_loss


def test_no_signal_on_flat_price_series():
    candles = _candles_from_closes([1.1000] * 50)

    assert generate_signal("EUR/USD", candles) is None


def test_no_signal_with_insufficient_history():
    candles = _candles_from_closes([1.1000, 1.1010, 1.0990])

    assert generate_signal("EUR/USD", candles) is None


def test_rsi_oversold_parameter_blocks_signal_when_threshold_unreachable():
    candles = _candles_from_closes(_flat_then_drop())
    assert generate_signal("EUR/USD", candles) is not None  # RSI padrão (<=30) confirma

    # RSI é limitado a [0, 100] — um limiar negativo nunca é alcançável, prova que o
    # parâmetro é respeitado sem depender de calibrar a magnitude exata do fixture.
    blocked = generate_signal("EUR/USD", candles, rsi_oversold=-10.0)
    assert blocked is None


def test_bb_num_std_parameter_wider_band_blocks_a_weaker_move():
    # queda de 1 candle (RSI sempre bate 0, isolado com rsi_oversold=100) — toca a banda de 1
    # desvio, mas não a de 5 (valores calibrados empiricamente pra esse fixture específico)
    candles = _candles_from_closes(_flat_then_drop(drop_step=0.0002, drop_candles=1))

    narrow = generate_signal("EUR/USD", candles, bb_num_std=1.0, rsi_oversold=100.0)
    wide = generate_signal("EUR/USD", candles, bb_num_std=5.0, rsi_oversold=100.0)

    assert narrow is not None
    assert wide is None


def test_reprice_signal_for_entry_preserves_risk_and_target_distance():
    candles = _candles_from_closes(_flat_then_drop())
    signal = generate_signal("EUR/USD", candles)
    assert signal is not None

    risk = signal.entry - signal.stop_loss
    target_distance = signal.target - signal.entry

    gapped_entry = signal.entry - 0.0010  # gap pra baixo na execução
    repriced = reprice_signal_for_entry(signal, gapped_entry)

    assert repriced.entry == pytest.approx(gapped_entry)
    assert (repriced.entry - repriced.stop_loss) == pytest.approx(risk)
    assert (repriced.target - repriced.entry) == pytest.approx(target_distance)


def test_reprice_signal_for_entry_rejects_non_positive_price():
    candles = _candles_from_closes(_flat_then_drop())
    signal = generate_signal("EUR/USD", candles)
    assert signal is not None

    with pytest.raises(ValueError):
        reprice_signal_for_entry(signal, 0.0)
