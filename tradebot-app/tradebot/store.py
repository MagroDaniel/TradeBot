"""Persistência em SQLite — robôs, posições, carteiras demo, eventos (auditoria) e patrimônio.

Substitui o `signals.json` do crypto-daytrade: aqui há escrita concorrente (motor numa
thread, painel em outra) e consultas (P&L do dia, últimos N eventos), o que JSON não aguenta
bem. Tudo é separado por `account` (paper | demo | live) E por `bot_id` — cada robô tem
carteira, posições e histórico próprios, e uma posição de teste nunca se mistura com uma real.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from tradebot.models import Position

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bots (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, config TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'stopped', created_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS wallets (
    account TEXT NOT NULL, bot_id INTEGER NOT NULL, market TEXT NOT NULL, cash REAL NOT NULL,
    initial REAL NOT NULL, reset_at_ms INTEGER NOT NULL, PRIMARY KEY (account, bot_id, market)
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL, bot_id INTEGER NOT NULL DEFAULT 1, market TEXT NOT NULL, symbol TEXT NOT NULL,
    direction TEXT NOT NULL, qty REAL NOT NULL, entry_price REAL NOT NULL, stop_loss REAL NOT NULL,
    initial_stop REAL NOT NULL, take_profit REAL, time_limit_minutes INTEGER, trailing_activation REAL,
    trailing_distance REAL, best_price REAL, opened_at_ms INTEGER NOT NULL, strategy TEXT NOT NULL,
    reason TEXT NOT NULL, entry_fee REAL NOT NULL DEFAULT 0, status TEXT NOT NULL, exit_price REAL,
    exit_fee REAL NOT NULL DEFAULT 0, exit_reason TEXT, closed_at_ms INTEGER, extra TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions (account, bot_id, status);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts_ms INTEGER NOT NULL, level TEXT NOT NULL, kind TEXT NOT NULL,
    bot_id INTEGER, market TEXT, symbol TEXT, message TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS equity (
    ts_ms INTEGER NOT NULL, account TEXT NOT NULL, bot_id INTEGER NOT NULL DEFAULT 1, market TEXT NOT NULL,
    equity REAL NOT NULL
);
"""

_POSITION_FIELDS = (
    "market", "symbol", "direction", "qty", "entry_price", "stop_loss", "initial_stop", "take_profit",
    "time_limit_minutes", "trailing_activation", "trailing_distance", "best_price", "opened_at_ms",
    "strategy", "reason", "entry_fee", "status", "exit_price", "exit_fee", "exit_reason", "closed_at_ms",
)


