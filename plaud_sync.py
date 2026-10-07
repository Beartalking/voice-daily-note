#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Plaud cloud -> local, split by whether Plaud has a transcript.

  no transcript  -> solo dictation: download audio, convert to m4a, drop into
                    ~/Desktop/capture/ for pipeline A (run separately)
  has transcript -> conversation: transcript (speaker-labelled) + all summaries
                    as one note in 23_Meetings/, never transcribed locally

Only recordings that ended at least PLAUD_MIN_AGE_HOURS ago are touched, so
there is time to trigger transcription in the Plaud app first. Runs at 08:30
and 20:30, so the evening run picks up the day's recordings up to ~18:30.

Usage:
    python3 plaud_sync.py              # process new recordings
    python3 plaud_sync.py --dry-run    # show routing, write nothing
    python3 plaud_sync.py --id of_xxx  # one recording (ignores the age cutoff)
    python3 plaud_sync.py --seed       # mark everything in Plaud as processed

Exit codes: 0 ok, 1 some recordings failed, 2 Plaud login expired.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from config import (
    PLAUD_LEDGER,
    PLAUD_LOCK,
    PLAUD_LOOKBACK_DAYS,
    PLAUD_MIN_AGE_HOURS,
    PLAUD_MEETINGS_DIR,
    RECORDING_DIR,
)

PLAUD_BIN = os.environ.get("PLAUD_BIN", "plaud")
AUTH_EXPIRED = 2  # plaud CLI exit code for an expired login

ID_RE = re.compile(r"\b(of_[0-9a-f]{32})\b")
FIELD_RE = re.compile(r"^\s{2}(\w+):\s+(.*)$")
URL_RE = re.compile(r"https://\S+")
# Untitled recordings are named after their own start time; no point repeating it.
UNTITLED_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
UNSAFE_CHARS_RE = re.compile(r'[/\\:*?"<>|\n\r\t]+')
# `plaud file` duration, e.g. "1m51s", "1h2m3s", "45s"
DURATION_RE = re.compile(r"^(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?$")


class AuthExpired(Exception):
    pass


class PlaudError(Exception):
    pass


# ── plaud CLI ────────────────────────────────────────────────────────

def _plaud(*args):
    # type: (str) -> str
    proc = subprocess.run(
        [PLAUD_BIN, *args], capture_output=True, text=True, timeout=300
    )
    if proc.returncode == AUTH_EXPIRED:
        raise AuthExpired((proc.stdout + proc.stderr).strip())
    if proc.returncode != 0:
        raise PlaudError(
            "plaud {} -> exit {}: {}".format(
                " ".join(args), proc.returncode, (proc.stdout + proc.stderr).strip()
            )
        )
    return proc.stdout


def list_recent_ids(days):
    # type: (int) -> list[str]
    out = _plaud("recent", "-d", str(days))
    ids = []
    for line in out.splitlines():
        m = ID_RE.search(line)
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def list_all_ids(page_size=100):
    # type: (int) -> list[str]
    """Every recording in the account; `recent` caps out at 365 days."""
    ids = []
    page = 1
    while True:
        found = ID_RE.findall(_plaud("files", "-p", str(page), "-s", str(page_size)))
        ids.extend(i for i in found if i not in ids)
        if len(found) < page_size:
            return ids
        page += 1


def get_file(file_id):
    # type: (str) -> dict
    """Parse `plaud file` key/value output. start_at is UTC without a suffix."""
    fields = {}
    for line in _plaud("file", file_id).splitlines():
        m = FIELD_RE.match(line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    for key in ("id", "name", "start_at", "transcript"):
        if key not in fields:
            raise PlaudError("plaud file {}: missing '{}' in output".format(file_id, key))
    start_utc = datetime.fromisoformat(fields["start_at"]).replace(tzinfo=timezone.utc)
    fields["start_local"] = start_utc.astimezone()  # system zone (Pacific/Auckland)
    fields["end_local"] = fields["start_local"] + parse_duration(fields.get("duration", ""))
    return fields


def parse_duration(text):
    # type: (str) -> timedelta
    """'1h2m3s' -> timedelta. Missing or unparseable -> 0, i.e. age counts from start."""
    m = DURATION_RE.match(text.strip())
    if not text.strip() or not m:
        return timedelta(0)
    h, mi, se = (int(g) if g else 0 for g in m.groups())
    return timedelta(hours=h, minutes=mi, seconds=se)


def too_recent(rec, now):
    # type: (dict, datetime) -> bool
    return now - rec["end_local"] < timedelta(hours=PLAUD_MIN_AGE_HOURS)


# ── naming ───────────────────────────────────────────────────────────

def _clean_name(name, max_len=60):
    # type: (str, int) -> str
    if UNTITLED_RE.match(name):
        return ""
    name = UNSAFE_CHARS_RE.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:max_len].rstrip(" .")


