from alerts.telegram_notifier import TelegramNotifier
from analysis.performance import summarize
from storage.signals_store import SignalRecord


def _capture_sent_text(monkeypatch):
    sent = {}

    class _FakeResponse:
        ok = True
        text = ""

        def raise_for_status(self):
            pass

    def _fake_post(url, data, timeout):
        sent["text"] = data["text"]
        return _FakeResponse()

    monkeypatch.setattr("alerts.telegram_notifier.requests.post", _fake_post)
    return sent


def _signal(**overrides) -> SignalRecord:
    base = dict(
        symbol="BTCUSDT",
        direction="long",
        entry=100.0,
        stop_loss=95.0,
        target=110.0,
        rsi_value=45.0,
        reason="EMA9 cruzou acima da EMA21, RSI em 45 (não sobrecomprado)",
        opened_at="2026-09-08T10:00:00+00:00",
    )
    base.update(overrides)
    return SignalRecord(**base)


def test_signal_alert_never_mentions_leverage(monkeypatch):
    sent = _capture_sent_text(monkeypatch)

    TelegramNotifier("token", "chat").send_signal_alert(_signal())

    text_lower = sent["text"].lower()
    assert "alavancagem" not in text_lower or "nunca sugere alavancagem" in text_lower
    assert "leverage" not in text_lower


def test_signal_alert_shows_entry_stop_target(monkeypatch):
    sent = _capture_sent_text(monkeypatch)

    TelegramNotifier("token", "chat").send_signal_alert(_signal())

    assert "BTCUSDT" in sent["text"]
    assert "100" in sent["text"]
    assert "95" in sent["text"]
    assert "110" in sent["text"]


def test_long_signal_uses_green_icon(monkeypatch):
    sent = _capture_sent_text(monkeypatch)

    TelegramNotifier("token", "chat").send_signal_alert(_signal(direction="long"))

    assert "🟢" in sent["text"]


def test_short_signal_uses_red_icon(monkeypatch):
    sent = _capture_sent_text(monkeypatch)

    TelegramNotifier("token", "chat").send_signal_alert(_signal(direction="short"))

    assert "🔴" in sent["text"]


def test_result_target_hit_uses_check_icon(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    signal = _signal(status="target_hit", close_price=110.0)

    TelegramNotifier("token", "chat").send_result(signal)

    assert "✅" in sent["text"]
    assert "Alvo atingido" in sent["text"]


def test_result_stop_hit_uses_cross_icon(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    signal = _signal(status="stop_hit", close_price=95.0)

    TelegramNotifier("token", "chat").send_result(signal)

    assert "❌" in sent["text"]
    assert "Stop atingido" in sent["text"]


def test_daily_report_with_no_records(monkeypatch):
    sent = _capture_sent_text(monkeypatch)

    TelegramNotifier("token", "chat").send_daily_report("2026-09-08", summarize([]), [])

    assert "Nenhum sinal resolvido" in sent["text"]


def test_daily_report_lists_every_record_win_and_loss(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    records = [
        _signal(symbol="BTCUSDT", status="target_hit", close_price=110.0),
        _signal(symbol="ETHUSDT", status="stop_hit", close_price=95.0),
        _signal(symbol="SOLUSDT", status="expired", close_price=101.0),
    ]

    TelegramNotifier("token", "chat").send_daily_report("2026-09-08", summarize(records), records)

    text = sent["text"]
    assert "BTCUSDT" in text and "✅" in text
    assert "ETHUSDT" in text and "❌" in text
    assert "SOLUSDT" in text and "⌛" in text
    assert "1✅" in text
    assert "1❌" in text
    assert "1⌛" in text


def test_weekly_report_with_no_records(monkeypatch):
    sent = _capture_sent_text(monkeypatch)

    TelegramNotifier("token", "chat").send_weekly_report(
        "2026-09-01", "2026-09-07", summarize([]), []
    )

    assert "Relatório semanal" in sent["text"]
    assert "2026-09-01" in sent["text"] and "2026-09-07" in sent["text"]
    assert "Nenhum sinal resolvido" in sent["text"]


def test_weekly_report_lists_every_record(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    records = [
        _signal(symbol="BTCUSDT", status="target_hit", close_price=110.0),
        _signal(symbol="ETHUSDT", status="stop_hit", close_price=95.0),
    ]

    TelegramNotifier("token", "chat").send_weekly_report(
        "2026-09-01", "2026-09-07", summarize(records), records
    )

    text = sent["text"]
    assert "BTCUSDT" in text and "✅" in text
    assert "ETHUSDT" in text and "❌" in text


def test_monthly_report_with_no_records(monkeypatch):
    sent = _capture_sent_text(monkeypatch)

    TelegramNotifier("token", "chat").send_monthly_report("2026-08", summarize([]), [])

    assert "Relatório mensal" in sent["text"]
    assert "2026-08" in sent["text"]
    assert "Nenhum sinal resolvido" in sent["text"]


def test_monthly_report_lists_every_record(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    records = [_signal(symbol="SOLUSDT", status="expired", close_price=101.0)]

    TelegramNotifier("token", "chat").send_monthly_report("2026-08", summarize(records), records)

    text = sent["text"]
    assert "SOLUSDT" in text and "⌛" in text
