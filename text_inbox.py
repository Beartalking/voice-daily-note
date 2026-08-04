#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pipeline C: Text Inbox -> Obsidian Daily Notes.

Reads text files from an iCloud-synced inbox folder, calls Claude to generate
title/scene/tags, then appends formatted entries to the correct daily note.

Usage:
    python3 text_inbox.py              # process all new files
    python3 text_inbox.py --dry-run    # preview only
    python3 text_inbox.py --force      # reprocess all
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

import requests

from config import (
    ANTHROPIC_API_URL,
    ANTHROPIC_API_VERSION,
    CLAUDE_MODEL,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    TEXT_INBOX_DIR,
    TEXT_INBOX_LEDGER,
    get_api_key,
)
from daily_note_writer import get_daily_note_path, write_daily_note
from text_inbox_prompt import SYSTEM_PROMPT

PROCESSED_DIR = TEXT_INBOX_DIR / "processed"


def _load_ledger():
    # type: () -> dict
    """Load the set of inbox filenames already processed, keyed by date."""
    if TEXT_INBOX_LEDGER.exists():
        return json.loads(TEXT_INBOX_LEDGER.read_text(encoding="utf-8"))
    return {}


def _save_ledger(ledger):
    # type: (dict) -> None
    TEXT_INBOX_LEDGER.write_text(
        json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _parse_filename(filename):
    # type: (str) -> tuple[str, str] | None
    """Parse date and time from inbox filename.

    Supports formats:
        YYYY-MM-DD_HHmmss.md  (from Drafts action)
        YYYY-MM-DD_HHmmss.txt
        YYYY-MM-DD.md          (date only, use current time)

    Returns (date_str, time_str) or None if unparseable.
    """
    stem = Path(filename).stem

    # Try YYYY-MM-DD_HHmmss
    m = re.match(r"(\d{4}-\d{2}-\d{2})_(\d{6})$", stem)
    if m:
        date_str = m.group(1)
        raw_time = m.group(2)
        time_str = f"{raw_time[:2]}:{raw_time[2:4]}:{raw_time[4:6]}"
        return date_str, time_str

    # Try YYYY-MM-DD only
    m = re.match(r"(\d{4}-\d{2}-\d{2})$", stem)
    if m:
        return m.group(1), datetime.now().strftime("%H:%M:%S")

    return None


def _read_text(p):
    # type: (Path) -> str
    """Read text file with encoding fallback."""
    data = p.read_bytes()
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _call_claude(api_key, text):
    # type: (str, str) -> str | None
    """Call Claude API to generate metadata for the text."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": text}],
    }

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                ANTHROPIC_API_URL,
                headers=headers,
                json=payload,
                timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                blocks = [
                    b["text"] for b in data.get("content", []) if b.get("type") == "text"
                ]
                return "\n".join(blocks)

            if resp.status_code in (429, 500, 502, 503, 529):
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"    API {resp.status_code}, retrying in {delay}s...")
                time.sleep(delay)
                continue

            print(f"    API error {resp.status_code}: {resp.text[:300]}")
            return None

        except requests.exceptions.Timeout:
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            print(f"    API timeout, retrying in {delay}s...")
            time.sleep(delay)
            continue
        except requests.exceptions.RequestException as e:
            print(f"    API request error: {e}")
            return None

    print("    API failed after all retries")
    return None


def _parse_response(response):
    # type: (str) -> tuple[str, str, str, str] | None
    """Parse Claude's structured response into (title, scene, tags, body).

    Returns None if parsing fails.
    """
    title = scene = tags = ""
    body_lines = []
    in_body = False

    for line in response.split("\n"):
        if line.startswith("TITLE:"):
            title = line[len("TITLE:"):].strip()
        elif line.startswith("SCENE:"):
            scene = line[len("SCENE:"):].strip()
        elif line.startswith("TAGS:"):
            tags = line[len("TAGS:"):].strip()
        elif line.startswith("BODY:"):
            in_body = True
        elif in_body:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()

    if not title or not body:
        return None

    return title, scene, tags, body


def _format_entry(title, scene, tags, time_str, body):
    # type: (str, str, str, str, str) -> str
    """Format a single daily note entry."""
    lines = [
        f"## {title}",
        f"**场景**：{scene}",
        f"**标签**： {tags}",
        f"**记录时间**：{time_str}",
        "",
        "---",
        body,
    ]
    return "\n".join(lines)


def discover_inbox_files():
    # type: () -> list[Path]
    """Find all .md and .txt files anywhere under the inbox directory.

    Scans recursively so files are still picked up even if the upstream
    Shortcut nests them under an extra sub-path. Observed in the field: a
    doubled `Obsidian/Bear Vault/_inbox/text/` tree when the Shortcut's
    hard-coded sub-path is appended onto an already-deep destination folder.
    Anything under `processed/` is excluded.
    """
    if not TEXT_INBOX_DIR.exists():
        return []
    files = []
    for ext in ("*.md", "*.txt"):
        for p in TEXT_INBOX_DIR.rglob(ext):
            if p.parent == PROCESSED_DIR or PROCESSED_DIR in p.parents:
                continue
            files.append(p)
    return sorted(files, key=lambda p: p.name)


def _prune_empty_dirs():
    # type: () -> None
    """Remove empty sub-directories left under the inbox (e.g. the nested
    Obsidian/Bear Vault/_inbox/text tree some Shortcut configs create).
    Deepest first; never touches processed/ or the inbox root itself.
    """
    subdirs = [p for p in TEXT_INBOX_DIR.rglob("*") if p.is_dir()]
    for d in sorted(subdirs, key=lambda p: len(p.parts), reverse=True):
        if d == PROCESSED_DIR or PROCESSED_DIR in d.parents:
            continue
        try:
            d.rmdir()  # only succeeds when empty
        except OSError:
            pass


def process_inbox(force=False, dry_run=False):
    # type: (bool, bool) -> tuple[int, int, int]
    """Process all inbox files.

    Returns (success_count, skipped_count, failed_count).
    """
    TEXT_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    files = discover_inbox_files()
    if not files:
        print("  No files in inbox")
        return 0, 0, 0

    ledger = _load_ledger()
    api_key = None
    if not dry_run:
        api_key = get_api_key()

    success = 0
    skipped = 0
    failed = 0

    for f in files:
        fname = f.name

        # Check ledger
        if not force and fname in ledger.get("processed", []):
            print(f"  [SKIP] {fname}: already processed")
            skipped += 1
            continue

        # Parse filename for date/time
        parsed = _parse_filename(fname)
        if parsed is None:
            print(f"  [SKIP] {fname}: cannot parse date from filename")
            skipped += 1
            continue

        date_str, time_str = parsed

        # iCloud may not have materialised this file locally yet (placeholder
        # file): reading it raises OSError [Errno 11] Resource deadlock avoided.
        # That's transient — the ledger means it'll be picked up on a later run
        # — so skip just this file rather than aborting the whole batch.
        try:
            raw_text = _read_text(f).strip()
        except OSError as e:
            print(f"  [SKIP] {fname}: NOT AVAILABLE LOCALLY (iCloud has not downloaded this file yet) — {e}")
            skipped += 1
            continue

        if not raw_text:
            print(f"  [SKIP] {fname}: empty file")
            skipped += 1
            continue

        # Check if daily note already exists (for append mode)
        note_path = get_daily_note_path(date_str)
        append_mode = note_path.exists()
        action = "APPEND" if append_mode else "CREATE"

        if dry_run:
            print(
                f"  [DRY-RUN] {fname} -> {date_str} {time_str} "
                f"({len(raw_text)} chars) -> {action}"
            )
            skipped += 1
            continue

        print(f"  Processing: {fname} ({date_str} {time_str})")

        # Call Claude for metadata
        response = _call_claude(api_key, raw_text)
        if not response:
            print(f"    FAILED: No API response for {fname}")
            failed += 1
            continue

        parsed_resp = _parse_response(response)
        if parsed_resp is None:
            print(f"    FAILED: Could not parse API response for {fname}")
            print(f"    Raw response:\n{response[:500]}")
            failed += 1
            continue

        title, scene, tags, body = parsed_resp
        entry = _format_entry(title, scene, tags, time_str, body)

        # Write to daily note
        out = write_daily_note(date_str, 1, entry, append=append_mode)
        print(f"    -> {out.name}" + (" [APPENDED]" if append_mode else ""))

        # Update ledger
        processed_list = ledger.get("processed", [])
        processed_list.append(fname)
        ledger["processed"] = sorted(set(processed_list))
        _save_ledger(ledger)

        # Move to processed folder
        dest = PROCESSED_DIR / fname
        if dest.exists():
            dest = PROCESSED_DIR / f"{Path(fname).stem}_{int(time.time())}{Path(fname).suffix}"
        shutil.move(str(f), str(dest))

        success += 1

    if not dry_run:
        _prune_empty_dirs()

    return success, skipped, failed


def main():
    parser = argparse.ArgumentParser(
        description="Text Inbox: process text files into Obsidian Daily Notes"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without processing"
    )
    parser.add_argument(
        "--force", action="store_true", help="Reprocess all files (ignore ledger)"
    )
    args = parser.parse_args()

    print("Text Inbox Pipeline")
    print(f"  Inbox: {TEXT_INBOX_DIR}")
    print("=" * 50)

    success, skipped, failed = process_inbox(
        force=args.force, dry_run=args.dry_run
    )

    print("=" * 50)
    print(f"  Processed: {success}, Skipped: {skipped}, Failed: {failed}")


if __name__ == "__main__":
    main()
