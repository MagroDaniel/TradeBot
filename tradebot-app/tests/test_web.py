import pytest
from fastapi.testclient import TestClient

from tests.helpers import FakeMarketData
from tradebot.engine import Engine
from tradebot.store import Store
from tradebot.web.server import create_app

TOKEN = "segredo-de-teste"


@pytest.fixture
def client(tmp_path):
    store = Store(":memory:")
    md = {"spot": FakeMarketData("spot"), "futures": FakeMarketData("futures")}
    engine = Engine(store, tmp_path, market_data=md)
    app = create_app(engine, TOKEN)
    c = TestClient(app)
    c.engine = engine
    return c


def _login(client):
    r = client.get(f"/?token={TOKEN}", follow_redirects=False)
    assert r.status_code == 303
    client.cookies.set("tradebot_token", TOKEN)


def test_requires_token(client):
    assert client.get("/").status_code == 401
    assert client.post("/api/start").status_code == 401
    assert client.get("/?token=errado").status_code == 401
    assert client.get("/health").status_code == 200


def test_token_sets_strict_cookie(client):
    r = client.get(f"/?token={TOKEN}", follow_redirects=False)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_pages_render(client):
    _login(client)
    for path in ("/", "/partials/status", "/partials/positions", "/partials/trades", "/partials/events", "/settings"):
        r = client.get(path)
        assert r.status_code == 200, path
    assert "Desligado" in client.get("/partials/status").text


def test_commands_change_state(client):
    _login(client)
    r = client.post("/api/start")
    assert r.status_code == 204 and "refresh" in r.headers["HX-Trigger"]
    assert client.engine.state == "running"
    client.post("/api/pause")
    assert client.engine.state == "paused"
    client.post("/api/emergency")
    assert "Kill switch" in client.get("/partials/status").text
    client.post("/api/release-halt")
    assert "Kill switch" not in client.get("/partials/status").text


def test_settings_form_saves_and_validates(client):
    _login(client)
    form = {
        "futures_enabled": "on", "futures_initial_balance": "500", "futures_fee_pct": "0.05",
        "spot_initial_balance": "1000", "spot_fee_pct": "0.1",
        "top_symbols": "10", "symbols": "", "poll_seconds": "15",
        "risk_per_trade_pct": "0.5", "max_position_pct": "20", "max_open_positions": "2",
        "max_open_per_direction": "1", "max_trades_per_day": "5", "max_slippage_pct": "0.3",
        "strategy": "donchian_breakout", "param_donchian_breakout_entry_channel": "55",
        "param_donchian_breakout_timeframe": "1h",
    }
    r = client.post("/settings", data=form, follow_redirects=False)
    assert r.status_code == 303 and "saved=1" in r.headers["location"]
    s = client.engine.settings
    assert s.strategy == "donchian_breakout"
    assert s.params_for()["entry_channel"] == 55
    assert not s.markets["spot"].enabled
    assert s.risk.risk_per_trade_pct == 0.5
    assert s.markets["futures"].fee_rate == pytest.approx(0.0005)

    bad = dict(form, risk_per_trade_pct="40")
    r = client.post("/settings", data=bad, follow_redirects=False)
    assert "error=" in r.headers["location"]
    assert client.engine.settings.risk.risk_per_trade_pct == 0.5  # não aplicou o inválido


def test_wallet_reset_blocked_with_open_position_message(client):
    _login(client)
    r = client.post("/api/wallet/futures/reset")
    assert r.status_code == 204
    assert client.post("/api/wallet/nada/reset").status_code == 404
