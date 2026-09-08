from datetime import date

from data.schedule import date_brt


def test_date_brt_same_day_when_utc_is_daytime():
    # 10h UTC = 07h BRT, mesmo dia calendário
    assert date_brt("2026-09-08T10:00:00+00:00") == date(2026, 9, 8)


def test_date_brt_crosses_to_previous_day_near_utc_midnight():
    # 02h UTC de 09/09 = 23h BRT de 08/09 (dia anterior em BRT)
    assert date_brt("2026-09-09T02:00:00+00:00") == date(2026, 9, 8)
