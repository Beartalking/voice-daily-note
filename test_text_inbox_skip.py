#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained regression check for the 09:30 iCloud-placeholder crash.

This repo has no test suite and no test framework installed (no tests/
directory, no pytest config, no requirements.txt entry for it) — so this is
a plain script, not a pytest file. Run it directly:

    python3 test_text_inbox_skip.py

It exits 0 and prints "OK" on success, or prints a traceback and exits 1.

What it checks: one file in the inbox is an iCloud placeholder that raises
OSError(11, "Resource deadlock avoided") when read (simulated by
monkeypatching Path.read_bytes for that one filename). Before the fix, that
exception was unhandled and killed process_inbox() entirely, so every other
file in the batch went unprocessed. After the fix, that one file is skipped
and every other file in the same run still completes normally.

Nothing real is touched: TEXT_INBOX_DIR, PROCESSED_DIR, TEXT_INBOX_LEDGER,
get_daily_note_path, write_daily_note, _call_claude and get_api_key are all
monkeypatched to a throwaway temp directory / fakes for the duration of the
check, then restored in a finally block. No network call, no write into the
real Obsidian vault, no touch of the real ledger.
"""
from __future__ import annotations

import io
import shutil
import tempfile
import traceback
from contextlib import redirect_stdout
from pathlib import Path

import text_inbox


def _make_inbox(inbox_dir):
    # type: (Path) -> tuple[Path, Path, Path]
    """Create 3 inbox files; the middle one (by sorted filename order) is the
    'iCloud placeholder' that will fail to read. Ordering matters: it proves
    files both before *and* after the crash point still get processed.
    """
    good1 = inbox_dir / "2026-08-01_090000.md"
    bad = inbox_dir / "2026-08-01_091000.md"
    good2 = inbox_dir / "2026-08-01_092000.md"
    good1.write_text("First normal note.", encoding="utf-8")
    bad.write_text("Placeholder content (will fail to read).", encoding="utf-8")
    good2.write_text("Second normal note.", encoding="utf-8")
    return good1, bad, good2


def test_icloud_placeholder_file_is_skipped_others_still_process():
    tmp_dir = Path(tempfile.mkdtemp(prefix="text_inbox_check_"))
    inbox_dir = tmp_dir / "inbox"
    inbox_dir.mkdir()
    good1, bad_file, good2 = _make_inbox(inbox_dir)

    real_read_bytes = Path.read_bytes

    def flaky_read_bytes(self):
        if self.name == bad_file.name:
            raise OSError(11, "Resource deadlock avoided")
        return real_read_bytes(self)

    fake_responses = iter([
        "TITLE: First\nSCENE: test\nTAGS: \nBODY:\nFirst normal note.",
        "TITLE: Second\nSCENE: test\nTAGS: \nBODY:\nSecond normal note.",
    ])
    written_notes = []

    originals = dict(
        TEXT_INBOX_DIR=text_inbox.TEXT_INBOX_DIR,
        PROCESSED_DIR=text_inbox.PROCESSED_DIR,
        TEXT_INBOX_LEDGER=text_inbox.TEXT_INBOX_LEDGER,
        get_daily_note_path=text_inbox.get_daily_note_path,
        write_daily_note=text_inbox.write_daily_note,
        _call_claude=text_inbox._call_claude,
        get_api_key=text_inbox.get_api_key,
        Path_read_bytes=Path.read_bytes,
    )

    try:
        text_inbox.TEXT_INBOX_DIR = inbox_dir
        text_inbox.PROCESSED_DIR = inbox_dir / "processed"
        text_inbox.TEXT_INBOX_LEDGER = tmp_dir / ".ledger.json"
        text_inbox.get_daily_note_path = lambda date_str: tmp_dir / "notes" / (date_str + ".md")
        text_inbox.write_daily_note = (
            lambda date, count, text, append=False:
            written_notes.append((date, text)) or (tmp_dir / "notes" / (date + ".md"))
        )
        text_inbox._call_claude = lambda api_key, text: next(fake_responses, None)
        text_inbox.get_api_key = lambda: "fake-key-for-test"
        Path.read_bytes = flaky_read_bytes

        buf = io.StringIO()
        with redirect_stdout(buf):
            success, skipped, failed = text_inbox.process_inbox(force=False, dry_run=False)
        output = buf.getvalue()
    finally:
        text_inbox.TEXT_INBOX_DIR = originals["TEXT_INBOX_DIR"]
        text_inbox.PROCESSED_DIR = originals["PROCESSED_DIR"]
        text_inbox.TEXT_INBOX_LEDGER = originals["TEXT_INBOX_LEDGER"]
        text_inbox.get_daily_note_path = originals["get_daily_note_path"]
        text_inbox.write_daily_note = originals["write_daily_note"]
        text_inbox._call_claude = originals["_call_claude"]
        text_inbox.get_api_key = originals["get_api_key"]
        Path.read_bytes = originals["Path_read_bytes"]
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # The run must not abort, and must not report the batch as a failure.
    assert failed == 0, "expected 0 failed, got %d\n%s" % (failed, output)
    # The two readable files must still be fully processed (not merely skipped).
    assert success == 2, "expected 2 successful, got %d\n%s" % (success, output)
    assert skipped == 1, "expected exactly 1 skip (the iCloud placeholder), got %d\n%s" % (skipped, output)
    assert len(written_notes) == 2, "both readable files should have reached write_daily_note"
    assert written_notes[0][1].split("\n")[0] == "## First"
    assert written_notes[1][1].split("\n")[0] == "## Second"

    # The skip message must be distinctly greppable and plainly say this is
    # an iCloud availability issue, not a parse failure.
    assert "2026-08-01_091000.md" in output
    assert "NOT AVAILABLE LOCALLY" in output, "skip message must be greppable\n%s" % output
    assert "iCloud" in output, "skip message must plainly name iCloud\n%s" % output
    assert "Resource deadlock avoided" in output, "original OSError text should be preserved\n%s" % output

    # It must not be confusable with the pre-existing "empty file" skip idiom.
    assert "empty file" not in output.split("2026-08-01_091000.md")[1].split("\n")[0]


def main():
    try:
        test_icloud_placeholder_file_is_skipped_others_still_process()
    except AssertionError:
        print("FAILED")
        traceback.print_exc()
        return 1
    except Exception:
        print("ERROR (unexpected exception)")
        traceback.print_exc()
        return 1
    print("OK: iCloud placeholder file was skipped; both other files in the "
          "same run were fully processed; process_inbox() did not abort.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
