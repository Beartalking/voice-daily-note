#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check Plaud routing (2026-10-27: long recordings without a Plaud transcript
are transcribed locally into 23_Meetings instead of entering the diary path).

Plain script like the other test_*.py here; run it directly:

    python3 test_plaud_route.py

It exits 0 and prints "OK" on success. Pure functions only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config import PLAUD_LOCAL_MEETING_MINUTES
from plaud_sync import choose_route, format_segments


def _rec(minutes, transcript):
    start = datetime(2026, 10, 27, 11, 6, tzinfo=timezone(timedelta(hours=13)))
    return {"transcript": transcript, "start_local": start,
            "end_local": start + timedelta(minutes=minutes)}


def main():
    # type: () -> int
    n = PLAUD_LOCAL_MEETING_MINUTES
    assert choose_route(_rec(78, "available")) == "meeting"
    assert choose_route(_rec(2, "available")) == "meeting"
    assert choose_route(_rec(78, "unavailable")) == "local-meeting"
    assert choose_route(_rec(n, "unavailable")) == "local-meeting"
    assert choose_route(_rec(n - 1, "unavailable")) == "audio"
    assert choose_route(_rec(0, "unavailable")) == "audio"  # duration unparseable

    segs = [{"start": 0.0, "text": " Hi Ingrid "}, {"start": 61.4, "text": "  "},
            {"start": 3725.9, "text": "Bye."}]
    assert format_segments(segs) == "[0:00:00] Hi Ingrid\n[1:02:05] Bye."
    assert format_segments([]) == ""
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
