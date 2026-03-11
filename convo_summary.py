#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Post-refinement step: generate structured summaries for #Convo entries."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

import requests

from config import (
    ANTHROPIC_API_URL,
    ANTHROPIC_API_VERSION,
    CLAUDE_MODEL,
    MAX_RETRIES,
    MIN_MAX_TOKENS,
    OUTPUT_DIR,
    RETRY_BASE_DELAY,
    get_api_key,
)

CONVO_SUMMARY_PROMPT = """\
你是一位会议和对话记录整理助手。你的任务是为一段对话录音的转录文本生成结构化摘要。

## 输出格式

严格按以下格式输出，不要添加任何额外解释：

```
### 对话摘要

**场景**：[对话发生的场景、地点或背景。如果录音中有说明就用它；如果没有，写 "[待补充]"]
**参与者**：[对话参与者。如果录音中提到了名字就用；如果没有，写 "[待补充]"]
**日期**：[对话日期]

#### 要点
- [关键讨论点1]
- [关键讨论点2]
- [关键讨论点3]
...

#### 下一步行动
- [ ] [具体的行动项1]
- [ ] [具体的行动项2]
...
```

## 处理规则

- 从对话内容中提炼要点，每个要点用一句话概括
- 如果对话中明确提到了下一步计划或 action items，列出来；如果没有明确的行动项，这个部分可以省略
- 场景和参与者信息优先从录音开头或结尾的说明中提取；如果没有，用 "[待补充]" 占位
- 要点按讨论顺序排列，不要重新排序
- 保持简洁，每个要点不超过两句话
- 用中文输出\
"""


def _call_claude(api_key: str, user_message: str) -> str:
    """Call Claude API with retry logic."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": max(MIN_MAX_TOKENS, 2048),
        "system": CONVO_SUMMARY_PROMPT,
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
                blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
                return "\n".join(blocks)

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


def _parse_convo_entries(text: str) -> List[Tuple[int, int, str, str]]:
    """Find #Convo entries in a daily note.

    Returns list of (start_pos, end_pos, title, body) for entries containing #Convo tag.
    """
    entries = []
    # Split by ## headers
    header_pattern = re.compile(r"^## .+", re.MULTILINE)
    headers = list(header_pattern.finditer(text))

    for i, match in enumerate(headers):
        start = match.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        section = text[start:end]

        # Check for #Convo tag
        if not re.search(r"#Convo\b", section):
            continue

        title_line = match.group(0)
        title = title_line.lstrip("# ").strip()

        # Extract body (everything after the --- separator)
        parts = re.split(r"^---\s*$", section, maxsplit=1, flags=re.MULTILINE)
        body = parts[1].strip() if len(parts) > 1 else section[len(title_line):].strip()

        entries.append((start, end, title, body))

    return entries


def _has_summary(section_text: str) -> bool:
    """Check if a #Convo entry already has a summary appended."""
    return "### 对话摘要" in section_text


def summarize_convo_in_file(filepath: Path, api_key: str, dry_run: bool = False) -> int:
    """Process a single daily note file: find #Convo entries, generate and append summaries.

    Returns number of summaries generated.
    """
    text = filepath.read_text(encoding="utf-8")
    entries = _parse_convo_entries(text)

    if not entries:
        return 0

    generated = 0
    # Process in reverse order so positions remain valid after insertion
    for start, end, title, body in reversed(entries):
        section = text[start:end]
        if _has_summary(section):
            print(f"    [SKIP] '{title}' already has summary")
            continue

        if dry_run:
            print(f"    [DRY-RUN] Would summarize: '{title}'")
            generated += 1
            continue

        # Extract date from frontmatter
        date_match = re.search(r"date:\s*(\d{4}-\d{2}-\d{2})", text)
        date_str = date_match.group(1) if date_match else ""

        user_msg = f"日期：{date_str}\n标题：{title}\n\n{body}"
        print(f"    Summarizing: '{title}'...")
        summary = _call_claude(api_key, user_msg)

        if not summary:
            print(f"    FAILED: No summary for '{title}'")
            continue

        # Append summary before the next entry (at end of current section)
        insert_pos = end
        # Trim trailing whitespace from section, then add summary
        section_end = text[start:end].rstrip()
        new_section = text[start:start + len(section_end)] + "\n\n" + summary + "\n\n"
        text = text[:start] + new_section + text[end:]
        generated += 1

    if generated > 0 and not dry_run:
        filepath.write_text(text, encoding="utf-8")

    return generated


def summarize_convo_all(force: bool = False, dry_run: bool = False) -> Tuple[int, int]:
    """Scan all output daily notes for #Convo entries and generate summaries.

    Returns (files_processed, summaries_generated).
    """
    if not OUTPUT_DIR.exists():
        print("  Output directory not found")
        return 0, 0

    api_key = None
    if not dry_run:
        api_key = get_api_key()

    files_processed = 0
    total_summaries = 0

    for md_file in sorted(OUTPUT_DIR.rglob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        if "#Convo" not in text:
            continue

        # Check if all #Convo entries already have summaries (skip unless force)
        entries = _parse_convo_entries(text)
        if not entries:
            continue

        unsummarized = [e for e in entries if not _has_summary(text[e[0]:e[1]])]
        if not unsummarized and not force:
            continue

        print(f"  Processing {md_file.name} ({len(unsummarized)} #Convo entries to summarize)...")
        files_processed += 1
        count = summarize_convo_in_file(md_file, api_key, dry_run=dry_run)
        total_summaries += count

    return files_processed, total_summaries
