import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.helpers import make_candles, random_walk
from tradebot.models import LONG, SHORT, Candle
from tradebot.strategies import STRATEGIES, get_strategy

CRYPTO_DIR = Path(__file__).resolve().parents[2] / "crypto-daytrade"


def test_registry_has_unique_names_and_valid_defaults():
    for name, strategy in STRATEGIES.items():
        assert strategy.name == name
        params = strategy.resolve(None)
        assert strategy.timeframe(params)
        assert strategy.warmup(params) > 0


def test_param_validation_rejects_out_of_range():
    with pytest.raises(ValueError):
        get_strategy("ema_cross").resolve({"atr_stop": 999})
    with pytest.raises(ValueError):
        get_strategy("ema_cross").resolve({"timeframe": "7m"})


def test_unknown_param_is_ignored():
    params = get_strategy("ema_cross").resolve({"campo_antigo": 1})
    assert "campo_antigo" not in params


@pytest.mark.skipif(not CRYPTO_DIR.exists(), reason="crypto-daytrade não está no checkout")
def test_ema_cross_matches_crypto_daytrade_production_signal():
    """Paridade: a estratégia portada tem que gerar EXATAMENTE os mesmos sinais que o bot de
    alertas validado em backtest (mesma janela de 100 candles + 50 de 1h)."""
    sys.path.insert(0, str(CRYPTO_DIR))
    try:
        from analysis.signals import generate_signal as legacy_generate  # type: ignore
        from data.binance_client import Candle as LegacyCandle  # type: ignore
    finally:
        sys.path.remove(str(CRYPTO_DIR))

    strategy = get_strategy("ema_cross")
    params = strategy.resolve(None)
    matches = signals = 0
    for seed in range(12):
        closes = random_walk(2000, seed=seed, vol=0.008)
        candles = make_candles(closes)
        hourly = make_candles(closes[::4], minutes=60)
        for i in range(400, len(candles)):
            window = candles[i - 100:i]
            htf = [c for c in hourly if c.close_time_ms < candles[i].open_time_ms][-50:]
            new = strategy.generate("X", window, htf, params)
            legacy = legacy_generate(
                "X", [LegacyCandle(c.open_time_ms, c.open, c.high, c.low, c.close, c.volume, c.close_time_ms)
                      for c in window],
                [LegacyCandle(c.open_time_ms, c.open, c.high, c.low, c.close, c.volume, c.close_time_ms) for c in htf],
            )
            assert (new is None) == (legacy is None), f"seed {seed} idx {i}"
            if new:
                signals += 1
                assert new.direction == legacy.direction
                assert new.exit_plan.stop_loss == pytest.approx(legacy.stop_loss)
                assert new.exit_plan.take_profit == pytest.approx(legacy.target)
                matches += 1
    assert signals > 0  # o teste precisa de fato exercitar sinais


def _flat_then(closes_tail: list[float], flat: float = 100.0, n_flat: int = 300, wiggle: float = 0.3) -> list[float]:
    base = [flat + (wiggle if i % 2 else -wiggle) for i in range(n_flat)]
    return base + closes_tail


def test_donchian_breakout_long_on_first_close_above_channel():
    strategy = get_strategy("donchian_breakout")
    params = strategy.resolve({"trend_ema": 0})
    candles = make_candles(_flat_then([103.0]), minutes=60, spread=0.0)
    signal = strategy.generate("X", candles, None, params)
    assert signal and signal.direction == LONG
    assert signal.exit_plan.take_profit is None
    assert signal.exit_plan.trailing_distance > 0
    # no candle seguinte, ainda acima, NÃO repete o sinal
    assert strategy.generate("X", make_candles(_flat_then([103.0, 104.0]), minutes=60, spread=0.0), None, params) is None


def test_donchian_trend_filter_blocks_counter_trend_breakout():
    strategy = get_strategy("donchian_breakout")
    params = strategy.resolve({"trend_ema": 200})
    falling = [200 - i * 0.3 for i in range(300)]
    closes = falling + [falling[-1] + 0.2] * 25 + [falling[-1] + 3]
    assert strategy.generate("X", make_candles(closes, minutes=60, spread=0.0), None, params) is None


