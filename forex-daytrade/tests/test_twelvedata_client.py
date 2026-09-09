from datetime import datetime, timezone

from data.twelvedata_client import Candle, TwelveDataClient, TwelveDataError, closed_candles


class _FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self.ok = status_code < 400
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _value(dt: str, o: str, h: str, l: str, c: str) -> dict:
    return {"datetime": dt, "open": o, "high": h, "low": l, "close": c}


def test_get_candles_parses_and_computes_close_time(monkeypatch):
    payload = {
        "meta": {"symbol": "EUR/USD", "interval": "1h"},
        "values": [_value("2026-09-10 07:00:00", "1.16331", "1.16372", "1.16312", "1.16357")],
        "status": "ok",
    }
    monkeypatch.setattr(
        "data.twelvedata_client.requests.get",
        lambda url, params, timeout: _FakeResponse(200, payload),
    )

    candles = TwelveDataClient(api_key="fake").get_candles("EUR/USD", interval="1h", outputsize=1)

    assert len(candles) == 1
    c = candles[0]
    expected_open_ms = int(datetime(2026, 9, 10, 7, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert c.open_time_ms == expected_open_ms
    assert c.open == 1.16331
    assert c.high == 1.16372
    assert c.low == 1.16312
    assert c.close == 1.16357
    assert c.volume == 0.0  # forex não tem volume real — payload sem essa chave
    assert c.close_time_ms == expected_open_ms + 60 * 60_000  # +1h


def test_get_candles_sorts_ascending_even_if_api_returns_descending(monkeypatch):
    payload = {
        "values": [
            _value("2026-09-10 09:00:00", "1", "1", "1", "1"),
            _value("2026-09-10 08:00:00", "1", "1", "1", "1"),
            _value("2026-09-10 07:00:00", "1", "1", "1", "1"),
        ],
        "status": "ok",
    }
    monkeypatch.setattr(
        "data.twelvedata_client.requests.get",
        lambda url, params, timeout: _FakeResponse(200, payload),
    )

    candles = TwelveDataClient(api_key="fake").get_candles("EUR/USD", interval="1h")

    assert [c.open_time_ms for c in candles] == sorted(c.open_time_ms for c in candles)


def test_get_candles_raises_on_error_status(monkeypatch):
    payload = {"status": "error", "message": "chave inválida"}
    monkeypatch.setattr(
        "data.twelvedata_client.requests.get",
        lambda url, params, timeout: _FakeResponse(200, payload),
    )

    try:
        TwelveDataClient(api_key="fake").get_candles("EUR/USD")
        assert False, "deveria ter levantado TwelveDataError"
    except TwelveDataError:
        pass


def test_get_historical_candles_stops_when_page_is_short(monkeypatch):
    payload = {"values": [_value("2026-01-01 00:00:00", "1", "1", "1", "1")], "status": "ok"}
    monkeypatch.setattr(
        "data.twelvedata_client.requests.get",
        lambda url, params, timeout: _FakeResponse(200, payload),
    )

    start_ms = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)
    candles = TwelveDataClient(api_key="fake").get_historical_candles("EUR/USD", "1h", start_ms, end_ms)

    assert len(candles) == 1


def test_get_historical_candles_pages_until_a_short_page(monkeypatch):
    # página cheia = 5000 candles (o `page_size` real usado por get_historical_candles) ->
    # precisa pedir mais uma página; a segunda, com só 1 candle, é a última.
    calls = []

    def _full_page_values():
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return [
            _value(
                datetime.fromtimestamp(base.timestamp() + i * 3600, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "1", "1", "1", "1",
            )
            for i in range(5000)
        ]

    full_page = _full_page_values()

    def fake_get(url, params, timeout):
        calls.append(params["start_date"])
        if len(calls) == 1:
            return _FakeResponse(200, {"values": full_page, "status": "ok"})
        return _FakeResponse(
            200, {"values": [_value("2026-08-01 00:00:00", "1", "1", "1", "1")], "status": "ok"}
        )

    monkeypatch.setattr("data.twelvedata_client.requests.get", fake_get)
    monkeypatch.setattr("data.twelvedata_client.time.sleep", lambda seconds: None)

    start_ms = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    candles = TwelveDataClient(api_key="fake").get_historical_candles("EUR/USD", "1h", start_ms, end_ms)

    assert len(calls) == 2
    assert len(candles) == 5001


def test_get_historical_candles_stops_on_empty_page(monkeypatch):
    monkeypatch.setattr(
        "data.twelvedata_client.requests.get",
        lambda url, params, timeout: _FakeResponse(200, {"values": [], "status": "ok"}),
    )

    start_ms = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)
    candles = TwelveDataClient(api_key="fake").get_historical_candles("EUR/USD", "1h", start_ms, end_ms)

    assert candles == []


def test_get_current_price_returns_none_on_error(monkeypatch):
    monkeypatch.setattr(
        "data.twelvedata_client.requests.get",
        lambda url, params, timeout: _FakeResponse(400, {}),
    )

    assert TwelveDataClient(api_key="fake").get_current_price("EUR/USD") is None


def test_get_current_price_returns_value_on_success(monkeypatch):
    monkeypatch.setattr(
        "data.twelvedata_client.requests.get",
        lambda url, params, timeout: _FakeResponse(200, {"price": "1.16357"}),
    )

    assert TwelveDataClient(api_key="fake").get_current_price("EUR/USD") == 1.16357


def test_closed_candles_excludes_the_candle_still_in_formation():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    finished = Candle(0, 1, 1, 1, 1, 0.0, close_time_ms=now_ms - 1)
    open_now = Candle(1, 1, 1, 1, 1, 0.0, close_time_ms=now_ms + 1)

    assert closed_candles([finished, open_now], now=now) == [finished]
