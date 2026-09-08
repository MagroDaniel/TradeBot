from analysis.performance import summarize
from storage.signals_store import SignalRecord


def _record(status, **overrides) -> SignalRecord:
    base = dict(
        symbol="BTCUSDT",
        direction="long",
        entry=100.0,
        stop_loss=95.0,
        target=110.0,
        rsi_value=45.0,
        reason="teste",
        opened_at="2026-09-08T10:00:00+00:00",
        status=status,
    )
    base.update(overrides)
    return SignalRecord(**base)


def test_empty_history():
    summary = summarize([])

    assert summary.total_signals == 0
    assert summary.resolved == 0
    assert summary.win_rate == 0.0


def test_counts_wins_losses_and_expired_separately():
    records = [
        _record("target_hit"),
        _record("target_hit"),
        _record("stop_hit"),
        _record("expired"),
        _record("open"),
    ]

    summary = summarize(records)

    assert summary.total_signals == 5
    assert summary.resolved == 4  # tudo menos o "open"
    assert summary.wins == 2
    assert summary.losses == 1
    assert summary.expired == 1


def test_win_rate_excludes_expired_from_denominator():
    records = [_record("target_hit"), _record("target_hit"), _record("stop_hit"), _record("expired")]

    summary = summarize(records)

    # 2 vitórias em 3 decisivos (2 alvo + 1 stop) — o expirado não conta pro cálculo
    assert summary.win_rate == 2 / 3


def test_win_rate_is_zero_when_only_open_or_expired():
    records = [_record("open"), _record("expired")]

    summary = summarize(records)

    assert summary.win_rate == 0.0
