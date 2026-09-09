from backtest.filters import passes_adx_filter, passes_signal_candle_quality_filter
from data.binance_client import Candle


def _candles_from_closes(closes: list[float]) -> list[Candle]:
    return [
        Candle(open_time_ms=i, open=c, high=c + 1.0, low=c - 1.0, close=c, volume=100.0)
        for i, c in enumerate(closes)
    ]


def _flat_window_with_final_candle(final: Candle, flat_price: float = 100.0, count: int = 40) -> list[Candle]:
    """Janela achatada (EMA21 converge pro `flat_price` exato) seguida de um candle final
    customizado — deixa o teste focado só no comportamento do candle de sinal, sem precisar
    calcular a EMA de cabeça."""
    window = _candles_from_closes([flat_price] * (count - 1))
    return window + [final]


def test_adx_filter_passes_for_a_steady_uptrend():
    closes = [100.0 + i for i in range(40)]
    assert passes_adx_filter(_candles_from_closes(closes), min_adx=25.0) is True


def test_adx_filter_blocks_a_sideways_market():
    closes = [100.0 + (2.0 if i % 2 == 0 else -2.0) for i in range(40)]
    assert passes_adx_filter(_candles_from_closes(closes), min_adx=25.0) is False


def test_adx_filter_blocks_when_not_enough_history():
    assert passes_adx_filter(_candles_from_closes([100.0, 101.0]), min_adx=25.0) is False


def test_signal_candle_quality_passes_for_strong_long_bar():
    # corpo inteiro (100.5-101.0) acima da EMA21 (~100.0) e fechamento perto da máxima
    final = Candle(open_time_ms=999, open=100.5, high=101.2, low=100.3, close=101.0, volume=100.0)
    window = _flat_window_with_final_candle(final)
    assert passes_signal_candle_quality_filter(window, "long", min_close_position=0.5) is True


def test_signal_candle_quality_blocks_weak_close_for_long():
    # corpo acima da EMA21, mas fecha perto da mínima do candle (sem força de fechamento)
    final = Candle(open_time_ms=999, open=100.1, high=101.0, low=100.0, close=100.2, volume=100.0)
    window = _flat_window_with_final_candle(final)
    assert passes_signal_candle_quality_filter(window, "long", min_close_position=0.5) is False


def test_signal_candle_quality_blocks_body_not_fully_above_ema_for_long():
    # abertura abaixo da EMA21 — corpo não está inteiramente acima, mesmo fechando bem
    final = Candle(open_time_ms=999, open=99.5, high=101.0, low=99.0, close=100.5, volume=100.0)
    window = _flat_window_with_final_candle(final)
    assert passes_signal_candle_quality_filter(window, "long", min_close_position=0.5) is False


def test_signal_candle_quality_passes_for_strong_short_bar():
    # corpo inteiro (99.0-99.5) abaixo da EMA21 (~100.0) e fechamento perto da mínima
    final = Candle(open_time_ms=999, open=99.5, high=99.7, low=98.8, close=99.0, volume=100.0)
    window = _flat_window_with_final_candle(final)
    assert passes_signal_candle_quality_filter(window, "short", min_close_position=0.5) is True


def test_signal_candle_quality_blocks_zero_range_candle():
    final = Candle(open_time_ms=999, open=101.0, high=101.0, low=101.0, close=101.0, volume=100.0)
    window = _flat_window_with_final_candle(final)
    assert passes_signal_candle_quality_filter(window, "long", min_close_position=0.5) is False


def test_signal_candle_quality_blocks_when_not_enough_history():
    short_window = _candles_from_closes([100.0] * 5)
    assert passes_signal_candle_quality_filter(short_window, "long", min_close_position=0.5) is False
