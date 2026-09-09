import pytest

from analysis.kelly import cap_group_exposure, capped_stake, kelly_fraction


def test_kelly_fraction_zero_without_edge():
    assert kelly_fraction(model_probability=0.4, decimal_odds=2.0) == 0.0


def test_kelly_fraction_positive_with_edge():
    stake = kelly_fraction(model_probability=0.55, decimal_odds=2.10, fraction=1.0)
    assert stake > 0


def test_capped_stake_respects_max():
    stake = capped_stake(model_probability=0.9, decimal_odds=3.0, fraction=1.0, max_stake=0.03)
    assert stake == pytest.approx(0.03)


def test_cap_group_exposure_leaves_stakes_alone_when_under_max():
    stakes = [0.01, 0.01]
    assert cap_group_exposure(stakes, max_stake=0.03) == stakes


def test_cap_group_exposure_scales_down_proportionally_when_over_max():
    # caso real: 5 picks do mesmo jogo somando 13.3% da banca (08/09/2026) — deveriam ser
    # reduzidos proporcionalmente pra caber em 3%, mantendo a proporção relativa entre eles
    stakes = [0.03, 0.03, 0.03, 0.03, 0.0129]
    capped = cap_group_exposure(stakes, max_stake=0.03)

    assert sum(capped) == pytest.approx(0.03)
    # a maior aposta original continua a maior depois de reduzir
    assert capped[0] == max(capped)
    # proporção entre a 1ª e a última se mantém (mesmo fator de escala pra todas)
    assert capped[0] / capped[-1] == pytest.approx(stakes[0] / stakes[-1])


def test_cap_group_exposure_single_stake_above_max_gets_reduced_to_max():
    assert cap_group_exposure([0.05], max_stake=0.03) == pytest.approx([0.03])


def test_cap_group_exposure_empty_list():
    assert cap_group_exposure([], max_stake=0.03) == []
