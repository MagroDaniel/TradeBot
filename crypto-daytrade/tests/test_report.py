import pytest

from backtest.engine import BacktestResult, ExecutionCosts
from backtest.report import build_report, net_r_multiple, r_multiple
from storage.signals_store import SignalRecord


def _closed_signal(direction, entry, stop_loss, close_price, status, closed_at) -> SignalRecord:
    return SignalRecord(
        symbol="TESTUSDT",
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        target=entry + 2 * (entry - stop_loss) if direction == "long" else entry - 2 * (stop_loss - entry),
        rsi_value=50.0,
        reason="teste",
        opened_at="2026-01-01T00:00:00+00:00",
        status=status,
        closed_at=closed_at,
        close_price=close_price,
    )


def test_r_multiple_for_long_target_and_stop():
    win = _closed_signal("long", 100.0, 90.0, 120.0, "target_hit", "t1")
    loss = _closed_signal("long", 100.0, 90.0, 90.0, "stop_hit", "t2")

    assert r_multiple(win) == pytest.approx(2.0)
    assert r_multiple(loss) == pytest.approx(-1.0)


def test_r_multiple_for_short_target_and_stop():
    win = _closed_signal("short", 100.0, 110.0, 80.0, "target_hit", "t1")
    loss = _closed_signal("short", 100.0, 110.0, 110.0, "stop_hit", "t2")

    assert r_multiple(win) == pytest.approx(2.0)
    assert r_multiple(loss) == pytest.approx(-1.0)


def test_net_r_multiple_subtracts_fees_from_gross_result():
    signal = _closed_signal("long", 100.0, 90.0, 120.0, "target_hit", "t1")

    # Notional negociado = 100 + 120; risco = 10; 0,1% por lado custa 0,022R.
    assert net_r_multiple(signal, ExecutionCosts(taker_fee_rate=0.001)) == pytest.approx(1.978)


def test_r_multiple_raises_for_still_open_signal():
    open_signal = SignalRecord(
        symbol="TESTUSDT", direction="long", entry=100.0, stop_loss=90.0, target=120.0,
        rsi_value=50.0, reason="teste", opened_at="2026-01-01T00:00:00+00:00",
    )
    with pytest.raises(ValueError):
        r_multiple(open_signal)


def test_build_report_computes_expectancy_profit_factor_and_drawdown():
    closed = [
        _closed_signal("long", 100.0, 90.0, 120.0, "target_hit", "t1"),   # R = +2
        _closed_signal("long", 100.0, 90.0, 90.0, "stop_hit", "t2"),      # R = -1
        _closed_signal("short", 100.0, 110.0, 80.0, "target_hit", "t3"),  # R = +2
        _closed_signal("short", 100.0, 110.0, 110.0, "stop_hit", "t4"),   # R = -1
    ]
    result = BacktestResult(variant_name="teste", closed=closed, still_open=[])

    report = build_report(result)

    assert report.wins == 2
    assert report.losses == 2
    assert report.win_rate == pytest.approx(0.5)
    assert report.expectancy_r == pytest.approx(0.5)  # média de [2, -1, 2, -1]
    assert report.gross_expectancy_r == pytest.approx(0.5)
    assert report.profit_factor == pytest.approx(2.0)  # 4 / |-2|
    assert report.max_drawdown_r == pytest.approx(1.0)


def test_build_report_handles_no_closed_signals():
    result = BacktestResult(variant_name="vazio", closed=[], still_open=[])

    report = build_report(result)

    assert report.win_rate == 0.0
    assert report.expectancy_r == 0.0
    assert report.profit_factor == 0.0
    assert report.max_drawdown_r == 0.0
