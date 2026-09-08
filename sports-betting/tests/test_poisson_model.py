from datetime import date

import pytest

from model.poisson_model import MatchResult, PoissonModel


@pytest.fixture
def fitted_model() -> PoissonModel:
    matches = [
        MatchResult("Time A", "Time B", 2, 1),
        MatchResult("Time B", "Time A", 1, 1),
        MatchResult("Time A", "Time C", 3, 0),
        MatchResult("Time C", "Time A", 0, 2),
        MatchResult("Time B", "Time C", 1, 1),
        MatchResult("Time C", "Time B", 0, 0),
    ]
    return PoissonModel().fit(matches)


def test_fit_requires_matches():
    with pytest.raises(ValueError):
        PoissonModel().fit([])


def test_match_probabilities_sum_to_one(fitted_model):
    # A soma não fecha em exatamente 1.0 porque a distribuição de Poisson é
    # truncada em max_goals (cauda residual desprezível, mas não nula).
    probs = fitted_model.match_probabilities("Time A", "Time B")
    assert probs["home_win"] + probs["draw"] + probs["away_win"] == pytest.approx(1.0, abs=1e-3)


def test_stronger_attacking_team_favored(fitted_model):
    # Time A marcou mais e sofreu menos que Time C nos dados de exemplo
    probs = fitted_model.match_probabilities("Time A", "Time C")
    assert probs["home_win"] > probs["away_win"]


def test_unknown_team_raises(fitted_model):
    with pytest.raises(KeyError):
        fitted_model.match_probabilities("Time A", "Time Desconhecido")


def test_matches_without_date_are_unweighted():
    # Sem match_date, a ponderação temporal não tem o que fazer — deve se comportar
    # exatamente como o modelo sem ponderação (half_life_days=None).
    matches = [
        MatchResult("Time A", "Time B", 2, 1),
        MatchResult("Time B", "Time A", 1, 1),
        MatchResult("Time A", "Time C", 3, 0),
        MatchResult("Time C", "Time A", 0, 2),
    ]
    weighted = PoissonModel(half_life_days=30).fit(matches)
    unweighted = PoissonModel(half_life_days=None).fit(matches)

    assert weighted.league_avg_home_goals == pytest.approx(unweighted.league_avg_home_goals)
    assert weighted.team_strength["Time A"] == unweighted.team_strength["Time A"]


def test_recent_matches_weighted_more_than_old_ones():
    # Time X era fraco há muito tempo e forte recentemente (e vice-versa pro Time Y).
    # Com meia-vida curta, a força estimada deve refletir principalmente os jogos recentes.
    matches = [
        MatchResult("Time X", "Time Y", 0, 3, match_date=date(2020, 1, 1)),
        MatchResult("Time Y", "Time X", 3, 0, match_date=date(2020, 1, 8)),
        MatchResult("Time X", "Time Y", 3, 0, match_date=date(2024, 1, 1)),
        MatchResult("Time Y", "Time X", 0, 3, match_date=date(2024, 1, 8)),
    ]

    weighted = PoissonModel(half_life_days=180).fit(matches)
    unweighted = PoissonModel(half_life_days=None).fit(matches)

    # sem ponderação, os dois times ficam com força idêntica (2 vitórias e 2 derrotas cada)
    assert unweighted.team_strength["Time X"] == unweighted.team_strength["Time Y"]

    # com meia-vida curta, os jogos de 2024 (Time X goleando) dominam a estimativa
    assert weighted.team_strength["Time X"].attack > weighted.team_strength["Time Y"].attack


def test_disabling_half_life_ignores_dates():
    matches = [
        MatchResult("Time X", "Time Y", 0, 3, match_date=date(2020, 1, 1)),
        MatchResult("Time X", "Time Y", 3, 0, match_date=date(2024, 1, 1)),
    ]
    model = PoissonModel(half_life_days=None).fit(matches)
    # média simples dos dois jogos, sem favorecer o mais recente
    assert model.league_avg_home_goals == pytest.approx(1.5)
