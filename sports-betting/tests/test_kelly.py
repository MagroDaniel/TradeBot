import pytest

from analysis.kelly import capped_stake, kelly_fraction


def test_kelly_fraction_zero_without_edge():
    assert kelly_fraction(model_probability=0.4, decimal_odds=2.0) == 0.0


def test_kelly_fraction_positive_with_edge():
    stake = kelly_fraction(model_probability=0.55, decimal_odds=2.10, fraction=1.0)
    assert stake > 0


def test_capped_stake_respects_max():
    stake = capped_stake(model_probability=0.9, decimal_odds=3.0, fraction=1.0, max_stake=0.03)
    assert stake == pytest.approx(0.03)
