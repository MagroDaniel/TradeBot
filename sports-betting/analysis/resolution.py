"""Confere se um `Pick` bateu, a partir do placar bruto devolvido pela Odds API
(`event["scores"]`, lista de `{"name": time, "score": "N"}`).

Função pura, sem I/O — extraída de `main.py` pra poder ser testada isoladamente (main.py não
pode ser importado sem credenciais, ver CLAUDE.md). Precisa cobrir as 10 seleções que
`main.py::_selection_candidates` gera — um `pick.selection` que não bate com nenhuma delas cai
no `return False` do final, tratado como "não bateu" (comportamento antigo, antes de existir
`analysis/resolution.py`, cobria só 5 das 10 e derrubava as outras 5 nesse fallback por engano —
ver CLAUDE.md, "Resolução de resultados", pra o bug real que isso causou em produção).
"""
from __future__ import annotations

from storage.picks_store import Pick


def pick_won(pick: Pick, event: dict) -> bool:
    scores = {
        s["name"]: int(s["score"])
        for s in event.get("scores", []) or []
        if s.get("score") is not None
    }
    home_goals = scores.get(pick.home_team)
    away_goals = scores.get(pick.away_team)
    if home_goals is None or away_goals is None:
        return False

    home_team = pick.home_team
    away_team = pick.away_team
    total_goals = home_goals + away_goals
    both_scored = home_goals > 0 and away_goals > 0

    if pick.selection == f"{home_team} vence":
        return home_goals > away_goals
    if pick.selection == f"{away_team} vence":
        return away_goals > home_goals
    if pick.selection == "Empate":
        return home_goals == away_goals
    if pick.selection == "Over 2.5 gols":
        return total_goals > 2
    if pick.selection == "Under 2.5 gols":
        return total_goals <= 2
    if pick.selection == "Ambas marcam":
        return both_scored
    if pick.selection == "Ambas não marcam":
        return not both_scored
    if pick.selection == f"{home_team} ou empate":
        return home_goals >= away_goals
    if pick.selection == f"{away_team} ou empate":
        return away_goals >= home_goals
    if pick.selection == f"{home_team} ou {away_team}":
        return home_goals != away_goals
    return False
