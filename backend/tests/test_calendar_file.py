

def test_shipped_nse_2026_calendar_marks_listed_holidays_closed():
    from datetime import date
    from pathlib import Path

    from stratagy.sessions import ExchangeCalendar

    cal = ExchangeCalendar.from_file(Path(__file__).resolve().parents[1] / "data" / "exchange_calendar.json")
    assert cal.verified
    for d in (date(2026, 10, 2), date(2026, 10, 20), date(2026, 11, 10), date(2026, 12, 25)):
        assert not cal.session_for(d).is_trading_day
    assert cal.session_for(date(2026, 10, 26)).is_trading_day
