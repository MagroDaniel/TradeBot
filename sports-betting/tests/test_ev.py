import pytest

from analysis.ev import calculate_ev, implied_probability, market_hold, remove_overround


def test_implied_probability():
    assert implied_probability(2.0) == pytest.approx(0.5)
    assert implied_probability(4.0) == pytest.approx(0.25)


def test_implied_probability_rejects_invalid_odds():
    with pytest.raises(ValueError):
        implied_probability(1.0)


def test_remove_overround_normalizes_to_one():
    # odds típicas de um mercado 1X2 com margem da casa
    probs = [implied_probability(o) for o in (2.0, 3.4, 4.0)]
    fair = remove_overround(probs)
    assert sum(fair) == pytest.approx(1.0)


def test_calculate_ev_positive_when_model_favors_bettor():
    ev = calculate_ev(model_probability=0.55, decimal_odds=2.10)
    assert ev == pytest.approx(0.55 * 2.10 - 1)
    assert ev > 0


def test_calculate_ev_negative_when_odds_too_short():
    ev = calculate_ev(model_probability=0.4, decimal_odds=2.0)
    assert ev < 0


def test_market_hold_positive_for_typical_bookmaker_margin():
    # mesmas odds do test_remove_overround_normalizes_to_one — margem conhecida de ~5%
    hold = market_hold([2.0, 3.4, 4.0])
    assert hold == pytest.approx(1 / 2.0 + 1 / 3.4 + 1 / 4.0 - 1)
    assert hold > 0


def test_market_hold_zero_for_fair_odds():
    # odds "justas" (sem margem) somam exatamente 100% de probabilidade implícita
    hold = market_hold([2.0, 2.0])
    assert hold == pytest.approx(0.0)


def test_market_hold_negative_for_synthetic_market_across_books():
    # hold sintético: melhor odd por seleção vindo de casas diferentes pode ficar negativo
    # (mercado "mais aberto" que qualquer casa sozinha) — ver docs/estrategias_extraidas_livros.md
    hold = market_hold([2.10, 2.10])  # 1/2.10 + 1/2.10 - 1 < 0
    assert hold < 0
