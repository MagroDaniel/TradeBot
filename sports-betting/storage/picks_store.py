"""Armazenamento simples (JSON) dos picks enviados e seus resultados.

Suficiente para o volume de um bot diário; pode ser trocado por SQLite/Postgres
depois sem alterar o restante do código (a interface é save/load por data).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Pick:
    event_id: str
    match: str
    home_team: str
    away_team: str
    commence_time: str
    market: str
    selection: str
    odds: float
    model_probability: float
    ev: float
    suggested_stake_fraction: float
    result: str | None = None  # "green" | "red" | None (ainda não resolvido)
    profit_units: float | None = None
    bookmaker: str | None = None  # casa de apostas que ofereceu a melhor odd (None em picks
    # salvos antes desse campo existir — carregados via Pick(**p), o default cobre isso)


class PicksStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    def _read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def save_picks(self, date: str, picks: list[Pick]) -> None:
        data = self._read()
        data[date] = [asdict(p) for p in picks]
        self._write(data)

    def load_picks(self, date: str) -> list[Pick]:
        data = self._read()
        return [Pick(**p) for p in data.get(date, [])]

    def update_results(self, date: str, picks: list[Pick]) -> None:
        self.save_picks(date, picks)

    def all_picks(self) -> list[Pick]:
        data = self._read()
        return [Pick(**p) for day_picks in data.values() for p in day_picks]
