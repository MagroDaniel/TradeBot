"""Rastreia quais anúncios de listagem já foram vistos, pra não alertar o mesmo duas vezes.

JSON simples — mesmo raciocínio do bot de apostas: fácil de trocar por SQLite/Postgres
depois se o histórico crescer, não precisa disso agora pro volume esperado (o bot roda a
cada 15-30 min, poucos anúncios novos por execução).
"""
from __future__ import annotations

import json
from pathlib import Path

_MAX_IDS_KEPT = 500  # evita o arquivo crescer pra sempre; sobra bastante margem


class SeenListingsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps({"seen_article_ids": []}), encoding="utf-8")

    def _read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def seen_ids(self) -> set[int]:
        return set(self._read().get("seen_article_ids", []))

    def mark_seen(self, article_ids: list[int]) -> None:
        data = self._read()
        existing = set(data.get("seen_article_ids", []))
        existing.update(article_ids)
        data["seen_article_ids"] = sorted(existing)[-_MAX_IDS_KEPT:]
        self._write(data)
