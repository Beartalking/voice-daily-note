#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pipeline D: Bookshelf Sync.

Scan Obsidian daily notes for entries tagged #Book or #Movie and sync
their content into the matching Books/ or Movies/ files. Tagged entries
are appended as a new "## 后续笔记" section in each target file so
later reflections can stack up over time (great for re-reads, replays,
second viewings).

Flow:
    daily note entry (#Book / #Movie)
    -> dedup (tracker JSON)
    -> Claude extracts work title(s) + type
    -> fuzzy match Books/ or Movies/ existing files
       - 1 hit : append
       - 0 hit : auto-create via add_book.py / add_movie.py, then append
       - N hit : interactive pick (or --batch to skip)
    -> append formatted block under `## 后续笔记`
    -> tracker update

Usage:
    python3 bookshelf_sync.py               # 扫最近 30 天
    python3 bookshelf_sync.py --days 7
    python3 bookshelf_sync.py --dry-run     # 预览不写入
    python3 bookshelf_sync.py --tag movie   # 只处理 #Movie
    python3 bookshelf_sync.py --tag book    # 只处理 #Book
    python3 bookshelf_sync.py --force       # 忽略 tracker
    python3 bookshelf_sync.py --reset       # 清空 tracker
    python3 bookshelf_sync.py --batch       # 多候选时跳过，不交互
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from config import (
    ANTHROPIC_API_URL,
    ANTHROPIC_API_VERSION,
    CLAUDE_MODEL,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    get_api_key,
)

# --- Paths -----------------------------------------------------------
VAULT_ROOT = Path(
    "/Users/bearliu/Library/Mobile Documents/iCloud~md~obsidian/Documents/Bear Vault"
)
DAILY_NOTES_DIR = VAULT_ROOT / "10_Daily"
BOOKS_DIR = VAULT_ROOT / "40_Books"
MOVIES_DIR = VAULT_ROOT / "41_Movies"

SCRIPT_DIR = Path(__file__).resolve().parent
TRACKER_PATH = SCRIPT_DIR / "bookshelf_sync_tracker.json"

ADD_BOOK_SCRIPT = Path("/Users/bearliu/Desktop/ClaudeCode/reader-library/add_book.py")
ADD_MOVIE_SCRIPT = Path(
    "/Users/bearliu/Desktop/ClaudeCode/movie-notes/add_movie.py"
)

# voice-capture folds routed commands (reminders / English captures / research)
# into a collapsed archive block at the end of a daily note. Those blocks carry
# their own **标签** line, so a reminder like "下载 Jim Dale 版哈利波特有声书"
# tagged #Book would otherwise be picked up here as a reading entry. Strip the
# block before parsing, same as insight-finder's note_utils.strip_routed_archive.
ROUTED_ARCHIVE_RE = re.compile(
    r"\n*<!--\s*voice-capture:archive:start\s*-->.*?"
    r"<!--\s*voice-capture:archive:end\s*-->\n*",
    re.DOTALL,
)


# --- Prompt ----------------------------------------------------------
EXTRACTION_SYSTEM = """你从一条 Obsidian daily note 笔记块中提取被明确讨论的作品。

输入会附带一个提示，说明这条笔记被打了 #Book 或 #Movie 标签。
- #Book 对应书籍 (type=book)
- #Movie 对应电影/电视剧/游戏 (type 从 movie/tv/game 中选)

严格返回一个 JSON 数组，每个被明确讨论的作品一项：
[{"title_en": "英文/原名标题", "title_cn": "中文译名（没有就空字符串）", "type": "book|movie|tv|game"}]

判断规则：
- 只提取笔记中明确命名、且 Bear 有实际观感/阅读感受的作品
- 作品名以拉丁字母为主时用英文原名（如 "Severance" 而非 "人生切割术"）
- 中文原作（如《长安的荔枝》）title_en 必须留空（绝不要写拼音），title_cn 必填
- 只提取 Bear 真正阅读 / 观看过、有实际体验的作品；仅作对比、顺带提及、举例引用而 Bear 并未实际读 / 看的作品，不要提取
- 注意区分作者名与作品名：如「不如天然（《天然的有一年》…）」里作者是「天然」、作品名是《天然的有一年》本身要看上下文判断；拿不准作者与书名边界时，只提取能确定的作品名，宁缺毋滥
- 作品类型参考：书=book；剧集/动画/纪录片=tv；单部电影=movie；电子游戏=game
- 无明确作品返回 []

只返回 JSON，不要任何前缀、后缀、解释文字。"""


# --- Entry extraction ------------------------------------------------
TAG_PATTERN = re.compile(r"\*\*标签\*\*[：:].*#(Book|Movie)", re.IGNORECASE)
HEADING_PATTERN = re.compile(r"^## (.+)$", re.MULTILINE)


def iter_daily_notes(days: int):
    """Yield daily note paths whose date is within the last `days` days."""
    cutoff = datetime.now().date() - timedelta(days=days)
    if not DAILY_NOTES_DIR.exists():
        return
    for md in sorted(DAILY_NOTES_DIR.rglob("*.md")):
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", md.stem)
        if not m:
            continue
        try:
            note_date = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except ValueError:
            continue
        if note_date < cutoff:
            continue
        yield md, note_date


def split_blocks(text: str):
    """Split daily note text into level-2 heading blocks."""
    blocks = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    return [b for b in blocks if b.startswith("## ")]


def parse_block(block: str, note_date):
    """Parse a level-2 block into heading, metadata fields, body."""
    lines = block.split("\n")
    heading = lines[0][3:].strip() if lines and lines[0].startswith("## ") else ""

    def _field(name):
        m = re.search(rf"\*\*{name}\*\*[：:]\s*(.+)", block)
        return m.group(1).strip() if m else ""

    scene = _field("场景")
    timestamp = _field("记录时间")
    tags = _field("标签")

    # Body is content after the first top-level --- separator inside the block
    # Block shape:
    #   ## heading
    #   **场景**:...
    #   **标签**:...
    #   **记录时间**:...
    #   ---
    #   body text...
    # Block structure: heading + meta + '---' + body + (optional '---' + next block)
    # Take content between the 1st and 2nd standalone '---' line, or until EOF.
    parts = re.split(r"^---\s*$", block, flags=re.MULTILINE)
    if len(parts) >= 3:
        body = parts[1].strip()
    elif len(parts) == 2:
        body = parts[1].strip()
    else:
        body = ""

    return {
        "date": note_date.strftime("%Y-%m-%d"),
        "heading": heading,
        "scene": scene,
        "tags": tags,
        "timestamp": timestamp,
        "body": body,
    }


def extract_tagged_entries(days: int, only_tag: str | None):
    """Walk daily notes and yield entry dicts for #Book / #Movie blocks."""
    for md_path, note_date in iter_daily_notes(days):
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError:
            continue
        text = ROUTED_ARCHIVE_RE.sub("\n", text)
        for block in split_blocks(text):
            tag_match = TAG_PATTERN.search(block)
            if not tag_match:
                continue
            tag_type = tag_match.group(1).lower()  # 'book' or 'movie'
            if only_tag and only_tag != tag_type:
                continue
            entry = parse_block(block, note_date)
            entry["source_file"] = str(md_path.relative_to(VAULT_ROOT))
            entry["tag_type"] = tag_type
            yield entry


# --- Claude call -----------------------------------------------------
def extract_works(entry: dict, api_key: str):
    """Ask Claude to extract work titles from an entry."""
    user_msg = (
        f"这条笔记被打了 #{entry['tag_type'].capitalize()} 标签。\n\n"
        f"笔记标题：{entry['heading']}\n"
        f"场景：{entry['scene']}\n\n"
        f"正文：\n{entry['body']}"
    )
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1024,
        "system": EXTRACTION_SYSTEM,
        "messages": [{"role": "user", "content": user_msg}],
    }

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                ANTHROPIC_API_URL, headers=headers, json=payload, timeout=60
            )
            if resp.status_code == 200:
                data = resp.json()
                blocks = [
                    b["text"] for b in data.get("content", []) if b.get("type") == "text"
                ]
                text = "\n".join(blocks).strip()
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
                try:
                    works = json.loads(text)
                except json.JSONDecodeError:
                    # Try salvage: find the first [...]
                    m = re.search(r"\[.*\]", text, re.DOTALL)
                    if not m:
                        return []
                    works = json.loads(m.group(0))
                return works if isinstance(works, list) else []

            if resp.status_code in (429, 500, 502, 503, 529):
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"    API {resp.status_code}, retrying in {delay}s...")
                time.sleep(delay)
                continue

            print(f"    API error {resp.status_code}: {resp.text[:200]}")
            return []
        except requests.RequestException as e:
            print(f"    network error: {e}")
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
    return []


