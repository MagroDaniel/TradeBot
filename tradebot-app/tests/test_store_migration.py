import json
import sqlite3

from tradebot.engine import Engine
from tradebot.store import Store
from tests.helpers import FakeMarketData

V1_SCHEMA = """
CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE wallets (account TEXT NOT NULL, market TEXT NOT NULL, cash REAL NOT NULL, initial REAL NOT NULL,
    reset_at_ms INTEGER NOT NULL, PRIMARY KEY (account, market));
CREATE TABLE positions (id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, market TEXT NOT NULL,
    symbol TEXT NOT NULL, direction TEXT NOT NULL, qty REAL NOT NULL, entry_price REAL NOT NULL, stop_loss REAL NOT NULL,
    initial_stop REAL NOT NULL, take_profit REAL, time_limit_minutes INTEGER, trailing_activation REAL,
    trailing_distance REAL, best_price REAL, opened_at_ms INTEGER NOT NULL, strategy TEXT NOT NULL, reason TEXT NOT NULL,
    entry_fee REAL NOT NULL DEFAULT 0, status TEXT NOT NULL, exit_price REAL, exit_fee REAL NOT NULL DEFAULT 0,
    exit_reason TEXT, closed_at_ms INTEGER, extra TEXT NOT NULL DEFAULT '{}');
CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts_ms INTEGER NOT NULL, level TEXT NOT NULL,
    kind TEXT NOT NULL, market TEXT, symbol TEXT, message TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}');
CREATE TABLE equity (ts_ms INTEGER NOT NULL, account TEXT NOT NULL, market TEXT NOT NULL, equity REAL NOT NULL);
"""


def test_v1_database_becomes_bot_1(tmp_path):
    path = tmp_path / "tradebot.db"
    conn = sqlite3.connect(path)
    conn.executescript(V1_SCHEMA)
    conn.execute("INSERT INTO wallets VALUES ('paper', 'futures', 812.5, 1000, 0)")
    conn.execute("INSERT INTO positions (account, market, symbol, direction, qty, entry_price, stop_loss, initial_stop, "
                 "opened_at_ms, strategy, reason, status) VALUES ('paper', 'futures', 'BTCUSDT', 'long', 1, 100, 98, 98, "
                 "0, 'ema_cross', 'x', 'open')")
    conn.execute("INSERT INTO kv VALUES ('settings', ?)", (json.dumps({"strategy": "ema_cross",
                 "strategy_params": {"ema_cross": {"atr_stop": 2.5}}, "risk": {"risk_per_trade_pct": 0.7}}),))
    conn.execute("INSERT INTO kv VALUES ('engine_state', '\"paused\"')")
    conn.commit()
    conn.close()

    store = Store(path)
    engine = Engine(store, tmp_path, market_data={"spot": FakeMarketData("spot"), "futures": FakeMarketData("futures")})
    bot = engine.bots[1]
    assert bot.state == "paused"
    assert bot.config.params()["atr_stop"] == 2.5
    assert bot.config.risk.risk_per_trade_pct == 0.7
    assert bot.brokers["futures"].cash() == 812.5
    assert [p.symbol for p in store.open_positions("paper", 1)] == ["BTCUSDT"]
