import pytest

from analysis.resolution import pick_won
from storage.picks_store import Pick


def _pick(**overrides) -> Pick:
    base = dict(
        event_id="e1",
        match="Flamengo x Corinthians",
        home_team="Flamengo",
        away_team="Corinthians",
        commence_time="2026-09-12T23:30:00Z",
        market="soccer_brazil_campeonato:1x2/totals",
        selection="Empate",
        odds=4.49,
        model_probability=0.264,
        ev=0.185,
        suggested_stake_fraction=0.013,
    )
    base.update(overrides)
    return Pick(**base)


def _event(home_score: int, away_score: int) -> dict:
    return {
        "completed": True,
        "scores": [
            {"name": "Flamengo", "score": str(home_score)},
            {"name": "Corinthians", "score": str(away_score)},
        ],
    }


@pytest.mark.parametrize(
    "selection,home_goals,away_goals,expected",
    [
        # vitória / empate — já existia antes, continua coberto
        ("Flamengo vence", 2, 1, True),
        ("Flamengo vence", 1, 2, False),
        ("Corinthians vence", 1, 2, True),
        ("Corinthians vence", 2, 1, False),
        ("Empate", 1, 1, True),
        ("Empate", 2, 1, False),
        # over/under — já existia antes, continua coberto
        ("Over 2.5 gols", 2, 1, True),
        ("Over 2.5 gols", 1, 1, False),
        ("Under 2.5 gols", 1, 1, True),
        ("Under 2.5 gols", 2, 1, False),
        # BTTS — bug real: não existia nenhuma checagem, sempre caía em False
        ("Ambas marcam", 1, 1, True),
        ("Ambas marcam", 2, 0, False),
        ("Ambas marcam", 0, 0, False),
        ("Ambas não marcam", 2, 0, True),
        ("Ambas não marcam", 0, 0, True),
        ("Ambas não marcam", 1, 1, False),
        # dupla chance — bug real: não existia nenhuma checagem, sempre caía em False
        ("Flamengo ou empate", 2, 1, True),
        ("Flamengo ou empate", 1, 1, True),
        ("Flamengo ou empate", 0, 1, False),
        ("Corinthians ou empate", 0, 1, True),
        ("Corinthians ou empate", 1, 1, True),
        ("Corinthians ou empate", 2, 1, False),
        ("Flamengo ou Corinthians", 2, 1, True),
        ("Flamengo ou Corinthians", 1, 2, True),
        ("Flamengo ou Corinthians", 1, 1, False),
    ],
)
def test_pick_won_covers_all_10_selections(selection, home_goals, away_goals, expected):
    pick = _pick(selection=selection)
    event = _event(home_goals, away_goals)
    assert pick_won(pick, event) is expected


def test_pick_won_false_when_scores_missing():
    pick = _pick(selection="Flamengo vence")
    event = {"completed": True, "scores": None}
    assert pick_won(pick, event) is False


def test_pick_won_false_when_team_not_in_scores():
    pick = _pick(selection="Flamengo vence")
    event = {
        "completed": True,
        "scores": [{"name": "Flamengo", "score": "2"}],  # falta o placar do Corinthians
    }
    assert pick_won(pick, event) is False


def test_pick_won_false_for_unrecognized_selection():
    # seleção que não bate com nenhum dos 10 padrões conhecidos — comportamento antigo
    # (fallback pra False), mas agora é o caminho certo pra "não reconheço isso", não um bug
    # escondendo mercados que deveriam ter lógica própria
    pick = _pick(selection="Placar exato 2-1")
    event = _event(2, 1)
    assert pick_won(pick, event) is False
