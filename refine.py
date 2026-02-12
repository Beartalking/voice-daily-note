#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 2: Group transcripts by date, call Claude API for refinement, output MD files."""
from __future__ import annotations

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
from refinement_prompt import SYSTEM_PROMPT
from transcribe import extract_timestamp


def _read_text(p: Path) -> str:
    """Read text file with encoding fallback."""
    data = p.read_bytes()
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def group_transcripts_by_date() -> dict[str, list[tuple[str, str]]]:
    """
    Read all TXT files in transcripts/, group by date.
    Returns {date: [(time, content), ...]} sorted by time within each date.
    """
    if not TRANSCRIPTS_DIR.exists():
        return {}

    groups: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
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

    if skipped:
        print(f"  Skipped {len(skipped)} transcript files (no timestamp)")

    # Sort each group by time then sequence, and strip seq from output
    result: dict[str, list[tuple[str, str]]] = {}
    for date in sorted(groups.keys()):
        entries = sorted(groups[date], key=lambda x: (x[0], x[2]))
        result[date] = [(t, c) for t, c, _ in entries]

    return result


def _build_user_message(date: str, entries: list[tuple[str, str]]) -> str:
    """Build the user message for a single day's transcripts."""
    parts = [f"# {date}\n"]
    for time_str, content in entries:
        parts.append(f"## {time_str}\n")
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


def _write_output_md(date: str, entry_count: int, refined_text: str):
    """Write the final MD file with YAML front matter."""
    front_matter = f"---\ndate: {date}\ntype: daily-note\nentries: {entry_count}\n---\n\n"
    content = front_matter + refined_text
    output_path = OUTPUT_DIR / f"{date}.md"
    output_path.write_text(content, encoding="utf-8")
    return output_path


def refine_all(force: bool = False, dry_run: bool = False) -> tuple[int, int, int]:
    """
    Refine all grouped transcripts.
    Returns (success_count, skipped_count, failed_count).
    """
    groups = group_transcripts_by_date()
    if not groups:
        print("  No transcripts found to refine")
        return 0, 0, 0

    api_key = None
    if not dry_run:
        api_key = get_api_key()

    success = 0
    skipped = 0
    failed = 0

    for date, entries in groups.items():
        output_path = OUTPUT_DIR / f"{date}.md"
        if output_path.exists() and not force:
            print(f"  [SKIP] {date}.md already exists")
            skipped += 1
            continue

        if dry_run:
            total_chars = sum(len(c) for _, c in entries)
            print(
                f"  [DRY-RUN] {date}: {len(entries)} entries, "
                f"~{total_chars} chars -> output/{date}.md"
            )
            skipped += 1
            continue

        print(f"  Refining {date} ({len(entries)} entries)...")
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
        out = _write_output_md(date, len(entries), refined)
        print(f"    -> {out.name}")
        success += 1

    return success, skipped, failed
