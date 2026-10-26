import pytest

from tests.helpers import make_position
from tradebot.position import evaluate_bar


def test_no_exit_inside_barriers():
    p = make_position()
    assert evaluate_bar(p, 100, 104, 97, 101, 1000) is None


def test_stop_checked_before_target_in_same_candle():
    p = make_position()
    decision = evaluate_bar(p, 100, 111, 94, 100, 1000)
    assert decision.reason == "stop_loss"
    assert decision.price == 95.0


def test_gap_through_stop_exits_at_open_not_at_stop():
    p = make_position()
    decision = evaluate_bar(p, 90, 92, 89, 91, 1000)
    assert decision.reason == "stop_loss"
    assert decision.price == 90.0  # pior que o stop: o gap custa caro e o backtest mostra isso


def test_take_profit_long_and_short():
    assert evaluate_bar(make_position(), 100, 110.5, 99, 110, 1000).reason == "take_profit"
    short = make_position(direction="short", stop_loss=105, initial_stop=105, take_profit=90)
    decision = evaluate_bar(short, 100, 101, 89, 90, 1000)
    assert (decision.reason, decision.price) == ("take_profit", 90)


def test_time_limit_exits_at_close():
    p = make_position(time_limit_minutes=60, opened_at_ms=0)
    assert evaluate_bar(p, 100, 101, 99, 100, 59 * 60_000) is None
    decision = evaluate_bar(p, 100, 101, 99, 100.5, 60 * 60_000)
    assert (decision.reason, decision.price) == ("time_limit", 100.5)


def test_trailing_arms_after_activation_and_only_tightens():
    p = make_position(take_profit=None, trailing_activation=5.0, trailing_distance=3.0)
    evaluate_bar(p, 100, 104, 99, 103, 1000)  # +4: ainda não armou
    assert p.stop_loss == 95.0
    evaluate_bar(p, 103, 108, 102, 107, 2000)  # melhor 108 → stop 105
    assert p.stop_loss == pytest.approx(105.0)
    evaluate_bar(p, 107, 107.5, 106, 106, 3000)  # recuo não afrouxa
    assert p.stop_loss == pytest.approx(105.0)
    decision = evaluate_bar(p, 106, 106, 104, 104.5, 4000)
    assert decision.reason == "trailing_stop"
    assert decision.price == pytest.approx(105.0)


def test_trailing_update_applies_only_from_next_candle():
    # o candle que faz a máxima não pode ser o mesmo que já sai pelo stop novo
    p = make_position(take_profit=None, trailing_activation=0.0, trailing_distance=2.0)
    assert evaluate_bar(p, 100, 110, 97, 98, 1000) is None
    assert p.stop_loss == pytest.approx(108.0)


def test_short_trailing():
    p = make_position(direction="short", stop_loss=105, initial_stop=105, take_profit=None,
                      trailing_activation=2.0, trailing_distance=2.0)
    evaluate_bar(p, 100, 100.5, 96, 97, 1000)
    assert p.stop_loss == pytest.approx(98.0)
    assert evaluate_bar(p, 97, 98.5, 96.5, 98, 2000).reason == "trailing_stop"