def test_donchian_exit_channel():
    strategy = get_strategy("donchian_breakout")
    params = strategy.resolve({"trend_ema": 0, "exit_channel": 10})
    candles = make_candles(_flat_then([103.0, 104.0, 98.0]), minutes=60, spread=0.0)
    from tests.helpers import make_position
    assert strategy.should_exit(make_position(direction="long"), candles, params)
    assert not strategy.should_exit(make_position(direction="short"), candles, params)


def _noisy_range(seed: int = 1, n: int = 300) -> list[float]:
    import random
    rng = random.Random(seed)
    return [100 + rng.gauss(0, 0.4) for _ in range(n)]


def test_bollinger_reversion_long_in_flat_market_after_drop():
    strategy = get_strategy("bollinger_reversion")
    params = strategy.resolve({"rsi_low": 35})  # fixture chega a RSI ~33, ADX ~16
    candles = make_candles(_noisy_range() + [99.4, 98.8, 98.2, 97.6], spread=0.001)
    signal = strategy.generate("X", candles[-100:], None, params)
    assert signal and signal.direction == LONG
    assert signal.exit_plan.take_profit > signal.entry  # alvo = média central


def test_bollinger_reversion_skips_strong_trend():
    strategy = get_strategy("bollinger_reversion")
    params = strategy.resolve(None)
    falling = [100 * (1 - 0.004 * i) for i in range(200)]
    assert strategy.generate("X", make_candles(falling), None, params) is None


def test_supertrend_flip_with_htf_filter():
    strategy = get_strategy("supertrend")
    closes = [100 - i * 0.5 for i in range(120)] + [40 + i * 1.5 for i in range(40)]
    candles = make_candles(closes, spread=0.003)
    params = strategy.resolve({"use_htf_filter": False})
    found = [strategy.generate("X", candles[:i], None, params) for i in range(121, len(candles) + 1)]
    longs = [s for s in found if s]
    assert longs and longs[0].direction == LONG
    assert longs[0].exit_plan.stop_loss < longs[0].entry
    # com filtro e 1h ainda em baixa, bloqueia
    params_htf = strategy.resolve({"use_htf_filter": True})
    htf_down = make_candles([200 - i for i in range(60)], minutes=60)
    flip_idx = 121 + found.index(longs[0])
    assert strategy.generate("X", candles[:flip_idx], htf_down, params_htf) is None


def _hourly_day(moves: list[float], start=datetime(2026, 3, 2, tzinfo=timezone.utc)) -> list[Candle]:
    start_ms = int(start.timestamp() * 1000)
    closes = [100.0]
    for m in moves:
        closes.append(closes[-1] * (1 + m))
    return make_candles(closes[1:], start_ms=start_ms, minutes=60)


def test_session_momentum_enters_at_entry_hour_in_direction_of_move():
    strategy = get_strategy("session_momentum")
    params = strategy.resolve(None)
    prev_day = _hourly_day([0.0005 * (-1) ** i for i in range(24)], datetime(2026, 3, 1, tzinfo=timezone.utc))
    today = _hourly_day([0.001] * 14, datetime(2026, 3, 2, tzinfo=timezone.utc))
    signal = strategy.generate("BTCUSDT", prev_day + today, None, params)
    assert signal and signal.direction == LONG
    assert signal.exit_plan.time_limit_minutes == 7 * 60
    # uma hora depois não entra de novo
    later = _hourly_day([0.001] * 15, datetime(2026, 3, 2, tzinfo=timezone.utc))
    assert strategy.generate("BTCUSDT", prev_day + later, None, params) is None


def test_session_momentum_short_and_threshold():
    strategy = get_strategy("session_momentum")
    params = strategy.resolve(None)
    prev_day = _hourly_day([0.0] * 24, datetime(2026, 3, 1, tzinfo=timezone.utc))
    down = _hourly_day([-0.001] * 14, datetime(2026, 3, 2, tzinfo=timezone.utc))
    assert strategy.generate("BTCUSDT", prev_day + down, None, params).direction == SHORT
    tiny = _hourly_day([0.0001] * 14, datetime(2026, 3, 2, tzinfo=timezone.utc))
    assert strategy.generate("BTCUSDT", prev_day + tiny, None, params) is None
