from datetime import date, datetime, timezone

from data.schedule import date_brt, is_forex_market_open


def test_date_brt_same_day_when_utc_is_daytime():
    # 10h UTC = 07h BRT, mesmo dia calendário
    assert date_brt("2026-09-08T10:00:00+00:00") == date(2026, 9, 8)


def test_date_brt_crosses_to_previous_day_near_utc_midnight():
    # 02h UTC de 09/09 = 23h BRT de 08/09 (dia anterior em BRT)
    assert date_brt("2026-09-09T02:00:00+00:00") == date(2026, 9, 8)


def _dt(year, month, day, hour, weekday_check=None):
    d = datetime(year, month, day, hour, tzinfo=timezone.utc)
    if weekday_check is not None:
        assert d.weekday() == weekday_check
    return d


def test_market_closed_all_saturday():
    # 2026-09-12 é sábado
    assert is_forex_market_open(_dt(2026, 9, 12, 0, weekday_check=5)) is False
    assert is_forex_market_open(_dt(2026, 9, 12, 23, weekday_check=5)) is False


def test_market_closed_sunday_before_22h_utc():
    # 2026-09-13 é domingo
    assert is_forex_market_open(_dt(2026, 9, 13, 21, weekday_check=6)) is False


def test_market_opens_sunday_22h_utc():
    assert is_forex_market_open(_dt(2026, 9, 13, 22, weekday_check=6)) is True


def test_market_open_during_the_week():
    # 2026-09-09 é quarta
    assert is_forex_market_open(_dt(2026, 9, 9, 12, weekday_check=2)) is True


def test_market_open_friday_before_22h_utc():
    # 2026-09-11 é sexta
    assert is_forex_market_open(_dt(2026, 9, 11, 21, weekday_check=4)) is True


def test_market_closes_friday_22h_utc():
    assert is_forex_market_open(_dt(2026, 9, 11, 22, weekday_check=4)) is False