# --- Fuzzy match -----------------------------------------------------
NORM_PUNCT = re.compile(r"[\s\-_,'\"()·《》【】：:\.!?？！,，。·]+")


def normalize(s: str) -> str:
    if not s:
        return ""
    return NORM_PUNCT.sub("", s.lower())


def read_frontmatter(md_path: Path) -> dict:
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    m = re.match(r"---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"^(\w+):\s*(.*)$", line)
        if not kv:
            continue
        val = kv.group(2).strip().strip('"').strip("'")
        fm[kv.group(1)] = val
    return fm


def find_match(work: dict, target_dir: Path):
    """Return candidate file paths ranked by match score."""
    if not target_dir.exists():
        return []
    norm_en = normalize(work.get("title_en", ""))
    norm_cn = normalize(work.get("title_cn", ""))
    candidates = []
    for md in target_dir.rglob("*.md"):
        fm = read_frontmatter(md)
        if not fm:
            continue
        cand_titles = [
            normalize(fm.get("title", "")),
            normalize(fm.get("title_cn", "")),
            normalize(md.stem),
        ]
        cand_titles = [t for t in cand_titles if t]

        score = 0
        for source in [norm_en, norm_cn]:
            if not source:
                continue
            for cand in cand_titles:
                if source == cand:
                    score += 3
                elif source in cand or cand in source:
                    score += 1
        if score > 0:
            candidates.append((score, md))
    candidates.sort(key=lambda x: (-x[0], x[1].name))
    return [c[1] for c in candidates]


# --- Append ----------------------------------------------------------
FOLLOWUP_HEADING = "## 后续笔记"


def build_followup_block(entry: dict) -> str:
    lines = [
        f"### {entry['date']} · {entry['heading']}",
    ]
    if entry.get("scene"):
        lines.append(f"**场景**：{entry['scene']}")
    if entry.get("timestamp"):
        lines.append(f"**记录时间**：{entry['timestamp']}")
    lines.append("")
    lines.append(entry["body"].strip())
    return "\n".join(lines).rstrip() + "\n"


def append_followup(target: Path, entry: dict) -> bool:
    """Append this entry's followup block. Idempotent: returns False (no write)
    if the entry's block is already present, so re-runs never duplicate."""
    content = target.read_text(encoding="utf-8").rstrip()

    # Idempotency guard: skip if this exact entry block already exists
    block_marker = f"### {entry['date']} · {entry['heading']}"
    if block_marker in content:
        return False

    # Remove any trailing --- to keep file tidy
    content = re.sub(r"\n+---\s*$", "", content).rstrip()

    new_block = build_followup_block(entry)

    if FOLLOWUP_HEADING in content:
        content += "\n\n---\n\n" + new_block
    else:
        content += "\n\n---\n\n" + FOLLOWUP_HEADING + "\n\n" + new_block

    content += "\n"
    target.write_text(content, encoding="utf-8")
    return True


# --- Auto-create -----------------------------------------------------
def auto_create(work: dict, work_type: str):
    """Invoke add_book.py or add_movie.py; return created file path or None."""
    if work_type == "book":
        script = ADD_BOOK_SCRIPT
        title = work.get("title_en") or work.get("title_cn") or ""
        if not title:
            return None
        cmd = ["python3", str(script), title]
    else:  # movie tag
        work_type = (work.get("type") or "movie").lower()
        title = work.get("title_en") or work.get("title_cn") or ""
        if not title:
            return None
        script = ADD_MOVIE_SCRIPT
        cmd = [
            "python3",
            str(script),
            title,
            "--type",
            work_type,
        ]
        if work.get("title_cn"):
            cmd += ["--title-cn", work["title_cn"]]

    print(f"    ▶ 自动建档: {' '.join(cmd[2:])}")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=script.parent)
    if proc.returncode != 0:
        print(f"    ❌ 建档失败: {proc.stderr[:300]}")
        return None
    # add_book.py 输出 "Created: <path>"，add_movie.py 输出 "已创建: <path>"
    m = re.search(r"(?:已创建|Created)[:：]?\s*(.+)", proc.stdout)
    if not m:
        print(f"    ⚠️  无法从输出解析文件路径: {proc.stdout[:200]}")
        return None
    created = Path(m.group(1).strip())
    return created if created.exists() else None


