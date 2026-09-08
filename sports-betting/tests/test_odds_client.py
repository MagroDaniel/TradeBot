import pytest
import requests

from data.odds_client import OddsAPIClient


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_single_key_success(monkeypatch):
    captured = {}

    def _fake_get(url, params, timeout):
        captured["apiKey"] = params["apiKey"]
        return _FakeResponse(200, payload=[{"id": "e1"}])

    monkeypatch.setattr("data.odds_client.requests.get", _fake_get)

    client = OddsAPIClient(api_keys=["chave-1"])
    result = client.get_upcoming_odds("soccer_epl")

    assert result == [{"id": "e1"}]
    assert captured["apiKey"] == "chave-1"


def test_falls_back_to_next_key_when_first_is_exhausted(monkeypatch):
    calls = []

    def _fake_get(url, params, timeout):
        calls.append(params["apiKey"])
        if params["apiKey"] == "chave-1":
            return _FakeResponse(401, payload={"error_code": "OUT_OF_USAGE_CREDITS"})
        return _FakeResponse(200, payload=[{"id": "e1"}])

    monkeypatch.setattr("data.odds_client.requests.get", _fake_get)

    client = OddsAPIClient(api_keys=["chave-1", "chave-2"])
    result = client.get_upcoming_odds("soccer_epl")

    assert result == [{"id": "e1"}]
    assert calls == ["chave-1", "chave-2"]

    # a chamada seguinte já começa direto na chave-2 (não volta pra chave-1)
    client.get_upcoming_odds("soccer_epl")
    assert calls[-1] == "chave-2"


def test_raises_when_all_keys_exhausted(monkeypatch):
    def _fake_get(url, params, timeout):
        return _FakeResponse(401, payload={"error_code": "OUT_OF_USAGE_CREDITS"})

    monkeypatch.setattr("data.odds_client.requests.get", _fake_get)

    client = OddsAPIClient(api_keys=["chave-1", "chave-2"])
    with pytest.raises(requests.HTTPError):
        client.get_upcoming_odds("soccer_epl")


def test_empty_api_keys_raises():
    with pytest.raises(ValueError):
        OddsAPIClient(api_keys=[])


def test_get_event_odds_uses_event_endpoint(monkeypatch):
    captured = {}

    def _fake_get(url, params, timeout):
        captured["url"] = url
        captured["markets"] = params["markets"]
        return _FakeResponse(200, payload={"id": "e1", "bookmakers": []})

    monkeypatch.setattr("data.odds_client.requests.get", _fake_get)

    client = OddsAPIClient(api_keys=["chave-1"])
    client.get_event_odds("soccer_epl", "e1", "btts,double_chance")

    assert captured["url"].endswith("/sports/soccer_epl/events/e1/odds")
    assert captured["markets"] == "btts,double_chance"
