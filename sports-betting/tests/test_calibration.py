from datetime import date, timedelta

from backtest.calibration import calibration_report, split_train_test
from model.poisson_model import MatchResult


def _dated_matches(n: int, start: date = date(2020, 1, 1)) -> list[MatchResult]:
    return [
        MatchResult("Time A", "Time B", 1, 0, match_date=start + timedelta(days=i))
        for i in range(n)
    ]


def test_split_train_test_respects_fraction_and_order():
    matches = _dated_matches(100)
    train, test = split_train_test(matches, test_fraction=0.2)

    assert len(train) == 80
    assert len(test) == 20
    # teste é sempre a parte mais recente (datas maiores que o treino)
    assert max(m.match_date for m in train) < min(m.match_date for m in test)


def test_split_train_test_keeps_undated_matches_in_train():
    dated = _dated_matches(10)
    undated = [MatchResult("Time A", "Time B", 2, 2, match_date=None)]
    train, test = split_train_test(dated + undated, test_fraction=0.2)

    assert undated[0] in train
    assert undated[0] not in test


def test_calibration_report_skips_bins_below_min_size():
    # poucos jogos de teste — nenhum bin deveria ter amostra suficiente
    train = [
        MatchResult("Time A", "Time B", 2, 1, match_date=date(2020, 1, 1)),
        MatchResult("Time B", "Time A", 1, 1, match_date=date(2020, 1, 8)),
    ]
    test = [MatchResult("Time A", "Time B", 1, 0, match_date=date(2020, 2, 1))]

    bins = calibration_report(train, test, min_bin_size=20)

    assert bins == []


def test_calibration_report_recovers_dominant_outcome():
    # Time A vence a maioria dos jogos de treino e de teste — o bin de maior probabilidade
    # prevista pra home_win tem que ter observed_rate também majoritário (>50%), confirmando que
    # o relatório pega o sinal real, mesmo sem exigir calibração perfeita (o modelo é simples e
    # só tem 2 times nesse fixture, não deveria bater exato).
    train = [
        MatchResult(
            "Time A", "Time B", 3, i % 3, match_date=date(2020, 1, 1) + timedelta(days=7 * i)
        )
        for i in range(30)
    ]
    test = [
        MatchResult(
            "Time A", "Time B", 2, i % 3, match_date=date(2021, 1, 1) + timedelta(days=7 * i)
        )
        for i in range(30)
    ]

    bins = calibration_report(train, test, min_bin_size=10)

    home_win_bins = [b for b in bins if b.outcome == "home_win"]
    assert home_win_bins  # achou pelo menos um bin com amostra suficiente
    high_prob_bin = max(home_win_bins, key=lambda b: b.prob_low)
    assert high_prob_bin.observed_rate > 0.5


def test_calibration_report_skips_teams_without_history():
    train = [MatchResult("Time A", "Time B", 1, 1, match_date=date(2020, 1, 1))]
    test = [
        MatchResult("Time X", "Time Y", 1, 0, match_date=date(2021, 1, 1))
        for _ in range(25)
    ]

    bins = calibration_report(train, test, min_bin_size=5)

    assert bins == []  # times desconhecidos, nada pra avaliar
