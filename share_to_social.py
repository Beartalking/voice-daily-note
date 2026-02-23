#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Share to Social: extract #Share entries → Twitter CN + LinkedIn EN + YouTube Shorts → Content Vault."""
from __future__ import annotations

import argparse
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

from config import (
    ANTHROPIC_API_URL,
    ANTHROPIC_API_VERSION,
    CLAUDE_MODEL,
    CONTENT_VAULT_MANUAL_DIR,
    MAX_RETRIES,
    MIN_MAX_TOKENS,
    RETRY_BASE_DELAY,
    SHARING_INPUT_DIR,
    SHARING_OUTPUT_DIR,
    TOKEN_MULTIPLIER,
    get_api_key,
)


# ── Data Model ──────────────────────────────────────────────────────

@dataclass
class ShareEntry:
    title: str
    body: str
    source_file: str
    source_date: str


@dataclass
class SocialPost:
    title: str
    brief: str
    twitter_cn: str
    linkedin_en: str
    youtube_shorts: str
    source_date: str


# ── Parsing ─────────────────────────────────────────────────────────

def _parse_entries_from_file(filepath: Path) -> list[ShareEntry]:
    """Parse a single MD file and extract entries tagged #Share."""
    text = filepath.read_text(encoding="utf-8")
    lines = text.split("\n")

    content_start = 0
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                content_start = i + 1
                break

    source_date = ""
    date_match = re.search(r"date:\s*(\d{4}-\d{2}-\d{2})", text)
    if date_match:
        source_date = date_match.group(1)
    else:
        fname_match = re.search(r"(\d{4}-\d{2}-\d{2})", filepath.stem)
        if fname_match:
            source_date = fname_match.group(1)

    content = "\n".join(lines[content_start:])
    entries_raw = re.split(r"(?=^## )", content, flags=re.MULTILINE)

    results = []
    for entry_text in entries_raw:
        entry_text = entry_text.strip()
        if not entry_text.startswith("## "):
            continue
        if not re.search(r"\*\*标签\*\*[：:].*#Share", entry_text):
            continue

        title_match = re.match(r"## (.+)", entry_text)
        if not title_match:
            continue
        title = title_match.group(1).strip()

        parts = re.split(r"^---\s*$", entry_text, maxsplit=1, flags=re.MULTILINE)
        if len(parts) < 2:
            body_lines = entry_text.split("\n")[2:]
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

def _call_claude(api_key: str, system_prompt: str, user_message: str, output_multiplier: float = TOKEN_MULTIPLIER) -> str:
    """Call Claude API with retry logic. Returns response text."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }
    estimated_tokens = int(len(user_message) * output_multiplier)
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
        parts.append("")

    content = "\n".join(parts)
    out_path.write_text(content, encoding="utf-8")
    return out_path


# ── Step 2: Generate multi-platform social posts ─────────────────────

SOCIAL_SYSTEM_PROMPT = """\
你是一位社交媒体内容策略师。你的任务是将用户的语音笔记整理成适合在三个不同平台发布的内容。

## 关于作者

Bear Liu，Fractional Product Designer，现居新西兰奥克兰。中英双语内容创作者，全网 14 万 Follower。内容聚焦设计、AI、独立工作和创业。

## 输出格式

对每一条输入条目，严格按照以下格式输出：

```
## 标题（可微调使其更吸引人）

简述：用 1-2 句话概括这条内容的核心。

---twitter-cn---
推特中文内容

---linkedin-en---
LinkedIn 英文内容

---youtube-shorts---
YouTube Shorts 标题
```

不同条目之间用 `===` 分隔。
不要添加任何解释、前言或总结。

---

## 各平台具体要求

### Twitter CN（中文推特）

- **不限字数**，原文是多少就整理多少，保留所有细节、数字、案例
- 润色语音口语化表达，使其更适合书面阅读，但保持自然流畅的个人风格
- 根据语义自然分段，提升可读性
- 保持第一人称视角，语气真实有观点

### LinkedIn EN（英文 LinkedIn）

- 翻译并改写为地道英文，针对 LinkedIn 平台特点优化
- 语气专业但有个人故事性，体现创业者/设计师身份
- 适当使用短段落，首句要能抓住注意力
- 如内容过于私人化、不适合职业平台，则输出：`[NOT FOR LINKEDIN] {原因一句话}`

### YouTube Shorts 标题

