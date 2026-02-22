#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Share pipeline: extract #Share entries → Twitter-ready posts → Obsidian Shared posts."""
from __future__ import annotations

import argparse
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

from config import (
    ANTHROPIC_API_URL,
    ANTHROPIC_API_VERSION,
    CLAUDE_MODEL,
    MAX_RETRIES,
    MIN_MAX_TOKENS,
    RETRY_BASE_DELAY,
    SHARING_INPUT_DIR,
    SHARING_OUTPUT_DIR,
    TOKEN_MULTIPLIER,
    VAULT_SHARED_POSTS_DIR,
    get_api_key,
)


# ── Data Models ──────────────────────────────────────────────────────

@dataclass
class ShareEntry:
    title: str
    body: str
    source_file: str
    source_date: str


@dataclass
class RefinedEntry:
    title: str
    content: str
    source_date: str


# ── Parsing ─────────────────────────────────────────────────────────

def _parse_entries_from_file(filepath: Path) -> list[ShareEntry]:
    """Parse a single MD file and extract entries tagged #Share."""
    text = filepath.read_text(encoding="utf-8")
    lines = text.split("\n")

    # Skip YAML front matter
    content_start = 0
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                content_start = i + 1
                break

    # Extract source date from front matter or filename
    source_date = ""
    date_match = re.search(r"date:\s*(\d{4}-\d{2}-\d{2})", text)
    if date_match:
        source_date = date_match.group(1)
    else:
        fname_match = re.search(r"(\d{4}-\d{2}-\d{2})", filepath.stem)
        if fname_match:
            source_date = fname_match.group(1)

    content = "\n".join(lines[content_start:])

    # Split by ## headings
    entries_raw = re.split(r"(?=^## )", content, flags=re.MULTILINE)

    results = []
    for entry_text in entries_raw:
        entry_text = entry_text.strip()
        if not entry_text.startswith("## "):
            continue

        # Check for #Share tag — handle both formats:
        # Format 1 (pipe-separated): **场景**：... | **标签**：#Share | **记录时间**：...
        # Format 2 (multi-line):     **标签**：#Share
        if not re.search(r"\*\*标签\*\*[：:].*#Share", entry_text):
            continue

        # Extract title
        title_match = re.match(r"## (.+)", entry_text)
        if not title_match:
            continue
        title = title_match.group(1).strip()

        # Extract body: everything after the first `---` separator line
        parts = re.split(r"^---\s*$", entry_text, maxsplit=1, flags=re.MULTILINE)
        if len(parts) < 2:
            # No --- separator, take everything after metadata lines
            body_lines = entry_text.split("\n")[2:]  # skip title + metadata
            body = "\n".join(body_lines).strip()
        else:
            body = parts[1].strip()

        if body:
            results.append(ShareEntry(
                title=title,
                body=body,
                source_file=filepath.name,
                source_date=source_date,
            ))

    return results


def extract_share_entries(input_dir: Path) -> list[ShareEntry]:
    """Scan all .md files in input_dir and collect #Share entries."""
    if not input_dir.exists():
        print(f"  Input directory not found: {input_dir}")
        return []

    all_entries = []
    md_files = sorted(input_dir.glob("*.md"))

    if not md_files:
        print(f"  No .md files found in {input_dir}")
        return []

    for f in md_files:
        entries = _parse_entries_from_file(f)
        all_entries.extend(entries)
        if entries:
            print(f"  Found {len(entries)} #Share entries in {f.name}")

    return all_entries


# ── Claude API ──────────────────────────────────────────────────────

