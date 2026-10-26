"""Usado pelo workflow de release: confere que a tag bate com `__version__` e imprime a seção
correspondente do CHANGELOG.md (texto da release e notas do botão "Atualizar" do painel).

    python scripts/release_notes.py v0.2.0 > release_notes.md
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradebot import __version__  # noqa: E402


def section(changelog: str, tag: str) -> str | None:
    lines, out, inside = changelog.splitlines(), [], False
    for line in lines:
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].strip().split()[0] == tag
            continue
        if inside:
            out.append(line)
    return "\n".join(out).strip() if inside or out else None


def main(tag: str) -> int:
    if tag != f"v{__version__}":
        print(f"Tag {tag} não bate com __version__ = {__version__} (tradebot/__init__.py)", file=sys.stderr)
        return 1
    notes = section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), tag)
    if not notes:
        print(f"CHANGELOG.md não tem a seção '## {tag}'", file=sys.stderr)
        return 1
    print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
