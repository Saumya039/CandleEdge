from datetime import UTC, date, datetime, time, timedelta

import pytest

from stratagy.candles import CandleBuilder, resample
from stratagy.config import SessionConfig
from stratagy.models import IST, Candle, Tick
from stratagy.sessions import CalendarFile, ExchangeCalendar, SessionPhase, SpecialSession

CUTOFF = time(15, 15)
MON = date(2026, 10, 26)  # a Monday


def at(h, m, s=0, d=MON):
    return datetime(d.year, d.month, d.day, h, m, s, tzinfo=IST)


def test_phase_boundaries_around_open_cutoff_close():
    cal = ExchangeCalendar()
    ph = lambda t: cal.phase(t, 15, CUTOFF)  # noqa: E731
    assert ph(at(8, 59, 59)) == SessionPhase.CLOSED
    assert ph(at(9, 0)) == SessionPhase.PRE_MARKET
    assert ph(at(9, 14, 59)) == SessionPhase.PRE_MARKET
    assert ph(at(9, 15)) == SessionPhase.OPENING_RANGE
    assert ph(at(9, 29, 59)) == SessionPhase.OPENING_RANGE
    assert ph(at(9, 30)) == SessionPhase.TRADING
    assert ph(at(15, 14, 59)) == SessionPhase.TRADING
    assert ph(at(15, 15)) == SessionPhase.NO_NEW_ENTRIES
    assert ph(at(15, 39, 59)) == SessionPhase.NO_NEW_ENTRIES
    assert ph(at(15, 40)) == SessionPhase.POST_CLOSE


def test_weekend_holiday_and_special_session():
    sat = date(2026, 10, 24)
    hol = date(2026, 10, 27)
    sp = date(2026, 10, 28)
    cal = ExchangeCalendar(
        SessionConfig(), CalendarFile(holidays=[hol], special_sessions=[SpecialSession(date=sp, open=time(18, 15), close=time(19, 15), note="Muhurat")]),
        verified=True,
    )
    assert cal.phase(at(10, 0, d=sat), 15, CUTOFF) == SessionPhase.CLOSED
    assert cal.phase(at(10, 0, d=hol), 15, CUTOFF) == SessionPhase.CLOSED
    assert cal.session_for(sp).is_trading_day and cal.session_for(sp).open.hour == 18
    assert cal.phase(at(10, 0, d=sp), 15, CUTOFF) == SessionPhase.CLOSED  # normal hours do not apply
    assert cal.phase(at(18, 30, d=sp), 15, CUTOFF) in (SessionPhase.OPENING_RANGE, SessionPhase.TRADING)


def test_unverified_calendar_is_flagged_not_assumed():
    s = ExchangeCalendar().session_for(MON)
    assert s.is_trading_day and not s.calendar_verified and "unknown" in s.note.lower()


def test_utc_input_is_converted_to_ist_and_naive_rejected():
    cal = ExchangeCalendar()
    utc = datetime(2026, 10, 26, 3, 45, tzinfo=UTC)  # 09:15 IST
    assert cal.phase(utc, 15, CUTOFF) == SessionPhase.OPENING_RANGE
    with pytest.raises(ValueError):
        cal.phase(datetime(2026, 10, 26, 10, 0), 15, CUTOFF)


def test_next_open_skips_weekend():
    cal = ExchangeCalendar()
    nxt = cal.next_open(at(16, 0, d=date(2026, 10, 23)))  # Friday after close
    assert nxt == at(9, 15, d=date(2026, 10, 26))


# ---------------------------------------------------------------- candles
def tick(sec, price, vol=None, ex=True, m=0):
    ts = at(9, 15 + m, sec)
    return Tick(instrument_id="X", ltp=price, qty=1, volume=vol, exchange_ts=ts if ex else None, received_ts=ts + timedelta(milliseconds=50))


def test_builder_builds_closed_candles_with_cumulative_volume():
    b = CandleBuilder("X", "T")
    assert b.on_tick(tick(1, 100, 1000)) is None
    b.on_tick(tick(20, 103, 1010))
    b.on_tick(tick(40, 99, 1030))
    closed = b.on_tick(tick(1, 101, 1035, m=1))
    assert closed is not None
    assert (closed.open, closed.high, closed.low, closed.close) == (100, 103, 99, 99)
    assert closed.volume == 30  # first tick contributes 0 (unknown prior cumulative)
    assert closed.ts == at(9, 15)


def test_builder_drops_duplicates_and_out_of_order_deterministically():
    b = CandleBuilder("X", "T")
    b.on_tick(tick(10, 100, 5))
    b.on_tick(tick(10, 100, 5))  # exact duplicate
    b.on_tick(tick(5, 99, 6))  # older than newest accepted
    assert b.dropped_duplicates == 1 and b.dropped_out_of_order == 1
    assert b.current.low == 100 and b.current.close == 100


def test_builder_uses_receive_time_only_when_exchange_ts_missing_and_counts_it():
    b = CandleBuilder("X", "T")
    b.on_tick(tick(10, 100, ex=False))
    assert b.ticks_without_exchange_ts == 1


def test_builder_never_fabricates_missing_minutes():
    b = CandleBuilder("X", "T")
    b.on_tick(tick(1, 100, 1))
    b.on_tick(tick(1, 101, 2, m=3))  # minutes 1 and 2 never traded / disconnected
    cs = b.closed_list()
    assert [c.ts.minute for c in cs] == [15]


def mk(minute, price=100.0, vol=10.0, day=MON):
    ts = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST) + timedelta(minutes=minute)
    return Candle(instrument_id="X", timeframe="1m", ts=ts, open=price, high=price + 1, low=price - 1, close=price + 0.5, volume=vol)


def test_resample_aligns_to_0915_and_closes_only_complete_buckets():
    cs = [mk(i, 100 + i) for i in range(12)]  # 09:15..09:26
    five = resample(cs, "5m")
    assert [c.ts.strftime("%H:%M") for c in five] == ["09:15", "09:20"]  # 09:25 bucket still forming
    assert five[0].open == 100 and five[0].close == 104.5 and five[0].volume == 50
    assert all(c.quality == "ok" for c in five)
    fifteen = resample([mk(i) for i in range(30)], "15m")
    assert [c.ts.strftime("%H:%M") for c in fifteen] == ["09:15", "09:30"]


def test_resample_marks_gaps_instead_of_filling():
    cs = [mk(i) for i in range(10) if i != 2]
    five = resample(cs, "5m")
    assert five[0].quality == "gap"
    assert five[0].volume == 40  # 4 candles, nothing invented


def test_resample_does_not_mix_days():
    cs = [mk(i, day=date(2026, 10, 23)) for i in range(5)] + [mk(i) for i in range(5)]
    five = resample(cs, "5m")
    assert [c.ts.date() for c in five] == [date(2026, 10, 23), MON]