def _call_claude(api_key: str, system_prompt: str, user_message: str) -> str:
    """Call Claude API with retry logic. Returns response text."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }
    estimated_tokens = int(len(user_message) * TOKEN_MULTIPLIER)
    max_tokens = max(MIN_MAX_TOKENS, estimated_tokens)

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
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
                return "\n".join(text_blocks)

            if resp.status_code in (429, 500, 502, 503, 529):
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"    API {resp.status_code}, retrying in {delay}s...")
                time.sleep(delay)
                continue

            print(f"    API error {resp.status_code}: {resp.text[:300]}")
            return ""

        except requests.exceptions.Timeout:
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            print(f"    API timeout, retrying in {delay}s...")
            time.sleep(delay)
            continue
        except requests.exceptions.RequestException as e:
            print(f"    API request error: {e}")
            return ""

    print("    API failed after all retries")
    return ""


# ── Step 1: Extract ─────────────────────────────────────────────────

def write_extracted(entries: list[ShareEntry], output_dir: Path) -> Path:
    """Write extracted entries to 01_extracted.md."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "01_extracted.md"

    parts = []
    for entry in entries:
        parts.append(f"## {entry.title}\n")
        parts.append(entry.body)
        parts.append("")  # blank line between entries

    content = "\n".join(parts)
    out_path.write_text(content, encoding="utf-8")
    return out_path


# ── Step 2: Twitter-ready Posts ──────────────────────────────────────

TWITTER_SYSTEM_PROMPT = """\
你是一位社交媒体内容编辑。你的任务是对用户提供的语音笔记内容进行书面润色，使其可以直接在推特（X）上发布。

## 润色原则

- **保持原意**：不改变作者的观点、态度和第一人称视角。
- **保持个人风格**：保留作者独特的表达方式和思考角度。
- **提升流畅度**：让口语化的表达更符合书面阅读习惯，但不要过度正式化。
- **保留细节**：不删除具体的数字、案例或个人经历，这些是内容的灵魂。
- **自然段落**：根据语义自然分段，提升可读性。
- **适合推特**：语气自然、有观点、有个性，适合社交媒体上的公开分享。
- **语言保持**：中文内容润色为中文，英文内容润色为英文，不互相翻译。

## 输出格式

对每一条输入条目，保持 `## 标题` 格式，直接输出润色后的内容。
标题可以微调使其更吸引人，但不要偏离原意。
不同条目之间用 `===` 分隔。
不要添加任何解释、前言或总结。\
"""


def refine_for_twitter(api_key: str, output_dir: Path) -> Path:
    """Read 01_extracted.md, refine via Claude API, write 02_twitter.md."""
    extracted_path = output_dir / "01_extracted.md"
    if not extracted_path.exists():
        raise SystemExit("ERROR: 01_extracted.md not found. Run extract step first.")

    user_message = extracted_path.read_text(encoding="utf-8")
    print("  Calling Claude API for Twitter refinement...")
    refined = _call_claude(api_key, TWITTER_SYSTEM_PROMPT, user_message)

    if not refined:
        raise SystemExit("ERROR: Claude API returned empty response for refinement.")

    out_path = output_dir / "02_twitter.md"
    out_path.write_text(refined, encoding="utf-8")
    return out_path


# ── Step 3: Merge to Obsidian Vault ─────────────────────────────────

def _iso_week_label(date_str: str) -> str:
    """Convert YYYY-MM-DD to 'Week N - YYYY' (ISO week, no zero-padding)."""
    dt = datetime.fromisoformat(date_str)
    iso = dt.isocalendar()
    return f"Week {iso.week} - {iso.year}"


def _parse_refined_entries(output_dir: Path, source_entries: list[ShareEntry]) -> list[RefinedEntry]:
    """Parse 02_twitter.md and pair with source_dates from original entries by position."""
    twitter_path = output_dir / "02_twitter.md"
    if not twitter_path.exists():
        raise SystemExit("ERROR: 02_twitter.md not found. Run refine step first.")

    text = twitter_path.read_text(encoding="utf-8")
    blocks = [b.strip() for b in re.split(r"^===\s*$", text, flags=re.MULTILINE) if b.strip()]

    refined = []
    for i, block in enumerate(blocks):
        title_match = re.match(r"## (.+)", block)
        if not title_match:
            continue
        title = title_match.group(1).strip()
        content = block[title_match.end():].strip()

        # Match source_date by position (Claude preserves entry order)
        source_date = source_entries[i].source_date if i < len(source_entries) else ""

        if not source_date:
            today = datetime.today().strftime("%Y-%m-%d")
            print(f"  WARNING: No source_date for entry '{title}', using today ({today})")
            source_date = today

        refined.append(RefinedEntry(title=title, content=content, source_date=source_date))

    return refined


