from alerts.telegram_notifier import TelegramNotifier
from analysis.scoring import Assessment


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


def test_high_risk_alert_uses_warning_icon(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    assessment = Assessment(risk_tags=["Seed Tag"], price_change_percent=None, quote_volume=None)

    TelegramNotifier("token", "chat").send_listing_alert(
        "Binance Will List FooCoin (FOO) with Seed Tag Applied", "FOO", assessment
    )

    assert "🚨" in sent["text"]
    assert "FOO" in sent["text"]
    assert "Seed Tag" in sent["text"]


def test_low_risk_alert_uses_new_icon(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    assessment = Assessment(risk_tags=[], price_change_percent=5.0, quote_volume=1000.0)

    TelegramNotifier("token", "chat").send_listing_alert(
        "Binance Will Add FooCoin (FOO)", "FOO", assessment
    )

    assert "🆕" in sent["text"]


def test_message_always_includes_disclaimer(monkeypatch):
    sent = _capture_sent_text(monkeypatch)
    assessment = Assessment(risk_tags=[], price_change_percent=None, quote_volume=None)

    TelegramNotifier("token", "chat").send_listing_alert("Título qualquer", "FOO", assessment)

    assert "NÃO é uma previsão" in sent["text"]