# --- Tracker ---------------------------------------------------------
def load_tracker() -> dict:
    if TRACKER_PATH.exists():
        try:
            return json.loads(TRACKER_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_tracker(tracker: dict) -> None:
    TRACKER_PATH.write_text(
        json.dumps(tracker, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# --- Main ------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Sync tagged daily-note entries to Books/Movies shelves.")
    parser.add_argument("--days", type=int, default=30, help="回溯天数（默认 30）")
    parser.add_argument("--tag", choices=["book", "movie"], help="只处理某一类标签")
    parser.add_argument("--dry-run", action="store_true", help="预览，不写文件")
    parser.add_argument("--force", action="store_true", help="忽略 tracker 重跑")
    parser.add_argument("--reset", action="store_true", help="清空 tracker 再跑")
    parser.add_argument("--batch", action="store_true", help="多候选时跳过（非交互）")
    args = parser.parse_args()

    if args.reset:
        if TRACKER_PATH.exists():
            TRACKER_PATH.unlink()
        print("🔄 tracker 已清空")

    try:
        api_key = get_api_key()
    except Exception as e:
        print(f"❌ 无法读取 API key: {e}")
        sys.exit(1)

    tracker = load_tracker()
    entries = list(extract_tagged_entries(args.days, args.tag))
    print(f"🔍 扫描最近 {args.days} 天，命中 {len(entries)} 条 #Book/#Movie 条目")

    synced = 0
    skipped = 0
    created_files = 0

    for entry in entries:
        key = f"{entry['source_file']}#{entry['timestamp']}"
        if not args.force and key in tracker:
            skipped += 1
            continue

        print(f"\n▶ {entry['date']} · {entry['heading'][:50]} [#{entry['tag_type']}]")
        works = extract_works(entry, api_key)
        if not works:
            print("    (未能提取作品)")
            continue

        tracker_targets = list(tracker.get(key, []))
        all_ok = True  # every work in this entry resolved to a target

        for work in works:
            label = work.get("title_cn") or work.get("title_en") or "?"
            print(f"  • {label} ({work.get('type','?')})")

            # 按每部作品自己的 type 分流，不跟条目标签走：
            # 一条 #Book 笔记里可以顺口提到电影/游戏，反之亦然。
            work_type = (work.get("type") or entry["tag_type"]).lower()
            target_dir = BOOKS_DIR if work_type == "book" else MOVIES_DIR

            matches = find_match(work, target_dir)
            target = None
            if len(matches) == 1:
                target = matches[0]
                print(f"    → {target.relative_to(VAULT_ROOT)}")
            elif len(matches) == 0:
                if args.dry_run:
                    print("    (dry-run: 会自动建档)")
                    continue
                target = auto_create(work, work_type)
                if target:
                    created_files += 1
                    print(f"    ✅ 新建: {target.relative_to(VAULT_ROOT)}")
                else:
                    all_ok = False  # build failed (e.g. API down) -> retry next run
                    continue
            else:
                print(f"    多个匹配 ({len(matches)}):")
                for i, m in enumerate(matches[:5]):
                    print(f"      [{i}] {m.relative_to(VAULT_ROOT)}")
                if args.batch:
                    print("    (batch: 跳过)")
                    all_ok = False
                    continue
                choice = input("    选择编号 (回车跳过): ").strip()
                if not choice:
                    all_ok = False
                    continue
                try:
                    target = matches[int(choice)]
                except (ValueError, IndexError):
                    all_ok = False
                    continue

            if target is None or args.dry_run:
                continue

            if append_followup(target, entry):
                synced += 1
            rel = str(target.relative_to(VAULT_ROOT))
            if rel not in tracker_targets:
                tracker_targets.append(rel)

        # Only mark the entry as done when EVERY work resolved. If any work failed
        # (API down, ambiguous match, etc.) leave the key unrecorded so the next run
        # retries the failed works. append_followup is idempotent, so the already-
        # synced works in the same entry won't be duplicated on that retry.
        if not args.dry_run and works and all_ok:
            tracker[key] = tracker_targets
            save_tracker(tracker)

    if args.dry_run:
        print(f"\n[dry-run] 模拟处理 {len(entries)} 条条目，跳过 {skipped} 条已同步")
    else:
        print(
            f"\n✅ 完成。追加 {synced} 次，自动建档 {created_files} 个，跳过已同步 {skipped} 条"
        )


if __name__ == "__main__":
    main()
