"""Rastreia sinais emitidos e seus resultados — mesma lógica do bot de apostas
(`storage/picks_store.py` lá): um registro por sinal, que acumula o resultado quando
resolvido, em vez de tipos separados pra "previsto" e "resolvido".

Existe pra dar um histórico REAL de acerto/erro — essencial já que a ideia é eventualmente
oferecer isso pra outras pessoas (ver CLAUDE.md): nada de taxa de acerto inventada, o
`analysis/performance.py` só soma o que está registrado aqui.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class SignalRecord:
    symbol: str
    direction: str  # "long" ou "short"
    entry: float
    stop_loss: float
    target: float
    rsi_value: float
    reason: str
    opened_at: str  # ISO datetime (UTC)
    status: str = "open"  # "open" | "target_hit" | "stop_hit" | "expired"
    closed_at: str | None = None
    close_price: float | None = None


class SignalsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps({"signals": []}), encoding="utf-8")

    def _read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def add(self, record: SignalRecord) -> None:
        data = self._read()
        data["signals"].append(asdict(record))
        self._write(data)

    def open_signals(self) -> list[SignalRecord]:
        data = self._read()
        return [SignalRecord(**s) for s in data["signals"] if s["status"] == "open"]

    def has_open_signal_for(self, symbol: str) -> bool:
        return any(s.symbol == symbol for s in self.open_signals())

    def all_signals(self) -> list[SignalRecord]:
        data = self._read()
        return [SignalRecord(**s) for s in data["signals"]]

    def update(self, updated: list[SignalRecord]) -> None:
        """Substitui os registros pelos atualizados, casando por (symbol, opened_at) — chave
        natural já que um símbolo pode ter vários sinais ao longo do tempo."""
        data = self._read()
        by_key = {(u.symbol, u.opened_at): asdict(u) for u in updated}
        data["signals"] = [
            by_key.get((s["symbol"], s["opened_at"]), s) for s in data["signals"]
        ]
        self._write(data)
