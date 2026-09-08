import pytest

from analysis.multiple import MultipleLeg, build_multiple


def _leg(**overrides) -> MultipleLeg:
    base = dict(
        match="Time A x Time B",
        selection="Time A vence",
        odds=1.30,
        bookmaker="Bet365",
        model_probability=0.80,
    )
    base.update(overrides)
    return MultipleLeg(**base)


def test_build_multiple_none_when_not_enough_legs():
    candidates = [_leg(), _leg(match="Time C x Time D")]
    assert build_multiple(candidates, num_legs=4) is None


def test_build_multiple_none_when_disabled():
    candidates = [_leg() for _ in range(5)]
    assert build_multiple(candidates, num_legs=0) is None


def test_build_multiple_picks_highest_probability_legs():
    candidates = [
        _leg(match="Jogo 1", model_probability=0.60, odds=1.60),
        _leg(match="Jogo 2", model_probability=0.90, odds=1.15),
        _leg(match="Jogo 3", model_probability=0.85, odds=1.20),
        _leg(match="Jogo 4", model_probability=0.70, odds=1.45),
        _leg(match="Jogo 5", model_probability=0.55, odds=1.70),  # a mais fraca, deve sobrar
    ]

    multiple = build_multiple(candidates, num_legs=4)

    assert multiple is not None
    assert len(multiple.legs) == 4
    assert {leg.match for leg in multiple.legs} == {"Jogo 1", "Jogo 2", "Jogo 3", "Jogo 4"}


def test_build_multiple_combines_odds_and_probability_as_product():
    candidates = [
        _leg(match="Jogo 1", model_probability=0.80, odds=1.25),
        _leg(match="Jogo 2", model_probability=0.75, odds=1.35),
    ]

    multiple = build_multiple(candidates, num_legs=2)

    assert multiple is not None
    assert multiple.combined_odds == pytest.approx(1.25 * 1.35)
    assert multiple.combined_probability == pytest.approx(0.80 * 0.75)


def test_build_multiple_combined_ev_can_be_negative():
    # odds "justas" pra cada perna (odd = 1/prob, sem vantagem nenhuma) — mesmo assim o produto
    # das odds é exatamente 1/prob_combinada, então o EV combinado deveria ficar em ~0%, não
    # negativo por si só; aqui simulamos o caso real (odd um pouco abaixo da justa, como o
    # mercado tende a precificar favoritos claros) para confirmar que o EV combinado fica < 0.
    candidates = [
        _leg(match="Jogo 1", model_probability=0.80, odds=1.20),  # justa seria 1.25
        _leg(match="Jogo 2", model_probability=0.75, odds=1.28),  # justa seria ~1.33
    ]

    multiple = build_multiple(candidates, num_legs=2)

    assert multiple is not None
    assert multiple.combined_ev < 0
