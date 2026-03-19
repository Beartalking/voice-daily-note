#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Share to Social: extract #Share entries → Twitter CN → Content Vault."""
from __future__ import annotations

import argparse
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from config import (
    ANTHROPIC_API_URL,
    ANTHROPIC_API_VERSION,
    CLAUDE_MODEL,
    CONTENT_VAULT_MANUAL_DIR,
    MAX_RETRIES,
    MIN_MAX_TOKENS,
    RETRY_BASE_DELAY,
    SHARING_OUTPUT_DIR,
    TOKEN_MULTIPLIER,
    get_api_key,
)

# ── Obsidian Daily Notes source ─────────────────────────────────────
DAILY_NOTES_BASE = Path(
    "/Users/bearliu/Library/Mobile Documents/iCloud~md~obsidian/Documents/Bear Vault/Daily notes"
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
    twitter_cn: str
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
        if not re.search(r"\*\*标签\*\*[：:].*#Share", entry_text, re.IGNORECASE):
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


def _normalize_title(title: str) -> str:
    """Normalize title for dedup comparison: lowercase, no spaces/punctuation."""
    t = title.lower().strip()
    # Remove all non-alphanumeric (keep CJK chars as \w matches them)
    t = re.sub(r"[^\w]", "", t)
    return t


def extract_share_entries_from_daily_notes(
    input_dir: Optional[str] = None,
    force: bool = False,
) -> list[ShareEntry]:
    """Scan Obsidian Daily Notes directly for #Share entries, skipping already-processed ones."""
    base = Path(input_dir) if input_dir else DAILY_NOTES_BASE
    if not base.exists():
        print(f"  Daily Notes directory not found: {base}")
        return []

    if force:
        processed_titles = set()
    else:
        processed_titles = _collect_processed_titles()
        if processed_titles:
            print(f"  Found {len(processed_titles)} titles already processed in Content Vault")

    from datetime import timedelta
    cutoff_date = (datetime.today() - timedelta(days=7)).strftime("%Y-%m-%d")

    all_entries = []
    for md_file in sorted(base.rglob("*.md")):
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", md_file.stem)
        if not date_match:
            continue
        file_date = date_match.group(1)

        if file_date < cutoff_date:
            continue

        text = md_file.read_text(encoding="utf-8")
        if "#Share" not in text:
            continue

        entries = _parse_entries_from_file(md_file)
        # Filter out entries whose titles are already processed
        new_entries = []
        for entry in entries:
            normalized = _normalize_title(entry.title)
            if any(normalized in pt or pt in normalized for pt in processed_titles):
                continue
            new_entries.append(entry)

        if new_entries:
            skipped = len(entries) - len(new_entries)
            msg = f"  Found {len(new_entries)} new #Share entries in {md_file.name}"
            if skipped:
                msg += f" ({skipped} already processed)"
            print(msg)
        all_entries.extend(new_entries)

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
    max_tokens = min(64000, max(MIN_MAX_TOKENS, estimated_tokens))

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
你是 Bear Liu 的写作伙伴。你的任务是将他的语音笔记中标记 #Share 的条目改写成适合在 Twitter 发布的中文内容。

改写的目标：保留原始信息和意图，用 Bear 的真实写作风格重写，使之从"语音记录"变成"适合阅读的帖子"。

---

## 关于作者

Bear Liu，Fractional Product Designer，现居新西兰奥克兰。中英双语内容创作者，全网 14 万 Follower。内容聚焦 AI、产品设计、独立工作和创业实战。真实项目是内容素材库：Fractional Design Partner（B2B 商业主线）、JAM（资产型产品）。

---

## Bear 的写作声音（核心定位）

**一个在场的人在跟你讲他刚做过的一件事。**

像坐在朋友对面，听他边喝咖啡边复盘。有细节、有过程、有自嘲，偶尔蹦出一句让你笑出来的话。他不教你做人，也不贩卖焦虑，就是把事情说清楚。

三个关键词：**真诚、自嘲、跨文化**。

- 真诚到不怕丢脸：写自己的尴尬、写自己的失败
- 自嘲作为叙事引擎：几乎所有转折点和高潮都由自嘲触发，让痛苦的经历读起来也不沉重
- 跨文化双视角：能用中文的幽默感写新西兰的生活，也能用西方的职业框架反思中国式的成长经历

---

## 叙事比例

**70% 个人叙事 + 30% 分析反思。** 永远以个人经历为骨架，切入点是"我用了""我试了""我的感受是"。分析部分像"顿悟"式表达，讲完故事后说"现在我明白了"，然后给结论。

---

## 句式与节奏

### 核心节奏：口语化的说话节奏
短句和长句交替，形成"说话"的感觉。铺垫用长句，抖包袱用短句，像说相声。

长句也会用逗号切成短呼吸，读起来有一口气说完一段信息的流动感，然后用一个短句做结论。

### 允许的节奏工具
- **三连短句排比**：制造速度感。"走路想到什么，录。开车有个念头，录。刚开完会脑子还热着，录。"
- **单句成段**：起停顿和强调作用
- **冒号引出结论**："改变最大的不是时间，是心理负担。"
- **括号补充**：主线叙述中塞入补充信息，思维跳跃式地想到什么就补一句
- **感叹号和语气词**："简直""超级""TM""嘛""啊""吧""欧耶"

### 禁止的节奏
- 长从句嵌套（超过 3 层逗号分割的句子）
- 碎片式短句大量换行排版
- 排比修辞超过 3 个
- 过度整齐的对仗

---

## 词汇与措辞

### Bear 的标志性用词（自然使用，不要刻意堆砌）
- 评价类（轻描淡写式）："挺好""还不错""有点可惜""简直"
- 思考标记类："其实""坦白说""说实话""对我来说""我觉得""可能""大概""应该"
- 行动类："跑通""跑起来""拍板""下场""磨人"
- 情绪类："哈哈""欧耶""TM"（低频高冲击）
- 结构类："按照惯例""从XX上来说/来看""你呢？"
- 引号标记概念或隐喻：从"要专门腾出一天"变成了"顺手的事"

### 严禁的用词和句式
- **破折号（Em Dashes），中英文都不用**
- **"不是……而是"句型**
- "在这个 AI 时代……" 之类的抽象宏大叙事开头
- "今天我想聊聊……" 之类的预告式开头
- 鸡汤式表达："相信自己""勇敢追梦"
- 营销腔："颠覆""赋能""打造""闭环""链路"
- 四字成语堆砌
- "首先……其次……最后" 等教科书式连接词
- 网络流行语和过时的梗
- 煽情、渲染、情绪宣泄、强行升华、贩卖焦虑

---

## 情感表达

### 基调：温暖、自嘲、真诚
- 自嘲是核心调味料，驱动叙事的燃料
- 对负面经历非常克制，一两句带过事件本身，迅速转向"我从中学到什么"

### 情绪回收技术（Bear 最核心的风格标识）
在一个严肃或感伤的段落之后，突然用一句自嘲或幽默把情绪拉回来。例如：
- 写孤独感 → "赶紧找一份累到不可能有孤独感的工作！"
- 写投资亏损 → "买了三次特斯拉，每次都买完就跌，目前损失30%。"

---

## 段落过渡

自然过渡，极少使用显式连接词。段落之间靠主题的内在逻辑串联：
- 时间推进、问题驱动、维度切换
- 转折标记："但""不过""然而"（高频）
- 设问承上启下

---

## 中英文混合规则

中文文章中的英文遵循三层：
1. 专有名词不翻译：ChatGPT, Notion, YouTube, Apple Watch
2. 行业术语保留英文：Newsletter, Workshop, WFH, prototype, Design Thinking
3. 对话原文保留

不加引号标注，不特意翻译。完全符合海外华人日常交流的真实语感。

---

## 技术细节处理

用"我怎么用它"代替"它怎么工作"。不解释原理，转化为使用场景和实际效果。用结果量化取代原理解释。把技术问题包装成"踩坑"故事，有戏剧感。

---

## Twitter 帖子结构（Content.md 6.1）

- 开头：一句抓人的观察或结论（个人场景切入、反问、热点事件、高密度判断，四选一）
- 中段：补 2 到 4 条关键点，最好带一个真实片段或例子
- 收尾：一个可以引发回复的开放句，或一个下一步动作（向读者发问、自嘲式收尾、金句收束、自然停止，四选一）

---

## 标点规则（严格执行）

- 中文内容必须全程使用中文标点：逗号用 `，`，句号用 `。`，冒号用 `：`，问号用 `？`，感叹号用 `！`，顿号用 `、`，引号用 `""`，括号用 `（）`
- 禁止在中文语境中使用英文标点（逗号 `,`、冒号 `:`、句号 `.`、破折号 `-` 或 `—` 等）

---

## 改写原则

- **零删减倾向**：保留草稿的原始信息与意图，原文说了多少整理多少，保留所有细节、数字、案例
- 优先修复结构、逻辑顺序、表达清晰度
- 允许压缩重复口头禅，但不要把信息密度压没了
- 用 Bear 的声音重写，让语音记录变成"读起来舒服的帖子"
- 根据语义自然分段，提升可读性

---

## 输出格式

对每一条输入条目，严格按照以下格式输出：

```
## 标题（可微调使其更吸引人）

---twitter-cn---
推特中文内容
```

不同条目之间用 `===` 分隔。
不要添加任何解释、前言或总结。\
"""


def _sanitize_output(text: str) -> str:
    """Remove em dashes and fix prohibited patterns in generated text."""
    # Replace em dashes (——, —) with comma or remove
    text = text.replace("——", "，")
    text = text.replace("—", "，")
    # Clean up double commas that might result
    text = text.replace("，，", "，")
    return text


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

    result = _sanitize_output(result)
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

        # Extract twitter-cn section
        m = re.search(r"---twitter-cn---\s*\n(.*?)(?=\n---\w|$)", block, re.DOTALL)
        twitter_cn = m.group(1).strip() if m else ""

        source_date = source_entries[i].source_date if i < len(source_entries) else ""
        if not source_date:
            source_date = datetime.today().strftime("%Y-%m-%d")
            print(f"  WARNING: No source_date for '{title}', using today")

        posts.append(SocialPost(
            title=title,
            twitter_cn=twitter_cn,
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

        frontmatter = (
            f"---\n"
            f"title: {post.title}\n"
            f"date: {post.source_date}\n"
            f"publish_twitter_cn: true\n"
            f"ready: false\n"
            f"scheduled_for: \n"
            f"auto_publish: false\n"
            f"use_queue: true\n"
            f"source: manual\n"
            f"source_url: \n"
            f"images: \n"
            f"cloudinary_urls: {{}}\n"
            f"late_post_ids: {{}}\n"
            f"published_at: \n"
            f"---\n"
        )

        lines = [
            "",
            "---twitter-cn---",
            post.twitter_cn,
            "",
        ]

        file_path.write_text(frontmatter + "\n".join(lines), encoding="utf-8")
        written_paths.append(file_path)
        print(f"  Saved: {month_label}/{file_path.name}")

    return written_paths


# ── CLI ─────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Share to Social: extract #Share from Daily Notes → Twitter CN → Content Vault"
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
        type=str,
        default=None,
        help="Read daily notes from this local directory instead of Obsidian vault",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip dedup check and reprocess all #Share entries",
    )
    return parser.parse_args()


CONTENT_VAULT_SOCIAL_BASE = Path(
    "/Users/bearliu/Library/Mobile Documents/iCloud~md~obsidian/Documents/Bear Content Vault/Social Posts"
)


def _collect_processed_titles() -> set:
    """Scan all Social Posts (drafts + published) to find normalized titles already processed."""
    processed = set()
    if not CONTENT_VAULT_SOCIAL_BASE.exists():
        return processed
    for md_file in CONTENT_VAULT_SOCIAL_BASE.rglob("*.md"):
        stem = md_file.stem
        date_match = re.match(r"\d{4}-\d{2}-\d{2}-(.+)", stem)
        if date_match:
            processed.add(_normalize_title(date_match.group(1)))
        try:
            text = md_file.read_text(encoding="utf-8")
            title_match = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", text, re.MULTILINE)
            if title_match:
                processed.add(_normalize_title(title_match.group(1)))
        except Exception:
            pass
    return processed


def main():
    args = parse_args()
    output_dir = SHARING_OUTPUT_DIR

    # Step 1: Extract #Share entries directly from Obsidian Daily Notes
    source_label = args.input_dir or "Obsidian Daily Notes"
    print(f"Step 1: Scanning {source_label} for #Share entries...")
    entries = extract_share_entries_from_daily_notes(
        input_dir=args.input_dir,
        force=args.force,
    )
    if not entries:
        print("  No new #Share entries found. Nothing to do.")
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

    # Step 2: Generate social posts via Claude API
    api_key = get_api_key()
    print("\nStep 2: Generating social posts...")
    out = generate_social_posts(api_key, output_dir)
    print(f"  -> {out}")

    if args.step == "generate":
        print("Done (extract + generate).")
        return

    # Step 3: Save to Content Vault (Social Posts/drafts/manual/)
    print("\nStep 3: Saving to Content Vault...")
    posts = _parse_social_posts(output_dir, entries)
    written = save_to_content_vault(posts, CONTENT_VAULT_MANUAL_DIR)

    if written:
        print(f"\n  Saved {len(written)} post(s):")
        for p in written:
            print(f"    {p}")
    else:
        print("  No new posts (all entries already exist).")

    # Clean up temp pipeline files
    for f in output_dir.glob("*"):
        if f.is_file():
            f.unlink()

    print("\nDone!")


if __name__ == "__main__":
    main()
