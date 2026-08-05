#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained regression check for the concurrent-run double-append bug.

This repo has no test suite and no test framework installed, so this is a
plain script, not a pytest file. Run it directly:

    python3 test_text_inbox_lock.py

It exits 0 and prints "OK" on success, or prints a traceback and exits 1.

What it checks (the bug, observed 2026-08-06): launchd runs pipeline C daily
at 09:30. A manual run starting in the same minute raced it — both loaded the
ledger before either wrote it back, so neither saw the other's work and
2026-08-04_220755.txt was appended to the daily note twice.

Four properties of the fix:
  1. While another process holds the lock, process_inbox() does not run the
     body at all (no ledger read, no append) and reports (0, 0, 0).
  2. A SIGKILLed holder leaves no stale lock — flock is released by the kernel,
     so the next run is not blocked forever.
  3. A normal run acquires and releases cleanly.
  4. --dry-run bypasses the lock entirely: it writes nothing, so it must
     neither be blocked by nor block a real run.

Nothing real is touched: the body of the run (_process_inbox) is monkeypatched
to a recording fake, so no network call, no ledger write and no write into the
real Obsidian vault. Only the lock file itself is created, which is what is
under test.
"""
from __future__ import annotations

import io
import signal
import subprocess
import sys
import time
import traceback
from contextlib import redirect_stdout
from pathlib import Path

import text_inbox
from config import TEXT_INBOX_LOCK

HOLDER_SRC = (
    "import sys, time, text_inbox\n"
    "cm = text_inbox._inbox_lock()\n"
    "got = cm.__enter__()\n"
    "assert got is True, 'holder failed to acquire lock'\n"
    "print('HELD', flush=True)\n"
    "time.sleep(30)\n"
)


def _start_holder():
    """Spawn a process that grabs the lock and sits on it. Returns the Popen."""
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


def _call_process_inbox(**kwargs):
    """Call process_inbox with the body faked out. Returns (result, calls, out)."""
    calls = []

    def fake_body(force=False, dry_run=False):
        calls.append({"force": force, "dry_run": dry_run})
        return (99, 99, 99)  # sentinel: only visible if the body actually ran

    real_body = text_inbox._process_inbox
    text_inbox._process_inbox = fake_body
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            result = text_inbox.process_inbox(**kwargs)
    finally:
        text_inbox._process_inbox = real_body
    return result, calls, buf.getvalue()


def _lock_is_free():
    """True if the lock can be acquired right now."""
    with text_inbox._inbox_lock() as acquired:
        return acquired


def main():
    holder = None
    try:
        # --- 1. contended real run: body must not execute -------------------
        holder = _start_holder()
        result, calls, out = _call_process_inbox()
        assert result == (0, 0, 0), f"expected (0,0,0) when locked, got {result}"
        assert calls == [], f"body ran while another process held the lock: {calls}"
        assert "[LOCKED]" in out, f"no [LOCKED] notice printed, got: {out!r}"

        # --- 4. dry-run bypasses the lock (checked while still contended) ----
        result, calls, out = _call_process_inbox(dry_run=True)
        assert len(calls) == 1, f"dry-run was blocked by the lock: {calls}"
        assert calls[0]["dry_run"] is True, f"dry_run flag not passed: {calls}"
        assert result == (99, 99, 99), f"dry-run did not reach the body: {result}"

        # --- 2. SIGKILLed holder leaves no stale lock -----------------------
        holder.send_signal(signal.SIGKILL)
        holder.wait(timeout=10)
        holder = None
        deadline = time.time() + 5
        while time.time() < deadline and not _lock_is_free():
            time.sleep(0.05)
        assert _lock_is_free(), "lock still held after the holder was SIGKILLed"

        # --- 3. uncontended run acquires, runs the body, releases -----------
        result, calls, out = _call_process_inbox()
        assert len(calls) == 1, f"body did not run when lock was free: {calls}"
        assert result == (99, 99, 99), f"body result not returned: {result}"
        assert "[LOCKED]" not in out, f"reported LOCKED when free: {out!r}"
        assert _lock_is_free(), "lock not released after a normal run"

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
        "OK: a second concurrent run is blocked and does nothing; a SIGKILLed "
        "holder leaves no stale lock; an uncontended run acquires and releases; "
        f"--dry-run is not blocked. Lock file: {TEXT_INBOX_LOCK}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