def now_ms() -> int:
    return int(time.time() * 1000)


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        with self._lock:
            self._migrate_v1()
            self._conn.executescript(_SCHEMA)

    def _migrate_v1(self) -> None:
        """Versão 1 (um robô só) não tinha `bot_id`: tudo vira do robô 1."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(wallets)")}
        if not cols or "bot_id" in cols:
            return
        self._conn.executescript("""
            ALTER TABLE wallets RENAME TO wallets_v1;
            CREATE TABLE wallets (
                account TEXT NOT NULL, bot_id INTEGER NOT NULL, market TEXT NOT NULL, cash REAL NOT NULL,
                initial REAL NOT NULL, reset_at_ms INTEGER NOT NULL, PRIMARY KEY (account, bot_id, market));
            INSERT INTO wallets SELECT account, 1, market, cash, initial, reset_at_ms FROM wallets_v1;
            DROP TABLE wallets_v1;
            ALTER TABLE positions ADD COLUMN bot_id INTEGER NOT NULL DEFAULT 1;
            ALTER TABLE events ADD COLUMN bot_id INTEGER;
            ALTER TABLE equity ADD COLUMN bot_id INTEGER NOT NULL DEFAULT 1;
        """)

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    # --- chave/valor (configurações globais, marcas de patrimônio) ---
    def get_json(self, key: str, default: Any = None) -> Any:
        row = self._exec("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_json(self, key: str, value: Any) -> None:
        self._exec("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                   (key, json.dumps(value)))

    # --- robôs ---
    def list_bots(self) -> list[dict]:
        rows = self._exec("SELECT * FROM bots ORDER BY id").fetchall()
        return [dict(r) | {"config": json.loads(r["config"])} for r in rows]

    def insert_bot(self, name: str, config: dict, state: str = "stopped") -> int:
        cur = self._exec("INSERT INTO bots (name, config, state, created_at_ms) VALUES (?, ?, ?, ?)",
                         (name, json.dumps(config), state, now_ms()))
        return cur.lastrowid

    def update_bot(self, bot_id: int, name: str, config: dict) -> None:
        self._exec("UPDATE bots SET name = ?, config = ? WHERE id = ?", (name, json.dumps(config), bot_id))

    def set_bot_state(self, bot_id: int, state: str) -> None:
        self._exec("UPDATE bots SET state = ? WHERE id = ?", (state, bot_id))

    def get_bot_state(self, bot_id: int) -> str:
        row = self._exec("SELECT state FROM bots WHERE id = ?", (bot_id,)).fetchone()
        return row["state"] if row else "stopped"

    def delete_bot(self, bot_id: int) -> None:
        """Apaga o robô e TODO o histórico dele (posições, carteiras, patrimônio, eventos)."""
        with self._lock:
            for table in ("positions", "wallets", "equity", "events"):
                self._exec(f"DELETE FROM {table} WHERE bot_id = ?", (bot_id,))
            self._exec("DELETE FROM bots WHERE id = ?", (bot_id,))

    # --- carteiras ---
    def get_wallet(self, account: str, bot_id: int, market: str) -> dict | None:
        row = self._exec("SELECT * FROM wallets WHERE account = ? AND bot_id = ? AND market = ?",
                         (account, bot_id, market)).fetchone()
        return dict(row) if row else None

    def reset_wallet(self, account: str, bot_id: int, market: str, initial: float) -> None:
        self._exec(
            "INSERT INTO wallets (account, bot_id, market, cash, initial, reset_at_ms) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(account, bot_id, market) DO UPDATE SET cash = excluded.cash, initial = excluded.initial, "
            "reset_at_ms = excluded.reset_at_ms",
            (account, bot_id, market, initial, initial, now_ms()),
        )

    def add_cash(self, account: str, bot_id: int, market: str, delta: float) -> float:
        with self._lock:
            self._exec("UPDATE wallets SET cash = cash + ? WHERE account = ? AND bot_id = ? AND market = ?",
                       (delta, account, bot_id, market))
            return self.get_wallet(account, bot_id, market)["cash"]

    # --- posições ---
    def insert_position(self, account: str, bot_id: int, p: Position) -> Position:
        values = tuple(getattr(p, f) for f in _POSITION_FIELDS)
        cur = self._exec(
            f"INSERT INTO positions (account, bot_id, {', '.join(_POSITION_FIELDS)}, extra) "
            f"VALUES (?, ?, {', '.join('?' for _ in _POSITION_FIELDS)}, ?)",
            (account, bot_id, *values, json.dumps(p.extra)),
        )
        p.id = cur.lastrowid
        return p

    def update_position(self, p: Position) -> None:
        sets = ", ".join(f"{f} = ?" for f in _POSITION_FIELDS)
        self._exec(f"UPDATE positions SET {sets}, extra = ? WHERE id = ?",
                   (*(getattr(p, f) for f in _POSITION_FIELDS), json.dumps(p.extra), p.id))

    def _row_to_position(self, row: sqlite3.Row) -> Position:
        data = {f: row[f] for f in _POSITION_FIELDS}
        return Position(**data, id=row["id"], extra=json.loads(row["extra"] or "{}"))

    def open_positions(self, account: str, bot_id: int | None = None, market: str | None = None) -> list[Position]:
        sql = "SELECT * FROM positions WHERE account = ? AND status = 'open'"
        params: tuple = (account,)
        if bot_id is not None:
            sql += " AND bot_id = ?"
            params += (bot_id,)
        if market:
            sql += " AND market = ?"
            params += (market,)
        return [self._row_to_position(r) for r in self._exec(sql + " ORDER BY id", params).fetchall()]

    def delete_position(self, position_id: int) -> None:
        self._exec("DELETE FROM positions WHERE id = ?", (position_id,))

    def get_position(self, position_id: int) -> Position | None:
        row = self._exec("SELECT * FROM positions WHERE id = ?", (position_id,)).fetchone()
        return self._row_to_position(row) if row else None

    def position_owner(self, position_id: int) -> tuple[str, int] | None:
        row = self._exec("SELECT account, bot_id FROM positions WHERE id = ?", (position_id,)).fetchone()
        return (row["account"], row["bot_id"]) if row else None

    def closed_positions(self, account: str, bot_id: int, market: str | None = None, since_ms: int = 0,
                         limit: int | None = None) -> list[Position]:
        sql = "SELECT * FROM positions WHERE account = ? AND bot_id = ? AND status = 'closed' AND closed_at_ms >= ?"
        params: tuple = (account, bot_id, since_ms)
        if market:
            sql += " AND market = ?"
            params += (market,)
        sql += " ORDER BY closed_at_ms DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [self._row_to_position(r) for r in self._exec(sql, params).fetchall()]

    def count_opened_since(self, account: str, bot_id: int, market: str, since_ms: int) -> int:
        row = self._exec("SELECT COUNT(*) AS n FROM positions WHERE account = ? AND bot_id = ? AND market = ? "
                         "AND opened_at_ms >= ?", (account, bot_id, market, since_ms)).fetchone()
        return row["n"]

    # --- eventos (auditoria: toda decisão fica registrada, inclusive ordem negada) ---
    def log_event(self, kind: str, message: str, level: str = "info", bot_id: int | None = None,
                  market: str | None = None, symbol: str | None = None, data: dict | None = None) -> None:
        self._exec("INSERT INTO events (ts_ms, level, kind, bot_id, market, symbol, message, data) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (now_ms(), level, kind, bot_id, market, symbol, message, json.dumps(data or {}, default=str)))

    def recent_events(self, limit: int = 100, bot_id: int | None = None) -> list[dict]:
        if bot_id is None:
            rows = self._exec("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        else:  # eventos do robô + eventos globais (kill switch, erro de rede)
            rows = self._exec("SELECT * FROM events WHERE bot_id = ? OR bot_id IS NULL ORDER BY id DESC LIMIT ?",
                              (bot_id, limit)).fetchall()
        return [dict(r) | {"data": json.loads(r["data"] or "{}")} for r in rows]

    # --- curva de patrimônio ---
    def record_equity(self, account: str, bot_id: int, market: str, equity: float, ts_ms: int | None = None) -> None:
        self._exec("INSERT INTO equity (ts_ms, account, bot_id, market, equity) VALUES (?, ?, ?, ?, ?)",
                   (ts_ms or now_ms(), account, bot_id, market, equity))

    def equity_history(self, account: str, bot_id: int, market: str | None = None, since_ms: int = 0
                       ) -> list[tuple[int, float]]:
        """Com `market=None`, soma os mercados do robô em cada instante (snapshots são gravados
        juntos no mesmo ciclo, então o mesmo `ts_ms`)."""
        if market:
            rows = self._exec("SELECT ts_ms, equity FROM equity WHERE account = ? AND bot_id = ? AND market = ? "
                              "AND ts_ms >= ? ORDER BY ts_ms", (account, bot_id, market, since_ms)).fetchall()
        else:
            rows = self._exec("SELECT ts_ms, SUM(equity) AS equity FROM equity WHERE account = ? AND bot_id = ? "
                              "AND ts_ms >= ? GROUP BY ts_ms ORDER BY ts_ms", (account, bot_id, since_ms)).fetchall()
        return [(r["ts_ms"], r["equity"]) for r in rows]

    def clear_bot_market(self, account: str, bot_id: int, market: str) -> None:
        """Usado no reset da carteira demo: apaga histórico de posições/patrimônio daquele mercado."""
        self._exec("DELETE FROM positions WHERE account = ? AND bot_id = ? AND market = ?", (account, bot_id, market))
        self._exec("DELETE FROM equity WHERE account = ? AND bot_id = ? AND market = ?", (account, bot_id, market))