def audio_filename(rec):
    # type: (dict) -> str
    # pipeline A only picks up names containing YYYYMMDD_HHMMSS (transcribe.py);
    # anything else is skipped with a one-line notice.
    stamp = rec["start_local"].strftime("%Y%m%d_%H%M%S")
    name = _clean_name(rec["name"])
    return "PLAUD_{}{}.m4a".format(stamp, "_" + name if name else "")


def meeting_filename(rec):
    # type: (dict) -> str
    # Matches 23_Meetings: "YYYY-MM-DD - <project> - <title>.md". Project is
    # unknown at sync time, so "Plaud" marks it as not yet sorted.
    start = rec["start_local"]
    name = _clean_name(rec["name"], max_len=80) or start.strftime("%H%M 录音")
    return "{} - Plaud - {}.md".format(start.strftime("%Y-%m-%d"), name)


def _unique(path):
    # type: (Path) -> Path
    n = 2
    candidate = path
    while candidate.exists():
        candidate = path.with_name("{} ({}){}".format(path.stem, n, path.suffix))
        n += 1
    return candidate


# ── routes ───────────────────────────────────────────────────────────

def sync_audio(rec, dry_run):
    # type: (dict, bool) -> Optional[Path]
    dest = _unique(RECORDING_DIR / audio_filename(rec))
    if dry_run:
        print("    -> capture/{}".format(dest.name))
        return None
    # The signed URL says "expires in 24 hours" but is signed for 3600s, so
    # fetch it immediately before downloading.
    m = URL_RE.search(_plaud("audio", rec["id"]))
    if not m:
        raise PlaudError("plaud audio {}: no URL in output".format(rec["id"]))
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "audio.ogg"
        with urllib.request.urlopen(m.group(0), timeout=300) as resp, raw.open("wb") as f:
            shutil.copyfileobj(resp, f)
        # Plaud serves Ogg Opus; pipeline A only accepts wav/m4a/mp3.
        m4a = Path(tmp) / "audio.m4a"
        subprocess.run(
            ["afconvert", "-f", "m4af", "-d", "aac", str(raw), str(m4a)],
            check=True, capture_output=True,
        )
        RECORDING_DIR.mkdir(parents=True, exist_ok=True)
        # Move in whole, so pipeline A never sees a half-written file.
        shutil.move(str(m4a), str(dest))
    print("    -> capture/{}".format(dest.name))
    return dest


def build_meeting_note(rec, transcript, summary):
    # type: (dict, str, str) -> str
    start = rec["start_local"]
    title = _clean_name(rec["name"], max_len=200) or start.strftime("%Y-%m-%d %H:%M 录音")
    lines = [
        "---",
        "date: {}".format(start.strftime("%Y-%m-%d")),
        "type: meeting",
        "project: ",
        "participants: []",
        "source: plaud",
        "plaud_id: {}".format(rec["id"]),
        "start: {}".format(start.strftime("%Y-%m-%d %H:%M")),
        "duration: {}".format(rec.get("duration", "")),
        "tags: [plaud]",
        "---",
        "",
        "# {}".format(title),
        "",
        "## Plaud 摘要",
        "",
        summary.strip() or "（无摘要）",
        "",
        "## 转录",
        "",
        transcript.strip(),
        "",
    ]
    return "\n".join(lines)


