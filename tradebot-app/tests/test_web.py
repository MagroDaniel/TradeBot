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
    c = TestClient(create_app(engine, TOKEN))
    c.engine = engine
    return c


def _login(client):
    r = client.get(f"/?token={TOKEN}", follow_redirects=False)
    assert r.status_code == 303
    client.cookies.set("tradebot_token", TOKEN)


def test_requires_token(client):
    assert client.get("/").status_code == 401
    assert client.post("/api/bots/1/start").status_code == 401
    assert client.get("/?token=errado").status_code == 401
    assert client.get("/health").status_code == 200


def test_token_sets_strict_cookie(client):
    r = client.get(f"/?token={TOKEN}", follow_redirects=False)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_first_run_creates_default_bot_and_pages_render(client):
    _login(client)
    assert list(client.engine.bots) == [1]
    for path in ("/", "/partials/overview", "/bots/1", "/bots/1/partials/status", "/bots/1/partials/positions",
                 "/bots/1/partials/trades", "/bots/1/partials/events", "/bots/1/settings", "/bots/new", "/settings",
                 "/api/equity/overview", "/api/bots/1/equity"):
        assert client.get(path).status_code == 200, path
    assert client.get("/bots/99").status_code == 404
    assert "EMA 9/21" in client.get("/").text  # aba do robô na navegação


def test_create_bot_with_other_strategy_and_compare(client):
    _login(client)
    r = client.post("/bots", data={"name": "Donchian 1h", "strategy": "donchian_breakout", "copy_from": "1"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/bots/2/settings?created=1"
    bot = client.engine.bots[2]
    assert bot.config.strategy == "donchian_breakout" and bot.state == "stopped"
    assert bot.config.params()["timeframe"] == "1h"
    overview = client.get("/partials/overview").text
    assert "Donchian 1h" in overview and "em teste" in overview
    assert "Donchian 1h" in client.get("/").text


def test_commands_are_per_bot(client):
    _login(client)
    client.post("/bots", data={"name": "B2", "strategy": "supertrend"})
    r = client.post("/api/bots/2/start")
    assert r.status_code == 204 and "refresh" in r.headers["HX-Trigger"]
    assert client.engine.bots[2].state == "running"
    assert client.engine.bots[1].state == "stopped"
    client.post("/api/bots/2/pause")
    assert client.engine.bots[2].state == "paused"
    assert client.post("/api/bots/9/start").status_code == 404


def test_emergency_and_halt_are_global(client):
    _login(client)
    client.post("/api/emergency")
    assert "Kill switch" in client.get("/partials/overview").text
    assert "Kill switch" in client.get("/bots/1/partials/status").text
    client.post("/api/release-halt")
    assert "Kill switch" not in client.get("/partials/overview").text


def test_bot_settings_form_saves_and_validates(client):
    _login(client)
    form = {
        "name": "Produção", "futures_enabled": "on", "futures_initial_balance": "500", "futures_fee_pct": "0.05",
        "spot_initial_balance": "1000", "spot_fee_pct": "0.1",
        "top_symbols": "10", "symbols": "",
        "risk_per_trade_pct": "0.5", "max_position_pct": "20", "max_open_positions": "2",
        "max_open_per_direction": "1", "max_trades_per_day": "5", "max_slippage_pct": "0.3",
        "param_atr_stop": "2", "param_timeframe": "15m", "param_trailing_atr": "1.5",
    }
    r = client.post("/bots/1/settings", data=form, follow_redirects=False)
    assert r.status_code == 303 and "saved=1" in r.headers["location"]
    bot = client.engine.bots[1]
    assert bot.name == "Produção"
    assert bot.config.params()["atr_stop"] == 2 and bot.config.params()["trailing_atr"] == 1.5
    assert not bot.config.markets["spot"].enabled
    assert bot.config.risk.risk_per_trade_pct == 0.5
    assert bot.config.markets["futures"].fee_rate == pytest.approx(0.0005)

    r = client.post("/bots/1/settings", data=dict(form, risk_per_trade_pct="40"), follow_redirects=False)
    assert "error=" in r.headers["location"]
    assert client.engine.bots[1].config.risk.risk_per_trade_pct == 0.5  # não aplicou o inválido


def test_delete_bot_via_panel(client):
    _login(client)
    client.post("/bots", data={"name": "B2", "strategy": "supertrend"})
    r = client.post("/bots/2/delete", follow_redirects=False)
    assert r.headers["location"] == "/"
    assert 2 not in client.engine.bots
    r = client.post("/bots/1/delete", follow_redirects=False)
    assert "error=" in r.headers["location"]  # não apaga o último robô


def test_app_settings(client):
    _login(client)
    client.post("/settings", data={"poll_seconds": "20"})
    assert client.engine.app_settings.poll_seconds == 20
    r = client.post("/settings", data={"poll_seconds": "1"}, follow_redirects=False)
    assert "error=" in r.headers["location"]


def test_wallet_reset_routes(client):
    _login(client)
    assert client.post("/api/bots/1/wallet/futures/reset").status_code == 204
    assert client.post("/api/bots/1/wallet/nada/reset").status_code == 404
