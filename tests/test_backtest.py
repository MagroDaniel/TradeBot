import pytest

from tests.helpers import make_candles
from tradebot.backtest import Costs, Limits, bootstrap_p_value, run_backtest, split_by_period, summarize, Trade
from tradebot.models import ExitPlan, Signal
from tradebot.strategies.base import Strategy


class EveryNth(Strategy):
    """Sinal long quando o número de candles da janela bate um índice pré-definido."""
    name = "every"

    def __init__(self, fire_on_close_of: set[int], stop=0.02, tp=0.04):
        self.fire = fire_on_close_of
        self.stop, self.tp = stop, tp
        self.seen_last_close_times = []

    def warmup(self, p):
        return 5

    def generate(self, symbol, candles, htf, p):
        self.seen_last_close_times.append(candles[-1].close_time_ms)
        if candles[-1].open_time_ms in self.fire:
            e = candles[-1].close
            return Signal(symbol, "long", e, ExitPlan(e * (1 - self.stop), e * (1 + self.tp)), "t", self.name)
        return None


def test_entry_is_next_open_and_signal_never_sees_entry_candle():
    closes = [100.0] * 10 + [101, 103, 106, 107]
    candles = make_candles(closes, spread=0.0)
    strategy = EveryNth({candles[9].open_time_ms})
    trades, still_open = run_backtest(strategy, {}, {"X": candles}, costs=Costs(0, 0))
    [t] = trades
    assert t.entry_time_ms == candles[10].open_time_ms
    assert t.entry_price == candles[10].open
    # todo candle visto pela estratégia já tinha fechado antes da abertura em que operou
    assert max(strategy.seen_last_close_times) < candles[-1].open_time_ms
    assert t.exit_reason == "take_profit"
    assert t.r_net == pytest.approx(2.0)


def test_costs_make_net_r_worse_than_gross():
    closes = [100.0] * 10 + [99, 97, 96]
    candles = make_candles(closes, spread=0.0)
    trades, _ = run_backtest(EveryNth({candles[9].open_time_ms}), {}, {"X": candles},
                             costs=Costs(fee_rate=0.001, slippage_rate=0.0005))
    [t] = trades
    assert t.exit_reason == "stop_loss"
    assert t.r_net < t.r_gross < -1 + 1e-9


def test_concurrency_limit_applies_across_symbols():
    candles = make_candles([100.0] * 10 + [100.5] * 5, spread=0.0)
    fire = {candles[9].open_time_ms}
    data = {s: candles for s in ("A", "B", "C")}
    trades, still_open = run_backtest(EveryNth(fire), {}, data, costs=Costs(0, 0),
                                      limits=Limits(max_open_positions=3, max_open_per_direction=2))
    assert len(trades) + len(still_open) == 2


def test_long_only_blocks_shorts():
    class Shorty(EveryNth):
        def generate(self, symbol, candles, htf, p):
            s = super().generate(symbol, candles, htf, p)
            return Signal(s.symbol, "short", s.entry, ExitPlan(s.entry * 1.02, s.entry * 0.96), "t", "x") if s else None
    candles = make_candles([100.0] * 15, spread=0.0)
    trades, still_open = run_backtest(Shorty({candles[9].open_time_ms}), {}, {"X": candles},
                                      limits=Limits(long_only=True))
    assert trades == [] and still_open == []


def _trade(r, t):
    return Trade("X", "long", t, t + 1, 100, 100, 99, "x", r, r)


def test_summary_and_split():
    trades = [_trade(2, 0), _trade(-1, 10), _trade(-1, 20), _trade(2, 30)]
    s = summarize(trades)
    assert s.trades == 4 and s.win_rate == 0.5
    assert s.avg_r_net == pytest.approx(0.5)
    assert s.profit_factor == pytest.approx(2.0)
    assert s.max_drawdown_r == pytest.approx(2.0)
    parts = split_by_period(trades, 0, 40, 2)
    assert [len(p) for p in parts] == [2, 2]


def test_bootstrap_separates_edge_from_noise():
    edge = [_trade(1.0 if i % 3 else -1.0, i) for i in range(300)]  # +0.33R médio, consistente
    noise = [_trade(1.0 if i % 2 else -1.0, i) for i in range(300)]  # média zero
    assert bootstrap_p_value(edge, n_sims=500) < 0.05
    assert bootstrap_p_value(noise, n_sims=500) > 0.3
