import pytest

from tradebot.indicators import adx, atr, ema, rsi


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


# --- indicadores novos (não existiam no crypto-daytrade) ---
from tradebot.indicators import bollinger, donchian, sma, supertrend  # noqa: E402


def test_sma_is_rolling_mean():
    assert sma([1, 2, 3, 4, 5], 3) == pytest.approx([2, 3, 4])


def test_bollinger_flat_series_has_zero_width():
    lower, middle, upper = bollinger([10.0] * 25, 20, 2.0)
    assert len(middle) == 6
    assert lower[-1] == middle[-1] == upper[-1] == pytest.approx(10.0)


def test_bollinger_bands_surround_mean():
    values = [10, 11, 9, 10, 12, 8, 10, 11, 9, 10] * 3
    lower, middle, upper = bollinger(values, 10, 2.0)
    assert all(lo < mid < up for lo, mid, up in zip(lower, middle, upper))


def test_donchian_includes_current_candle():
    highs = [1, 5, 3, 2]
    lows = [0, 2, 1, 1]
    upper, lower = donchian(highs, lows, 3)
    assert upper == [5, 5]
    assert lower == [0, 1]


def test_supertrend_follows_clear_trends():
    up = [100 + i for i in range(40)]
    down = [139 - i * 2 for i in range(40)]
    closes = up + down
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    line, direction = supertrend(highs, lows, closes, 10, 3.0)
    assert direction[len(up) - 15] == 1  # ainda na subida
    assert direction[-1] == -1  # virou na descida
    assert line[-1] > closes[-1]  # em baixa a linha fica acima do preço
