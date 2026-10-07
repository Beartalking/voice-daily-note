#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check that archiving is per file (2026-10-08: one failure used to hold the whole batch).

Plain script like the other test_*.py here; run it directly:

    python3 test_archive_partial.py

It exits 0 and prints "OK" on success. Works in a temp dir: no real
capture/, transcripts/ or ledger is touched.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import transcribe
from pipeline import split_finished
from transcribe import AudioFile


def main():
    # type: () -> int
    with tempfile.TemporaryDirectory() as tmp:
        tdir = Path(tmp)
        with mock.patch.object(transcribe, "TRANSCRIPTS_DIR", tdir):

            def audio(stem):
                return AudioFile(path=tdir / f"{stem}.m4a", date="2026-10-07", time="05:20:38", seq=0)

            refined = audio("PLAUD_20261007_061335")
            (tdir / "PLAUD_20261007_061335.txt").write_text("hello", encoding="utf-8")

            failed = audio("PLAUD_20261007_052038")  # transcription failed: no .txt

            unrefined = audio("PLAUD_20261007_150705")  # transcribed, refine failed
            (tdir / "PLAUD_20261007_150705.txt").write_text("hi", encoding="utf-8")

            empty = audio("PLAUD_20261007_191918")  # silent recording: nothing to refine
            (tdir / "PLAUD_20261007_191918.txt").write_text("  \n", encoding="utf-8")

            other_day = AudioFile(path=tdir / "x.m4a", date="2026-10-06", time="07:00:00", seq=0)
            (tdir / "x.txt").write_text("hey", encoding="utf-8")

            ledger = {
                "2026-10-07": ["PLAUD_20261007_061335.txt"],
                # Listed under the wrong day: must not count as refined.
                "2026-10-08": ["x.txt"],
            }

            done, pending = split_finished([refined, failed, unrefined, empty, other_day], ledger)

    assert done == [refined, empty], done
    assert pending == [failed, unrefined, other_day], pending

    print("OK: only finished audio is archived; failed ones stay in capture/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
