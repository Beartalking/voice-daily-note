#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check that the retired pipeline B refuses to run.

This repo has no test framework installed, so this is a plain script:

    python3 test_share_to_social_retired.py

Exits 0 and prints "OK" on success, or prints a traceback and exits 1.

Why it exists: `share_to_social.py` was replaced on 2026-08-24 by
`content-publisher`'s `import-share`. The file stays for reference, but running
it out of habit would generate duplicate drafts, in the frozen February voice
that caused the two specs to drift apart in the first place. A comment at the
top of the file does not stop that; refusing to run does.

Nothing real is touched: main() must bail out before it reads any note.
"""
from __future__ import annotations

import io
import traceback
from contextlib import redirect_stdout

import share_to_social


def test_main_refuses_to_run_and_says_what_to_use_instead():
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            share_to_social.main()
    except SystemExit as exc:
        code = exc.code
    else:
        raise AssertionError("main() should have exited, it ran instead")

    assert code not in (0, None), f"a refusal must be a non-zero exit, got {code!r}"
    out = buf.getvalue()
    assert "import-share" in out, f"the message must name the replacement, got:\n{out}"
    assert "content-publisher" in out, f"and where it lives, got:\n{out}"


def test_it_bails_out_before_touching_any_note():
    """The guard must sit ahead of the scan, not after it."""
    def explode(*a, **kw):
        raise AssertionError("extraction ran; the guard is in the wrong place")

    real = share_to_social.extract_share_entries_from_daily_notes
    share_to_social.extract_share_entries_from_daily_notes = explode
    try:
        with redirect_stdout(io.StringIO()):
            share_to_social.main()
    except SystemExit:
        pass
    finally:
        share_to_social.extract_share_entries_from_daily_notes = real


def main() -> int:
    try:
        for test in (
            test_main_refuses_to_run_and_says_what_to_use_instead,
            test_it_bails_out_before_touching_any_note,
        ):
            test()
            print(f"  ok  {test.__name__}")
    except Exception:
        traceback.print_exc()
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
