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


def test_last_report_date_is_none_by_default(tmp_path):
    store = SignalsStore(tmp_path / "signals.json")

    assert store.get_last_report_date() is None


def test_set_and_get_last_report_date(tmp_path):
    store = SignalsStore(tmp_path / "signals.json")

    store.set_last_report_date("2026-09-08")

    assert store.get_last_report_date() == "2026-09-08"


def test_set_last_report_date_does_not_lose_signals(tmp_path):
    store = SignalsStore(tmp_path / "signals.json")
    store.add(_record())

    store.set_last_report_date("2026-09-08")

    assert len(store.all_signals()) == 1


def test_get_last_report_date_on_file_without_that_key(tmp_path):
    # simula um signals.json salvo antes dessa funcionalidade existir
    path = tmp_path / "signals.json"
    path.write_text('{"signals": []}', encoding="utf-8")

    store = SignalsStore(path)

    assert store.get_last_report_date() is None


def test_last_weekly_report_date_is_none_by_default(tmp_path):
    store = SignalsStore(tmp_path / "signals.json")

    assert store.get_last_weekly_report_date() is None


def test_set_and_get_last_weekly_report_date(tmp_path):
    store = SignalsStore(tmp_path / "signals.json")

    store.set_last_weekly_report_date("2026-09-14")

    assert store.get_last_weekly_report_date() == "2026-09-14"


def test_last_monthly_report_date_is_none_by_default(tmp_path):
    store = SignalsStore(tmp_path / "signals.json")

    assert store.get_last_monthly_report_date() is None


def test_set_and_get_last_monthly_report_date(tmp_path):
    store = SignalsStore(tmp_path / "signals.json")

    store.set_last_monthly_report_date("2026-10-01")

    assert store.get_last_monthly_report_date() == "2026-10-01"


def test_has_seen_news_event_is_false_by_default(tmp_path):
    store = SignalsStore(tmp_path / "signals.json")

    assert not store.has_seen_news_event("USD|Non-Farm Payrolls|2026-09-11T12:30:00+00:00|EUR/USD")


def test_mark_and_check_seen_news_event(tmp_path):
    store = SignalsStore(tmp_path / "signals.json")
    key = "USD|Non-Farm Payrolls|2026-09-11T12:30:00+00:00|EUR/USD"

    store.mark_news_event_seen(key)

    assert store.has_seen_news_event(key)
    assert not store.has_seen_news_event("outra chave qualquer")


def test_mark_news_event_seen_is_idempotent(tmp_path):
    store = SignalsStore(tmp_path / "signals.json")
    key = "USD|Non-Farm Payrolls|2026-09-11T12:30:00+00:00|EUR/USD"

    store.mark_news_event_seen(key)
    store.mark_news_event_seen(key)

    data = store._read()
    assert data["seen_news_events"].count(key) == 1


def test_persists_across_new_instances(tmp_path):
    path = tmp_path / "signals.json"
    SignalsStore(path).add(_record())

    reloaded = SignalsStore(path)

    assert len(reloaded.all_signals()) == 1
