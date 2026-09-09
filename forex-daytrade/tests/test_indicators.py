import pytest

from analysis.indicators import adx, atr, bollinger_bands, ema, rsi


def test_ema_of_constant_series_equals_the_constant():
    prices = [100.0] * 30
    result = ema(prices, period=9)

    assert result
    assert all(v == pytest.approx(100.0) for v in result)


def test_ema_reacts_faster_than_a_plain_average_to_a_jump():
    # preço estável em 100 por um tempo, depois pula pra 200 — a EMA deve se mover na
    # direção do novo preço, mas sem alcançá-lo de imediato (suavização)
    prices = [100.0] * 20 + [200.0] * 5
    result = ema(prices, period=9)

    assert result[-1] > 100.0
    assert result[-1] < 200.0


def test_ema_returns_empty_when_not_enough_data():
    assert ema([1.0, 2.0], period=9) == []


def test_rsi_is_100_when_strictly_increasing():
    prices = [100.0 + i for i in range(20)]  # só altas, nunca cai
    result = rsi(prices, period=14)

    assert result
    assert all(v == pytest.approx(100.0) for v in result)


def test_rsi_is_0_when_strictly_decreasing():
    prices = [100.0 - i for i in range(20)]  # só quedas, nunca sobe
    result = rsi(prices, period=14)

    assert result
    assert all(v == pytest.approx(0.0) for v in result)


def test_rsi_is_near_50_when_alternating_evenly():
    prices = [100.0 + (i % 2) for i in range(30)]  # sobe/desce alternado, mesma magnitude
    result = rsi(prices, period=14)

    assert result
    assert all(40 < v < 60 for v in result)


def test_rsi_returns_empty_when_not_enough_data():
    assert rsi([1.0, 2.0, 3.0], period=14) == []


def test_atr_of_constant_range_equals_that_range():
    # high sempre 2 acima do low, close sempre no meio — true range fica constante em 2
    n = 20
    highs = [101.0] * n
    lows = [99.0] * n
    closes = [100.0] * n

    result = atr(highs, lows, closes, period=14)

    assert result
    assert all(v == pytest.approx(2.0) for v in result)


def test_atr_returns_empty_when_not_enough_data():
    assert atr([1.0, 2.0], [1.0, 2.0], [1.0, 2.0], period=14) == []


def test_adx_is_high_for_a_steady_uptrend():
    # sobe um valor fixo por candle, sem retração nenhuma — tendência forte e limpa
    n = 40
    closes = [100.0 + i for i in range(n)]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]

    result = adx(highs, lows, closes, period=14)

    assert result
    assert result[-1] > 40.0  # bem acima do limiar de ~20-25 usado como filtro de tendência


def test_adx_is_low_for_a_sideways_market():
    # oscila pra cima e pra baixo em torno do mesmo nível — sem direção definida
    n = 40
    closes = [100.0 + (2.0 if i % 2 == 0 else -2.0) for i in range(n)]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]

    result = adx(highs, lows, closes, period=14)

    assert result
    assert result[-1] < 20.0


def test_adx_returns_empty_when_not_enough_data():
    assert adx([1.0, 2.0], [1.0, 2.0], [1.0, 2.0], period=14) == []


def test_bollinger_bands_of_constant_series_has_zero_width():
    prices = [100.0] * 25
    upper, middle, lower = bollinger_bands(prices, period=20, num_std=2.0)

    assert upper and middle and lower
    assert all(v == pytest.approx(100.0) for v in upper)
    assert all(v == pytest.approx(100.0) for v in middle)
    assert all(v == pytest.approx(100.0) for v in lower)


def test_bollinger_bands_widens_with_more_volatility():
    steady = [100.0] * 25
    volatile = [100.0 + (5.0 if i % 2 == 0 else -5.0) for i in range(25)]

    steady_upper, _, steady_lower = bollinger_bands(steady, period=20)
    volatile_upper, _, volatile_lower = bollinger_bands(volatile, period=20)

    assert (volatile_upper[-1] - volatile_lower[-1]) > (steady_upper[-1] - steady_lower[-1])


def test_bollinger_bands_middle_is_the_simple_moving_average():
    prices = [100.0 + i for i in range(25)]  # rampa linear, SMA fácil de conferir de cabeça
    _, middle, _ = bollinger_bands(prices, period=20)

    expected_sma = sum(prices[-20:]) / 20
    assert middle[-1] == pytest.approx(expected_sma)


def test_bollinger_bands_returns_empty_when_not_enough_data():
    assert bollinger_bands([1.0, 2.0], period=20) == ([], [], [])
