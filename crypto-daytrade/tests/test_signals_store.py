from storage.signals_store import SignalRecord, SignalsStore


def _record(symbol="BTCUSDT", opened_at="2026-09-08T10:00:00+00:00", **overrides) -> SignalRecord:
    base = dict(
        symbol=symbol,
        direction="long",
        entry=100.0,
        stop_loss=95.0,
        target=110.0,
        rsi_value=45.0,
        reason="teste",
        opened_at=opened_at,
    )
    base.update(overrides)
    return SignalRecord(**base)


def test_new_store_has_no_signals(tmp_path):
    store = SignalsStore(tmp_path / "signals.json")

    assert store.all_signals() == []
    assert store.open_signals() == []


def test_add_and_retrieve(tmp_path):
    store = SignalsStore(tmp_path / "signals.json")

    store.add(_record())

    assert len(store.all_signals()) == 1
    assert store.open_signals()[0].symbol == "BTCUSDT"


def test_has_open_signal_for(tmp_path):
    store = SignalsStore(tmp_path / "signals.json")
    store.add(_record(symbol="ETHUSDT"))

    assert store.has_open_signal_for("ETHUSDT")
    assert not store.has_open_signal_for("BTCUSDT")


def test_update_changes_status_and_keeps_others_untouched(tmp_path):
    store = SignalsStore(tmp_path / "signals.json")
    store.add(_record(symbol="BTCUSDT", opened_at="2026-09-08T10:00:00+00:00"))
    store.add(_record(symbol="ETHUSDT", opened_at="2026-09-08T11:00:00+00:00"))

    resolved = store.open_signals()[0]
    resolved.status = "target_hit"
    resolved.close_price = 110.0
    store.update([resolved])

    all_signals = store.all_signals()
    statuses = {s.symbol: s.status for s in all_signals}
    assert statuses["BTCUSDT"] == "target_hit"
    assert statuses["ETHUSDT"] == "open"
    assert not store.has_open_signal_for("BTCUSDT")
    assert store.has_open_signal_for("ETHUSDT")


def test_persists_across_new_instances(tmp_path):
    path = tmp_path / "signals.json"
    SignalsStore(path).add(_record())

    reloaded = SignalsStore(path)

    assert len(reloaded.all_signals()) == 1
