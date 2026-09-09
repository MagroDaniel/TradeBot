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
        symbol="EUR/USD",
        direction="long",
        entry=1.1000,
        stop_loss=1.0950,
        target=1.1100,
        rsi_value=45.0,
        reason="EMA9 cruzou acima da EMA21, RSI em 45 (não sobrecomprado)",
        opened_at="2026-09-08T10:00:00+00:00",
        market_mode="forex",
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

    assert "EUR/USD" in sent["text"]
    assert "1.10000" in sent["text"]
    assert "1.09500" in sent["text"]
    assert "1.11000" in sent["text"]


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
    signal = _signal(status="target_hit", close_price=1.1100)

    TelegramNotifier("token", "chat").send_result(signal)

    assert "✅" in sent["text"]
    assert "Alvo atingido" in sent["text"]


def test_result_stop_hit_uses_cross_icon(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    signal = _signal(status="stop_hit", close_price=1.0950)

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
        _signal(symbol="EUR/USD", status="target_hit", close_price=1.1100),
        _signal(symbol="GBP/USD", status="stop_hit", close_price=1.0950),
        _signal(symbol="USD/JPY", status="expired", close_price=1.1000),
    ]

    TelegramNotifier("token", "chat").send_daily_report("2026-09-08", summarize(records), records)

    text = sent["text"]
    assert "EUR/USD" in text and "✅" in text
    assert "GBP/USD" in text and "❌" in text
    assert "USD/JPY" in text and "⌛" in text
    assert "1✅" in text
    assert "1❌" in text
    assert "1⌛" in text
