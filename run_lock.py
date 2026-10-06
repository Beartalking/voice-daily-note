#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared run lock: one advisory flock per pipeline, so two runs never interleave.

Used by pipeline A (pipeline.py, launchd 09:00 + manual /capture) and pipeline C
(text_inbox.py, launchd 09:30). Each guards its own ledger with its own lock file.

flock is released by the kernel when the process exits, so a crashed or killed
run cannot leave a stale lock that blocks every later run — the classic failure
of PID-file locks, which shows up months later as a pipeline that quietly stopped.
Keep lock files on local disk next to the ledger they guard, never in iCloud:
flock is unreliable on synced paths and only this machine's processes need it.
"""
from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def exclusive_lock(path: Path):
    """Hold an exclusive non-blocking lock on `path` for the duration of the block.

    Yields True when the lock was acquired, False when another run holds it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
