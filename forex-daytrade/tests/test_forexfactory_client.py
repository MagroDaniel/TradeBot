from datetime import datetime, timezone

from data.forexfactory_client import EconomicEvent, ForexFactoryClient


class _FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _raw_event(**overrides) -> dict:
    base = {
        "title": "Non-Farm Payrolls",
        "country": "USD",
        "date": "2026-09-11T12:30:00+00:00",
        "impact": "High",
        "forecast": "180K",
        "previous": "150K",
        "actual": "",
    }
    base.update(overrides)
    return base


def test_get_week_events_parses_all_fields(monkeypatch):
    payload = [_raw_event()]
    monkeypatch.setattr(
        "data.forexfactory_client.requests.get", lambda url, timeout: _FakeResponse(200, payload)
    )

    events = ForexFactoryClient().get_week_events()

    assert len(events) == 1
    e = events[0]
    assert e.title == "Non-Farm Payrolls"
    assert e.country == "USD"
    assert e.impact == "High"
    assert e.forecast == "180K"
    assert e.previous == "150K"
    assert e.actual is None  # string vazia vira None


def test_get_relevant_high_impact_events_filters_by_currency_and_impact(monkeypatch):
    payload = [
        _raw_event(country="USD", impact="High"),
        _raw_event(country="JPY", impact="High", title="Tankan Index"),  # moeda não coberta
        _raw_event(country="EUR", impact="Low", title="Trade Balance"),  # impacto baixo
        _raw_event(country="GBP", impact="High", title="GDP"),
    ]
    monkeypatch.setattr(
        "data.forexfactory_client.requests.get", lambda url, timeout: _FakeResponse(200, payload)
    )

    events = ForexFactoryClient().get_relevant_high_impact_events()

    titles = {e.title for e in events}
    assert titles == {"Non-Farm Payrolls", "GDP"}


def test_economic_event_datetime_utc_parses_iso_date():
    event = EconomicEvent(
        title="t", country="USD", date="2026-09-11T12:30:00+00:00",
        impact="High", forecast="1", previous="1", actual=None,
    )

    assert event.datetime_utc == datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc)


def test_economic_event_datetime_utc_returns_none_for_malformed_date():
    event = EconomicEvent(
        title="t", country="USD", date="not-a-date",
        impact="High", forecast="1", previous="1", actual=None,
    )

    assert event.datetime_utc is None


def test_has_surprise_requires_both_actual_and_forecast():
    with_both = EconomicEvent(
        title="t", country="USD", date="2026-09-11T12:30:00+00:00",
        impact="High", forecast="180K", previous="150K", actual="200K",
    )
    no_actual_yet = EconomicEvent(
        title="t", country="USD", date="2026-09-11T12:30:00+00:00",
        impact="High", forecast="180K", previous="150K", actual=None,
    )
    no_forecast = EconomicEvent(
        title="t", country="USD", date="2026-09-11T12:30:00+00:00",
        impact="High", forecast=None, previous="150K", actual="200K",
    )

    assert with_both.has_surprise() is True
    assert no_actual_yet.has_surprise() is False
    assert no_forecast.has_surprise() is False
