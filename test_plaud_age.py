#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check for the Plaud age cutoff (2026-10-07: "before today" -> "ended >= 2h ago").

Plain script like the other test_*.py here; run it directly:

    python3 test_plaud_age.py

It exits 0 and prints "OK" on success. Pure functions only: no plaud CLI,
no network, no ledger.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config import PLAUD_MIN_AGE_HOURS
from plaud_sync import parse_duration, too_recent


def main():
    # type: () -> int
    assert parse_duration("1m51s") == timedelta(minutes=1, seconds=51)
    assert parse_duration("1h2m3s") == timedelta(hours=1, minutes=2, seconds=3)
    assert parse_duration("45s") == timedelta(seconds=45)
    assert parse_duration("2h") == timedelta(hours=2)
    assert parse_duration("") == timedelta(0)
    assert parse_duration("garbage") == timedelta(0)

    tz = timezone(timedelta(hours=13))  # NZDT
    now = datetime(2026, 10, 7, 20, 30, tzinfo=tz)
    min_age = timedelta(hours=PLAUD_MIN_AGE_HOURS)

    def rec(end):
        return {"end_local": end}

    # Evening run: same-day recording that ended long enough ago is picked up.
    assert not too_recent(rec(now - min_age - timedelta(minutes=1)), now)
    assert not too_recent(rec(now - min_age), now)
    # Ended inside the window: held for the next run.
    assert too_recent(rec(now - min_age + timedelta(minutes=1)), now)
    # A long meeting that started early but ended recently is still held.
    start = now - timedelta(hours=3)
    assert too_recent(rec(start + parse_duration("2h30m")), now)

    print("OK: duration parsing and the {}h age cutoff behave".format(PLAUD_MIN_AGE_HOURS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
