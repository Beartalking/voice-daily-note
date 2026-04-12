#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 2: Group transcripts by date, call Claude API for refinement, output MD files."""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

import requests

from config import (
    ANTHROPIC_API_URL,
    ANTHROPIC_API_VERSION,
    CLAUDE_MODEL,
    MAX_CHAR_SHRINK_RATIO,
    MAX_RETRIES,
    MIN_MAX_TOKENS,
    OUTPUT_DIR,
    RETRY_BASE_DELAY,
    TOKEN_MULTIPLIER,
    TRANSCRIPTS_DIR,
    get_api_key,
)
from daily_note_writer import get_daily_note_path, write_daily_note
from refinement_prompt import SYSTEM_PROMPT
from transcribe import extract_timestamp

REFINED_LEDGER = TRANSCRIPTS_DIR / ".refined_ledger.json"


def _load_ledger():
    # type: () -> dict
    """Load the set of transcript filenames already refined, keyed by date."""
    if REFINED_LEDGER.exists():
        return json.loads(REFINED_LEDGER.read_text(encoding="utf-8"))
    return {}


def _save_ledger(ledger):
    # type: (dict) -> None
    REFINED_LEDGER.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_text(p: Path) -> str:
    """Read text file with encoding fallback."""
    data = p.read_bytes()
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def group_transcripts_by_date():
    # type: () -> tuple[dict[str, list[tuple[str, str]]], dict[str, list[str]]]
    """
    Read all TXT files in transcripts/, group by date.
    Returns:
      - groups: {date: [(time, content), ...]} sorted by time within each date
      - filenames: {date: [filename, ...]} for ledger tracking
    """
    if not TRANSCRIPTS_DIR.exists():
        return {}, {}

    groups = defaultdict(list)  # type: dict[str, list[tuple[str, str, int]]]
    file_map = defaultdict(list)  # type: dict[str, list[str]]
    skipped = []

    for p in sorted(TRANSCRIPTS_DIR.glob("*.txt")):
        ts = extract_timestamp(p.name)
        if ts is None:
            skipped.append(p.name)
            continue
        date, time_str, seq = ts
        content = _read_text(p)
        if not content.strip():
            print(f"  [SKIP] Empty transcript: {p.name}")
            continue
        groups[date].append((time_str, content, seq))
        file_map[date].append(p.name)

    if skipped:
        print(f"  Skipped {len(skipped)} transcript files (no timestamp)")

    # Sort each group by time then sequence, and strip seq from output
    result = {}  # type: dict[str, list[tuple[str, str]]]
    for date in sorted(groups.keys()):
        entries = sorted(groups[date], key=lambda x: (x[0], x[2]))
        result[date] = [(t, c) for t, c, _ in entries]

    return result, dict(file_map)


def _detect_language(text: str) -> str:
    """Return 'ENGLISH' if text is primarily in English, else 'CHINESE'."""
    stripped = text.strip()
    if not stripped:
        return "CHINESE"
    # Count ASCII letters (English) vs CJK characters (Chinese)
    ascii_letters = sum(1 for c in stripped if c.isascii() and c.isalpha())
    cjk_chars = sum(1 for c in stripped if '\u4e00' <= c <= '\u9fff')
    total = ascii_letters + cjk_chars
    if total == 0:
        return "CHINESE"
    return "ENGLISH" if ascii_letters / total > 0.5 else "CHINESE"


def _build_user_message(date: str, entries: list[tuple[str, str]]) -> str:
    """Build the user message for a single day's transcripts."""
    parts = [f"# {date}\n"]
    for time_str, content in entries:
        lang = _detect_language(content)
        parts.append(f"## {time_str} [{lang}]\n")
        parts.append(content.strip())
        parts.append("")  # blank line between entries
    return "\n".join(parts)


def _estimate_max_tokens(text: str) -> int:
    """Estimate max_tokens for the API call."""
    # Rough estimate: 1 Chinese character ~ 1.5 tokens, 1 English word ~ 1 token
    char_count = len(text)
    estimated_tokens = int(char_count * TOKEN_MULTIPLIER)
    return max(MIN_MAX_TOKENS, estimated_tokens)


