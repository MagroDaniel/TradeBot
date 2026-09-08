from datetime import date

from data.schedule import format_date_br, format_time_brt, is_same_day_brt


def test_is_same_day_brt_true_when_same_calendar_day():
    # 10h UTC = 07h BRT, mesmo dia calendário
    assert is_same_day_brt("2026-09-08T10:00:00Z", date(2026, 9, 8))


def test_is_same_day_brt_false_when_different_day():
    assert not is_same_day_brt("2026-09-09T10:00:00Z", date(2026, 9, 8))


def test_is_same_day_brt_handles_date_crossing_midnight_utc():
    # 02h UTC de 09/09 = 23h BRT de 08/09 (dia anterior em BRT)
    assert is_same_day_brt("2026-09-09T02:00:00Z", date(2026, 9, 8))
    assert not is_same_day_brt("2026-09-09T02:00:00Z", date(2026, 9, 9))


def test_format_date_br():
    assert format_date_br("2026-09-08") == "08/09"


def test_format_time_brt():
    assert format_time_brt("2026-09-12T23:30:00Z") == "20h30"