- 一行标题，简洁有力，能让人想点击
- 在标题末尾或行内加 1-3 个英文 hashtag（如 #ProductDesign #AITools #Figma）
- 标题尽量用英文，但如果内容是中文为主可以用中文标题 + 英文 hashtag\
"""


def generate_social_posts(api_key: str, output_dir: Path) -> Path:
    """Read 01_extracted.md, generate all platform versions, write 02_social.md."""
    extracted_path = output_dir / "01_extracted.md"
    if not extracted_path.exists():
        raise SystemExit("ERROR: 01_extracted.md not found. Run extract step first.")

    user_message = extracted_path.read_text(encoding="utf-8")
    print("  Calling Claude API for multi-platform social post generation...")
    # Output is 3 platform versions per entry, so ~4x the input length
    result = _call_claude(api_key, SOCIAL_SYSTEM_PROMPT, user_message, output_multiplier=4.0)

    if not result:
        raise SystemExit("ERROR: Claude API returned empty response.")

    out_path = output_dir / "02_social.md"
    out_path.write_text(result, encoding="utf-8")
    return out_path


# ── Step 3: Save to Content Vault ────────────────────────────────────

def _safe_filename(title: str) -> str:
    """Convert a title to a safe filename (keeps CJK characters)."""
    slug = re.sub(r'[\\/:*?"<>|]', "-", title)
    return slug.strip(". ") or "untitled"


def _parse_social_posts(output_dir: Path, source_entries: list[ShareEntry]) -> list[SocialPost]:
    """Parse 02_social.md into SocialPost objects, matched by position to source_entries."""
    social_path = output_dir / "02_social.md"
    if not social_path.exists():
        raise SystemExit("ERROR: 02_social.md not found. Run generate step first.")

    text = social_path.read_text(encoding="utf-8")
    blocks = [b.strip() for b in re.split(r"^===\s*$", text, flags=re.MULTILINE) if b.strip()]

    posts = []
    for i, block in enumerate(blocks):
        title_match = re.match(r"## (.+)", block)
        if not title_match:
            continue
        title = title_match.group(1).strip()

        # Extract brief
        brief_match = re.search(r"简述[：:]\s*(.+?)(?=\n---twitter-cn---|$)", block, re.DOTALL)
        brief = brief_match.group(1).strip() if brief_match else ""

        # Extract sections
        def _extract_section(tag: str) -> str:
            pattern = rf"---{tag}---\s*\n(.*?)(?=\n---\w|$)"
            m = re.search(pattern, block, re.DOTALL)
            return m.group(1).strip() if m else ""

        twitter_cn = _extract_section("twitter-cn")
        linkedin_en = _extract_section("linkedin-en")
        youtube_shorts = _extract_section("youtube-shorts")

        source_date = source_entries[i].source_date if i < len(source_entries) else ""
        if not source_date:
            source_date = datetime.today().strftime("%Y-%m-%d")
            print(f"  WARNING: No source_date for '{title}', using today")

        posts.append(SocialPost(
            title=title,
            brief=brief,
            twitter_cn=twitter_cn,
            linkedin_en=linkedin_en,
            youtube_shorts=youtube_shorts,
            source_date=source_date,
        ))

    return posts


def save_to_content_vault(posts: list[SocialPost], manual_dir: Path) -> list[Path]:
    """Save each post as a separate MD file under manual/YYYY-MM/. Idempotent."""
    written_paths = []

    for post in posts:
        month_label = post.source_date[:7]
        month_dir = manual_dir / month_label
        month_dir.mkdir(parents=True, exist_ok=True)

        slug = _safe_filename(post.title)
        file_path = month_dir / f"{post.source_date}-{slug}.md"

        if file_path.exists():
            print(f"  [SKIP] Already exists: {file_path.name}")
            continue

        lines = [f"## {post.title}", ""]
        if post.brief:
            lines += [post.brief, ""]
        lines += [
            "---twitter-cn---",
            post.twitter_cn,
            "",
            "---linkedin-en---",
            post.linkedin_en,
            "",
            "---youtube-shorts---",
            post.youtube_shorts,
            "",
        ]

        file_path.write_text("\n".join(lines), encoding="utf-8")
        written_paths.append(file_path)
        print(f"  Saved: {month_label}/{file_path.name}")

    return written_paths


# ── CLI ─────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Share to Social: extract #Share → Twitter CN + LinkedIn EN + YouTube Shorts → Content Vault"
    )
    parser.add_argument(
        "--step",
        choices=["extract", "generate"],
        default=None,
        help="Run up to a specific step only (default: run all steps including vault save)",
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
        help=f"Input directory containing daily note MD files (default: {SHARING_INPUT_DIR})",
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
        print("\n[DRY-RUN] Entries found:")
        for entry in entries:
            print(f"\n  ## {entry.title}  (from {entry.source_file}, {entry.source_date})")
            preview = entry.body[:150].replace("\n", " ")
            print(f"     {preview}...")
        return

    if args.step == "extract":
        print("Done (extract only).")
        return

    # Step 2: Generate social posts
    api_key = get_api_key()
    print("\nStep 2: Generating multi-platform social posts...")
    out = generate_social_posts(api_key, output_dir)
    print(f"  -> {out}")

    if args.step == "generate":
        print("Done (extract + generate).")
        return

    # Step 3: Save to Content Vault
    print("\nStep 3: Saving to Content Vault...")
    posts = _parse_social_posts(output_dir, entries)
    written = save_to_content_vault(posts, CONTENT_VAULT_MANUAL_DIR)

    if written:
        print(f"\n  Saved {len(written)} post(s):")
        for p in written:
            print(f"    {p}")
    else:
        print("  No new posts (all entries already exist).")

    print("\nDone!")


if __name__ == "__main__":
    main()
