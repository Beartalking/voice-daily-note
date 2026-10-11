#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained regression check: write_daily_note never overwrites a note.

Plain script like the other test_*.py here (no test framework installed):

    python3 test_daily_note_no_clobber.py

It exits 0 and prints "OK" on success, or prints a traceback and exits 1.

What it checks: 2026-10-04's note was created by morning-pages, then refine
wrote that date's first voice transcript with append=False (empty ledger) and
the Morning Pages block vanished. With an existing note, append=False must
append like append=True; with no note, it still creates one with front matter.

OUTPUT_DIR is pointed at a throwaway temp directory; the real vault is never
touched.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import traceback
from pathlib import Path

import daily_note_writer


def main():
    tmp = Path(tempfile.mkdtemp())
    original = daily_note_writer.OUTPUT_DIR
    daily_note_writer.OUTPUT_DIR = tmp
    try:
        note = daily_note_writer.get_daily_note_path("2026-10-04")
        note.parent.mkdir(parents=True)
        note.write_text("## Morning Pages 2026-10-04\n\nhandwritten\n", encoding="utf-8")

        daily_note_writer.write_daily_note("2026-10-04", 1, "## Voice entry\n", append=False)
        text = note.read_text(encoding="utf-8")
        assert "## Morning Pages 2026-10-04" in text, text
        assert text.rstrip().endswith("## Voice entry"), text
        assert "entries:" not in text, text

        fresh = daily_note_writer.write_daily_note("2026-10-05", 2, "## New\n", append=False)
        assert fresh.read_text(encoding="utf-8").startswith(
            "---\ndate: 2026-10-05\ntype: daily-note\nentries: 2\n---\n\n"
        )
    finally:
        daily_note_writer.OUTPUT_DIR = original
        shutil.rmtree(tmp)
    print("OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
