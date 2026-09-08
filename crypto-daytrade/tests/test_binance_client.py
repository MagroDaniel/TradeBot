from data.binance_client import BinanceClient


class _FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_parses_ticker_from_title(monkeypatch):
    payload = {
        "data": {
            "articles": [
                {"id": 283840, "title": "Binance Will List MarsCoin (MARSCOIN) with Seed Tag Applied"},
                {"id": 283773, "title": "Binance Futures Will Launch Multiple TradFi Perpetual Contracts"},
            ]
        }
    }
    monkeypatch.setattr(
        "data.binance_client.requests.get", lambda url, params, timeout: _FakeResponse(200, payload)
    )

    announcements = BinanceClient().get_new_listing_announcements(catalog_id="48")

    assert len(announcements) == 2
    assert announcements[0].article_id == 283840
    assert announcements[0].ticker == "MARSCOIN"
    assert announcements[1].ticker is None  # título sem parênteses de ticker


def test_find_trading_usdt_pair_returns_symbol_when_trading(monkeypatch):
    payload = {"symbols": [{"symbol": "FOOUSDT", "status": "TRADING"}]}
    monkeypatch.setattr(
        "data.binance_client.requests.get", lambda url, params, timeout: _FakeResponse(200, payload)
    )

    symbol = BinanceClient().find_trading_usdt_pair("FOO")

    assert symbol == "FOOUSDT"


def test_find_trading_usdt_pair_returns_none_when_not_trading(monkeypatch):
    payload = {"symbols": [{"symbol": "FOOUSDT", "status": "BREAK"}]}
    monkeypatch.setattr(
        "data.binance_client.requests.get", lambda url, params, timeout: _FakeResponse(200, payload)
    )

    assert BinanceClient().find_trading_usdt_pair("FOO") is None


def test_find_trading_usdt_pair_returns_none_when_symbol_does_not_exist(monkeypatch):
    monkeypatch.setattr(
        "data.binance_client.requests.get",
        lambda url, params, timeout: _FakeResponse(400, {"code": -1121, "msg": "Invalid symbol."}),
    )

    assert BinanceClient().find_trading_usdt_pair("NAOEXISTE") is None


def test_get_24hr_ticker_returns_none_on_error(monkeypatch):
    monkeypatch.setattr(
        "data.binance_client.requests.get", lambda url, params, timeout: _FakeResponse(400, {})
    )

    assert BinanceClient().get_24hr_ticker("FOOUSDT") is None


def test_get_24hr_ticker_returns_payload_on_success(monkeypatch):
    payload = {"priceChangePercent": "10.0", "quoteVolume": "500"}
    monkeypatch.setattr(
        "data.binance_client.requests.get", lambda url, params, timeout: _FakeResponse(200, payload)
    )

    assert BinanceClient().get_24hr_ticker("FOOUSDT") == payload
