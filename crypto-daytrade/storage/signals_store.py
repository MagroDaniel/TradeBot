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
    strategy_version: str = "legacy"
    timeframe: str | None = None
    signal_candle_closed_at: str | None = None
    entry_mode: str = "legacy"
    market_mode: str = "legacy"  # "spot" | "futures" | "legacy"


class SignalsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps({"signals": [], "last_report_date": None}), encoding="utf-8")

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

    def get_last_report_date(self) -> str | None:
        """Data (ISO, `YYYY-MM-DD`) do último relatório diário enviado — `None` se nunca
        enviou (arquivo antigo sem essa chave, ou primeira execução de sempre)."""
        return self._read().get("last_report_date")

    def set_last_report_date(self, iso_date: str) -> None:
        data = self._read()
        data["last_report_date"] = iso_date
        self._write(data)

    def get_last_weekly_report_date(self) -> str | None:
        """Mesma ideia de `get_last_report_date`, mas pro relatório semanal (toda
        segunda-feira) — chave separada pra não colidir com o corte diário."""
        return self._read().get("last_weekly_report_date")

    def set_last_weekly_report_date(self, iso_date: str) -> None:
        data = self._read()
        data["last_weekly_report_date"] = iso_date
        self._write(data)

    def get_last_monthly_report_date(self) -> str | None:
        """Mesma ideia, pro relatório mensal (todo dia 1)."""
        return self._read().get("last_monthly_report_date")

    def set_last_monthly_report_date(self, iso_date: str) -> None:
        data = self._read()
        data["last_monthly_report_date"] = iso_date
        self._write(data)

    def update(self, updated: list[SignalRecord]) -> None:
        """Substitui os registros pelos atualizados, casando por (symbol, opened_at) — chave
        natural já que um símbolo pode ter vários sinais ao longo do tempo."""
        data = self._read()
        by_key = {(u.symbol, u.opened_at): asdict(u) for u in updated}
        data["signals"] = [
            by_key.get((s["symbol"], s["opened_at"]), s) for s in data["signals"]
        ]
        self._write(data)
