"""Persistência em SQLite — posições, carteiras demo, eventos (auditoria) e configurações.

Substitui o `signals.json` do crypto-daytrade: aqui há escrita concorrente (motor numa
thread, painel em outra) e consultas (P&L do dia, últimos N eventos), o que JSON não aguenta
bem. Tudo é separado por `account` (paper | demo | live) — uma posição de teste nunca se
mistura com uma real, nem no histórico nem no cálculo de risco.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from tradebot.models import Position

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS wallets (
    account TEXT NOT NULL, market TEXT NOT NULL, cash REAL NOT NULL, initial REAL NOT NULL,
    reset_at_ms INTEGER NOT NULL, PRIMARY KEY (account, market)
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL, market TEXT NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL,
    qty REAL NOT NULL, entry_price REAL NOT NULL, stop_loss REAL NOT NULL, initial_stop REAL NOT NULL,
    take_profit REAL, time_limit_minutes INTEGER, trailing_activation REAL, trailing_distance REAL,
    best_price REAL, opened_at_ms INTEGER NOT NULL, strategy TEXT NOT NULL, reason TEXT NOT NULL,
    entry_fee REAL NOT NULL DEFAULT 0, status TEXT NOT NULL, exit_price REAL, exit_fee REAL NOT NULL DEFAULT 0,
    exit_reason TEXT, closed_at_ms INTEGER, extra TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions (account, status);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts_ms INTEGER NOT NULL, level TEXT NOT NULL,
    kind TEXT NOT NULL, market TEXT, symbol TEXT, message TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS equity (
    ts_ms INTEGER NOT NULL, account TEXT NOT NULL, market TEXT NOT NULL, equity REAL NOT NULL
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
        self._conn.execute("PRAGMA journal_mode=WAL") if self.path != ":memory:" else None
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(_SCHEMA)

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    # --- chave/valor (configurações, estado do motor) ---
    def get_json(self, key: str, default: Any = None) -> Any:
        row = self._exec("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_json(self, key: str, value: Any) -> None:
        self._exec("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                   (key, json.dumps(value)))

    # --- carteiras ---
    def get_wallet(self, account: str, market: str) -> dict | None:
        row = self._exec("SELECT * FROM wallets WHERE account = ? AND market = ?", (account, market)).fetchone()
        return dict(row) if row else None

    def reset_wallet(self, account: str, market: str, initial: float) -> None:
        self._exec(
            "INSERT INTO wallets (account, market, cash, initial, reset_at_ms) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(account, market) DO UPDATE SET cash = excluded.cash, initial = excluded.initial, "
            "reset_at_ms = excluded.reset_at_ms",
            (account, market, initial, initial, now_ms()),
        )

    def add_cash(self, account: str, market: str, delta: float) -> float:
        with self._lock:
            self._exec("UPDATE wallets SET cash = cash + ? WHERE account = ? AND market = ?", (delta, account, market))
            return self.get_wallet(account, market)["cash"]

    # --- posições ---
    def insert_position(self, account: str, p: Position) -> Position:
        values = tuple(getattr(p, f) for f in _POSITION_FIELDS)
        cur = self._exec(
            f"INSERT INTO positions (account, {', '.join(_POSITION_FIELDS)}, extra) "
            f"VALUES (?, {', '.join('?' for _ in _POSITION_FIELDS)}, ?)",
            (account, *values, json.dumps(p.extra)),
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

    def open_positions(self, account: str, market: str | None = None) -> list[Position]:
        sql = "SELECT * FROM positions WHERE account = ? AND status = 'open'"
        params: tuple = (account,)
        if market:
            sql += " AND market = ?"
            params += (market,)
        return [self._row_to_position(r) for r in self._exec(sql + " ORDER BY id", params).fetchall()]

    def get_position(self, position_id: int) -> Position | None:
        row = self._exec("SELECT * FROM positions WHERE id = ?", (position_id,)).fetchone()
        return self._row_to_position(row) if row else None

    def position_account(self, position_id: int) -> str | None:
        row = self._exec("SELECT account FROM positions WHERE id = ?", (position_id,)).fetchone()
        return row["account"] if row else None

    def closed_positions(self, account: str, since_ms: int = 0, limit: int | None = None) -> list[Position]:
        sql = "SELECT * FROM positions WHERE account = ? AND status = 'closed' AND closed_at_ms >= ? ORDER BY closed_at_ms DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [self._row_to_position(r) for r in self._exec(sql, (account, since_ms)).fetchall()]

    def count_opened_since(self, account: str, market: str, since_ms: int) -> int:
        row = self._exec("SELECT COUNT(*) AS n FROM positions WHERE account = ? AND market = ? AND opened_at_ms >= ?",
                         (account, market, since_ms)).fetchone()
        return row["n"]

    def closed_positions_market(self, account: str, market: str, since_ms: int) -> list[Position]:
        rows = self._exec("SELECT * FROM positions WHERE account = ? AND market = ? AND status = 'closed' "
                          "AND closed_at_ms >= ? ORDER BY closed_at_ms", (account, market, since_ms)).fetchall()
        return [self._row_to_position(r) for r in rows]

    # --- eventos (auditoria: toda decisão fica registrada, inclusive ordem negada) ---
    def log_event(self, kind: str, message: str, level: str = "info", market: str | None = None,
                  symbol: str | None = None, data: dict | None = None) -> None:
        self._exec("INSERT INTO events (ts_ms, level, kind, market, symbol, message, data) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (now_ms(), level, kind, market, symbol, message, json.dumps(data or {}, default=str)))

    def recent_events(self, limit: int = 100) -> list[dict]:
        rows = self._exec("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) | {"data": json.loads(r["data"] or "{}")} for r in rows]

    # --- curva de patrimônio ---
    def record_equity(self, account: str, market: str, equity: float, ts_ms: int | None = None) -> None:
        self._exec("INSERT INTO equity (ts_ms, account, market, equity) VALUES (?, ?, ?, ?)",
                   (ts_ms or now_ms(), account, market, equity))

    def equity_history(self, account: str, market: str, since_ms: int = 0) -> list[tuple[int, float]]:
        rows = self._exec("SELECT ts_ms, equity FROM equity WHERE account = ? AND market = ? AND ts_ms >= ? ORDER BY ts_ms",
                          (account, market, since_ms)).fetchall()
        return [(r["ts_ms"], r["equity"]) for r in rows]

    def clear_account(self, account: str, market: str) -> None:
        """Usado no reset da carteira demo: apaga histórico de posições/patrimônio daquele mercado."""
        self._exec("DELETE FROM positions WHERE account = ? AND market = ?", (account, market))
        self._exec("DELETE FROM equity WHERE account = ? AND market = ?", (account, market))
