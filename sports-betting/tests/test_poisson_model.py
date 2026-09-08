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