def sync_meeting(rec, dry_run):
    # type: (dict, bool) -> Optional[Path]
    dest = _unique(PLAUD_MEETINGS_DIR / meeting_filename(rec))
    if dry_run:
        print("    -> 23_Meetings/{}".format(dest.name))
        return None
    with tempfile.TemporaryDirectory() as tmp:
        t_path = Path(tmp) / "transcript.txt"
        s_path = Path(tmp) / "summary.md"
        _plaud("transcript", rec["id"], "-o", str(t_path))
        transcript = t_path.read_text(encoding="utf-8") if t_path.exists() else ""
        if not transcript.strip():
            # `plaud transcript` exits 0 even when there is none.
            raise PlaudError("plaud transcript {}: empty".format(rec["id"]))
        if rec.get("summary") == "available":
            _plaud("summary", rec["id"], "--all", "-o", str(s_path))
        summary = s_path.read_text(encoding="utf-8") if s_path.exists() else ""
    dest.write_text(build_meeting_note(rec, transcript, summary), encoding="utf-8")
    print("    -> 23_Meetings/{}".format(dest.name))
    return dest


# ── ledger / lock ────────────────────────────────────────────────────

def _load_ledger():
    # type: () -> dict
    if PLAUD_LEDGER.exists():
        return json.loads(PLAUD_LEDGER.read_text(encoding="utf-8"))
    return {}


def _save_ledger(ledger):
    # type: (dict) -> None
    tmp = PLAUD_LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PLAUD_LEDGER)


@contextmanager
def _lock():
    """Same pattern as text_inbox: flock, released by the kernel on exit."""
    fd = os.open(str(PLAUD_LOCK), os.O_RDWR | os.O_CREAT, 0o644)
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


# ── run ──────────────────────────────────────────────────────────────

def seed(dry_run):
    # type: (bool) -> int
    """Mark every recording currently in Plaud as processed, without fetching."""
    ledger = _load_ledger()
    ids = list_all_ids()
    new = [i for i in ids if i not in ledger]
    now = datetime.now().isoformat(timespec="seconds")
    for i in new:
        ledger[i] = {"route": "seed", "at": now}
    print("  seed: {} recordings in Plaud, {} newly marked".format(len(ids), len(new)))
    if not dry_run:
        _save_ledger(ledger)
    return 0


def run(only_id=None, dry_run=False):
    # type: (Optional[str], bool) -> int
    ledger = _load_ledger()
    now = datetime.now().astimezone()
    ids = [only_id] if only_id else list_recent_ids(PLAUD_LOOKBACK_DAYS)
    ok = skipped = failed = 0

    for file_id in ids:
        if file_id in ledger and not only_id:
            continue
        try:
            rec = get_file(file_id)
            if not only_id and too_recent(rec, now):
                skipped += 1  # leave time to transcribe in the app
                continue
            has_transcript = rec["transcript"] == "available"
            route = "meeting" if has_transcript else "audio"
            print("  {}  {}  {}  [{}]".format(
                file_id, rec["start_local"].strftime("%Y-%m-%d %H:%M"), rec["name"], route))
            if has_transcript:
                dest = sync_meeting(rec, dry_run)
            else:
                dest = sync_audio(rec, dry_run)
            if not dry_run:
                ledger[file_id] = {
                    "route": route,
                    "path": str(dest),
                    "at": datetime.now().isoformat(timespec="seconds"),
                }
                _save_ledger(ledger)  # per item, so a later failure keeps earlier work
            ok += 1
        except AuthExpired:
            raise
        except Exception as e:  # one bad recording must not stop the batch
            failed += 1
            print("  [FAILED] {}: {}".format(file_id, e))

    print("  Plaud sync: {} synced, {} too recent (held), {} failed".format(ok, skipped, failed))
    return 1 if failed else 0


def main():
    # type: () -> int
    p = argparse.ArgumentParser(description="Sync Plaud recordings to capture / 23_Meetings")
    p.add_argument("--dry-run", action="store_true", help="show routing, write nothing")
    p.add_argument("--id", help="process one recording (ignores the age cutoff)")
    p.add_argument("--seed", action="store_true",
                   help="mark every recording in Plaud as processed")
    args = p.parse_args()

    try:
        if args.dry_run:
            # Writes nothing, so it needs no lock and cannot block a real run.
            return seed(True) if args.seed else run(args.id, True)
        with _lock() as acquired:
            if not acquired:
                print("  [LOCKED] another plaud_sync run is in progress, skipping")
                return 0
            return seed(False) if args.seed else run(args.id, False)
    except AuthExpired as e:
        print("  [AUTH] Plaud login expired, run `plaud login`. ({})".format(e))
        return AUTH_EXPIRED


if __name__ == "__main__":
    sys.exit(main())
