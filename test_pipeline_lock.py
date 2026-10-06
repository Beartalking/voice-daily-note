#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained check for pipeline A's run lock and exit code (2026-10-06).

Plain script, no framework, same as test_text_inbox_lock.py. Run it directly:

    python3 test_pipeline_lock.py

It exits 0 and prints "OK" on success, or prints the failure and exits 1.

Why: from 2026-10-06 launchd runs pipeline.py daily at 09:00 (run_capture.sh)
while Bear still runs /capture by hand. Both read and write .refined_ledger.json,
the exact race that double-appended a text inbox entry on 2026-08-06. And the
launchd wrapper can only raise a failure notification if the pipeline's exit
code means something; before this change it was always 0.

Properties checked:
  1. While another process holds .pipeline.lock, main() skips the run body
     entirely, prints [LOCKED] and returns 0 (a skipped run is not a failure).
  2. A SIGKILLed holder leaves no stale lock.
  3. An uncontended run acquires, runs the body, returns its code, releases.
  4. --dry-run bypasses the lock: it writes nothing, so it must not be blocked.
  5. _run() maps failures to exit 1 (checked via the body's return passthrough).

Nothing real is touched: _run is monkeypatched to a recording fake and
ensure_dirs to a no-op, so no transcription, no API call, no vault write.
Only the lock file itself is created, which is what is under test.
"""
from __future__ import annotations

import io
import subprocess
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path

import pipeline
from config import PIPELINE_LOCK
from run_lock import exclusive_lock

HOLDER_SRC = (
    "import time\n"
    "from config import PIPELINE_LOCK\n"
    "from run_lock import exclusive_lock\n"
    "cm = exclusive_lock(PIPELINE_LOCK)\n"
    "got = cm.__enter__()\n"
    "assert got is True, 'holder failed to acquire lock'\n"
    "print('HELD', flush=True)\n"
    "time.sleep(30)\n"
)


def _start_holder():
    proc = subprocess.Popen(
        [sys.executable, "-c", HOLDER_SRC],
        cwd=str(Path(__file__).parent),
        stdout=subprocess.PIPE,
        text=True,
    )
    line = proc.stdout.readline().strip()
    if line != "HELD":
        proc.kill()
        raise AssertionError(f"holder did not acquire lock, said: {line!r}")
    return proc


def _call_main(argv, body_rc=0):
    """Call pipeline.main() with the body faked out. Returns (rc, calls, out)."""
    calls = []

    def fake_run(args):
        calls.append({"dry_run": args.dry_run})
        return body_rc

    real_run, real_dirs, real_argv = pipeline._run, pipeline.ensure_dirs, sys.argv
    pipeline._run = fake_run
    pipeline.ensure_dirs = lambda: None
    sys.argv = ["pipeline.py"] + argv
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = pipeline.main()
    finally:
        pipeline._run, pipeline.ensure_dirs, sys.argv = real_run, real_dirs, real_argv
    return rc, calls, buf.getvalue()


def _lock_is_free():
    with exclusive_lock(PIPELINE_LOCK) as acquired:
        return acquired


def main():
    holder = None
    try:
        # --- 1. contended: body never runs, LOCKED, exit 0 ------------------
        holder = _start_holder()
        rc, calls, out = _call_main([])
        assert calls == [], f"body ran while another process held the lock: {calls}"
        assert "[LOCKED]" in out, f"no [LOCKED] notice: {out!r}"
        assert rc == 0, f"a skipped run should exit 0, got {rc}"

        # --- 4. dry-run is not blocked by a held lock -----------------------
        rc, calls, out = _call_main(["--dry-run"])
        assert calls == [{"dry_run": True}], f"dry-run was blocked: {calls}"

        # --- 2. SIGKILLed holder leaves no stale lock -----------------------
        holder.kill()
        holder.wait(timeout=10)
        holder = None
        assert _lock_is_free(), "lock still held after the holder was killed"

        # --- 3. uncontended: runs body, passes rc through, releases ---------
        rc, calls, out = _call_main([])
        assert len(calls) == 1, f"body did not run when lock was free: {calls}"
        assert rc == 0 and "[LOCKED]" not in out, f"rc={rc} out={out!r}"
        assert _lock_is_free(), "lock not released after a normal run"

        # --- 5. a failing body surfaces as exit 1 ---------------------------
        rc, calls, out = _call_main([], body_rc=1)
        assert rc == 1, f"failure not propagated: rc={rc}"
        assert _lock_is_free(), "lock not released after a failing run"

    except AssertionError as e:
        print(f"FAIL: {e}")
        return 1
    except Exception:
        print("ERROR (unexpected exception)")
        traceback.print_exc()
        return 1
    finally:
        if holder is not None:
            holder.kill()
            holder.wait(timeout=10)

    print(
        "OK: a concurrent run is skipped with exit 0; --dry-run is not blocked; "
        "a SIGKILLed holder leaves no stale lock; an uncontended run acquires, "
        f"passes its exit code through and releases. Lock file: {PIPELINE_LOCK}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
