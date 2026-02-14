#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Share pipeline: extract #Share entries → Twitter-ready Chinese → LinkedIn bilingual posts."""
from __future__ import annotations

import argparse
import re
import time
from dataclasses import dataclass
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
    get_api_key,
)


# ── Data Model ──────────────────────────────────────────────────────

@dataclass
class ShareEntry:
    title: str
    body: str
    source_file: str
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
        if not re.search(r"\*\*标签\*\*[：:]\s*#Share", entry_text):
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


# ── Step 2: Twitter-ready Chinese Posts ──────────────────────────────

TWITTER_SYSTEM_PROMPT = """\
你是一位社交媒体内容编辑。你的任务是对用户提供的语音笔记内容进行书面润色，使其可以直接在推特（X）上用中文发布。

## 润色原则

- **保持原意**：不改变作者的观点、态度和第一人称视角。
- **保持个人风格**：保留作者独特的表达方式和思考角度。
- **提升流畅度**：让口语化的表达更符合书面阅读习惯，但不要过度正式化。
- **保留细节**：不删除具体的数字、案例或个人经历，这些是内容的灵魂。
- **自然段落**：根据语义自然分段，提升可读性。
- **适合推特**：语气自然、有观点、有个性，适合社交媒体上的公开分享。

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


# ── Step 3: LinkedIn Filter + Bilingual Translation ─────────────────

LINKEDIN_SYSTEM_PROMPT = """\
你是一位 LinkedIn 内容策略师。用户是一位产品设计师（Product Designer），你需要帮助筛选和优化适合在 LinkedIn 发布的内容。

## 筛选标准

适合 LinkedIn 的内容：
- 职业洞察、行业观察、工作方法论
- 技术趋势分析、AI/设计工具使用心得
- 教育、成长、跨文化观察等有深度的个人思考
- 有独特视角的社会观察（如果能与职业身份产生关联）

不适合 LinkedIn 的内容：
- 纯私人生活日记（除非有职业启示）
- 纯影视/娱乐评论（除非与设计或创意产业相关）
- 过于私密的个人健康/家庭话题

## 输出要求

### 适合发布的内容
1. 中文版：在润色基础上进一步调整措辞，使其更符合 LinkedIn 的专业调性，但保持个人风格和故事性。
2. 英文版：翻译为地道的英文，不是直译，而是重新以英文思维表达同样的内容和观点。保持第一人称。
3. 中英文版本之间用 `---` 分隔，英文标题为中文标题的翻译。

### 不适合发布的内容
在标题后标注 `[FILTERED]`，并简要注明原因。

### 不同条目之间
用 `===` 分隔不同条目。

## 输出格式示例

```
## 中文标题

中文版本内容...

---

## English Title

English version...

===

## 另一个标题
[FILTERED] 原因：...
```

直接输出内容，不要添加任何解释或前言。\
"""


def prepare_linkedin_posts(api_key: str, output_dir: Path) -> Path:
    """Read 02_twitter.md, filter + translate via Claude API, write 03_linkedin.md."""
    refined_path = output_dir / "02_twitter.md"
    if not refined_path.exists():
        raise SystemExit("ERROR: 02_twitter.md not found. Run twitter step first.")

    user_message = refined_path.read_text(encoding="utf-8")
    print("  Calling Claude API for LinkedIn filtering and translation...")
    result = _call_claude(api_key, LINKEDIN_SYSTEM_PROMPT, user_message)

    if not result:
        raise SystemExit("ERROR: Claude API returned empty response for LinkedIn step.")

    out_path = output_dir / "03_linkedin.md"
    out_path.write_text(result, encoding="utf-8")
    return out_path


# ── CLI ─────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Share pipeline: extract #Share → Twitter Chinese → LinkedIn bilingual"
    )
    parser.add_argument(
        "--step",
        choices=["extract", "twitter", "linkedin"],
        default=None,
        help="Run up to a specific step (default: run all 3 steps)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview extracted entries without calling the API",
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
            print(f"\n  ## {entry.title}  (from {entry.source_file})")
            preview = entry.body[:150].replace("\n", " ")
            print(f"     {preview}...")
        return

    if args.step == "extract":
        print("Done (extract only).")
        return

    # Step 2: Twitter
    api_key = get_api_key()
    print("\nStep 2: Refining for Twitter (Chinese)...")
    out = refine_for_twitter(api_key, output_dir)
    print(f"  -> {out}  (可直接用于推特发布)")

    if args.step == "twitter":
        print("Done (extract + twitter).")
        return

    # Step 3: LinkedIn
    print("\nStep 3: Preparing LinkedIn posts (filter + translate)...")
    out = prepare_linkedin_posts(api_key, output_dir)
    print(f"  -> {out}")

    print("\nDone! All 3 steps completed.")


if __name__ == "__main__":
    main()