def _call_claude_api(
    api_key: str, user_message: str, max_tokens: int
) -> tuple[str, bool]:
    """
    Call Claude API with retry logic.
    Returns (response_text, was_truncated).
    """
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}],
    }

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                ANTHROPIC_API_URL,
                headers=headers,
                json=payload,
                timeout=300,
            )

            if resp.status_code == 200:
                data = resp.json()
                text_blocks = [
                    b["text"] for b in data.get("content", []) if b.get("type") == "text"
                ]
                result_text = "\n".join(text_blocks)
                truncated = data.get("stop_reason") == "max_tokens"
                return result_text, truncated

            if resp.status_code in (429, 500, 502, 503, 529):
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"    API {resp.status_code}, retrying in {delay}s...")
                time.sleep(delay)
                continue

            # Non-retryable error
            print(f"    API error {resp.status_code}: {resp.text[:300]}")
            return "", False

        except requests.exceptions.Timeout:
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            print(f"    API timeout, retrying in {delay}s...")
            time.sleep(delay)
            continue
        except requests.exceptions.RequestException as e:
            print(f"    API request error: {e}")
            return "", False

    print("    API failed after all retries")
    return "", False


def _check_shrinkage(original: str, refined: str, date: str):
    """Warn if refined text is significantly shorter than original."""
    orig_len = len(original.strip())
    refined_len = len(refined.strip())
    if orig_len == 0:
        return
    shrink = 1 - (refined_len / orig_len)
    if shrink > MAX_CHAR_SHRINK_RATIO:
        print(
            f"  WARNING [{date}]: Text shrunk by {shrink:.0%} "
            f"({orig_len} -> {refined_len} chars). May be over-simplified."
        )


def _write_output_md(date, entry_count, refined_text, append=False):
    # type: (str, int, str, bool) -> Path
    """Write the final MD file with YAML front matter, or append to existing.

    Delegates to shared daily_note_writer for consistent behavior across pipelines.
    """
    return write_daily_note(date, entry_count, refined_text, append=append)


def refine_all(force=False, dry_run=False):
    # type: (bool, bool) -> tuple
    """
    Refine all grouped transcripts.
    Returns (success_count, skipped_count, failed_count).
    """
    groups, file_map = group_transcripts_by_date()
    if not groups:
        print("  No transcripts found to refine")
        return 0, 0, 0

    ledger = _load_ledger()

    api_key = None
    if not dry_run:
        api_key = get_api_key()

    success = 0
    skipped = 0
    failed = 0

    for date, entries in groups.items():
        output_path = get_daily_note_path(date)
        current_files = set(file_map.get(date, []))
        processed_files = set(ledger.get(date, []))
        new_files = current_files - processed_files

        if not new_files and not force:
            print(f"  [SKIP] {date}: all {len(current_files)} transcript(s) already refined")
            skipped += 1
            continue

        # Filter entries to only new transcripts (unless force)
        if new_files and not force and processed_files:
            # Only refine the new entries
            new_entries = []
            for t_time, t_content in entries:
                # Match entry back to filename via file_map
                for fname in new_files:
                    ts = extract_timestamp(fname)
                    if ts and ts[1] == t_time:
                        new_entries.append((t_time, t_content))
                        break
            if not new_entries:
                print(f"  [SKIP] {date}: no new entries to refine")
                skipped += 1
                continue
            entries = new_entries

        append_mode = output_path.exists() and bool(processed_files)

        if dry_run:
            total_chars = sum(len(c) for _, c in entries)
            action = "APPEND" if append_mode else "CREATE"
            print(
                f"  [DRY-RUN] {date}: {len(entries)} entries ({len(new_files)} new), "
                f"~{total_chars} chars -> {action} output/{date}.md"
            )
            skipped += 1
            continue

        action_label = "Appending to" if append_mode else "Refining"
        print(f"  {action_label} {date} ({len(entries)} entries, {len(new_files)} new)...")
        user_message = _build_user_message(date, entries)
        max_tokens = _estimate_max_tokens(user_message)

        refined, truncated = _call_claude_api(api_key, user_message, max_tokens)

        if not refined:
            print(f"    FAILED: No response for {date}")
            failed += 1
            continue

        if truncated:
            refined += "\n\n[TRUNCATED]\n"
            print(f"    WARNING: Response was truncated for {date}")

        _check_shrinkage(user_message, refined, date)
        out = _write_output_md(date, len(entries), refined, append=append_mode)
        print(f"    -> {out.name}" + (" [APPENDED]" if append_mode else ""))

        # Update ledger with all files for this date
        ledger[date] = sorted(current_files)
        _save_ledger(ledger)
        success += 1

    return success, skipped, failed