def merge_to_shared_posts(
    refined_entries: list[RefinedEntry],
    vault_posts_dir: Path,
) -> list[Path]:
    """Merge refined entries into weekly Obsidian vault files. Idempotent. Returns written paths."""
    vault_posts_dir.mkdir(parents=True, exist_ok=True)

    # Group entries by ISO week
    week_groups: dict[str, list[RefinedEntry]] = defaultdict(list)
    for entry in refined_entries:
        label = _iso_week_label(entry.source_date)
        week_groups[label].append(entry)

    written_paths = []

    for week_label, entries in week_groups.items():
        file_path = vault_posts_dir / f"{week_label}.md"

        existing_content = file_path.read_text(encoding="utf-8") if file_path.exists() else ""

        # Idempotency: skip entries whose title already appears in the file
        existing_titles = set(re.findall(r"^## (.+)$", existing_content, flags=re.MULTILINE))
        new_entries = [e for e in entries if e.title not in existing_titles]

        for entry in entries:
            if entry.title in existing_titles:
                print(f"  Skipping (already exists): {entry.title}")

        if not new_entries:
            print(f"  No new entries for {week_label}")
            continue

        # Build append text: entries joined by separator
        separator = "\n\n===\n\n"
        parts = [f"## {e.title}\n\n{e.content}" for e in new_entries]
        append_text = separator.join(parts)

        if existing_content:
            new_content = existing_content.rstrip() + separator + append_text + "\n"
        else:
            new_content = append_text + "\n"

        file_path.write_text(new_content, encoding="utf-8")
        written_paths.append(file_path)

        for entry in new_entries:
            print(f"  Adding to {week_label}: {entry.title}")
        print(f"  Wrote {len(new_entries)} entries to {file_path.name}")

    return written_paths


# ── CLI ─────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Share pipeline: extract #Share → refine for Twitter/X → write to Obsidian vault"
    )
    parser.add_argument(
        "--step",
        choices=["extract", "refine"],
        default=None,
        help="Run up to a specific step (default: run all steps including vault merge)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview extracted entries without calling the API or writing to vault",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help=f"Input directory (default: {SHARING_INPUT_DIR})",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    input_dir = args.input_dir or SHARING_INPUT_DIR
    output_dir = SHARING_OUTPUT_DIR

    # Step 1: Extract
    print("Step 1: Extracting #Share entries...")
    entries = extract_share_entries(input_dir)
    if not entries:
        print("  No #Share entries found. Nothing to do.")
        return

    print(f"  Total: {len(entries)} #Share entries extracted")
    out = write_extracted(entries, output_dir)
    print(f"  -> {out}")

    if args.dry_run:
        print("\n[DRY-RUN] Preview of extracted entries:")
        for entry in entries:
            week_label = _iso_week_label(entry.source_date) if entry.source_date else "(no date)"
            print(f"\n  ## {entry.title}  [{entry.source_file} -> {week_label}]")
            preview = entry.body[:150].replace("\n", " ")
            print(f"     {preview}...")
        return

    if args.step == "extract":
        print("Done (extract only).")
        return

    # Step 2: Refine for Twitter/X
    api_key = get_api_key()
    print("\nStep 2: Refining for Twitter/X...")
    out = refine_for_twitter(api_key, output_dir)
    print(f"  -> {out}")

    if args.step == "refine":
        print("Done (extract + refine).")
        return

    # Step 3: Merge to Obsidian vault
    print("\nStep 3: Merging into Obsidian Shared posts...")
    refined_entries = _parse_refined_entries(output_dir, entries)
    written = merge_to_shared_posts(refined_entries, VAULT_SHARED_POSTS_DIR)

    if written:
        print(f"\n  Updated {len(written)} weekly file(s):")
        for p in written:
            print(f"    {p}")
    else:
        print("  No files updated (all entries already exist).")

    print("\nDone! All steps completed.")


if __name__ == "__main__":
    main()
