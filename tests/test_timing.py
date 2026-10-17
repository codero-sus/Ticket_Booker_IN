from datetime import date

from ticket_booker.timing import (
    is_ac_class,
    parse_journey_date,
    tatkal_open_datetime,
)


def test_parse_journey_date_formats():
    assert parse_journey_date("2026-10-20") == date(2026, 10, 20)
    assert parse_journey_date("20-10-2026") == date(2026, 10, 20)
    assert parse_journey_date("20/10/2026") == date(2026, 10, 20)


def test_ac_classes():
    for code in ("1A", "2A", "3A", "CC", "EC", "3E"):
        assert is_ac_class(code), code
    for code in ("SL", "2S"):
        assert not is_ac_class(code), code


def test_tatkal_open_ac_is_10am_day_before():
    opening = tatkal_open_datetime(date(2026, 10, 20), "3A")
    assert (opening.day, opening.hour, opening.minute) == (19, 10, 0)
    assert str(opening.tzinfo) == "Asia/Kolkata"


def test_tatkal_open_nonac_is_11am_day_before():
    opening = tatkal_open_datetime(date(2026, 10, 20), "SL")
    assert (opening.day, opening.hour, opening.minute) == (19, 11, 0)
