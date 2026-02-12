#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from pathlib import Path
from typing import Optional, Tuple, List

# 固定目录结构（按你说的来）
DESKTOP = Path.home() / "Desktop"
INPUT_DIR = DESKTOP / "transcripts"
OUTPUT_MD = DESKTOP / "weekly_raw.md"

# 从文件名中提取：YYYY_MM_DD_HH_MM_SS
TS_RE = re.compile(r"(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{2})")

def extract_ts(filename: str) -> Optional[Tuple[str, str]]:
    """
    返回 (date_str 'YYYY-MM-DD', time_str 'HH:MM:SS')
    提取不到则返回 None
    """
    m = TS_RE.search(filename)
    if not m:
        return None
    y, mo, d, hh, mm, ss = m.groups()
    return f"{y}-{mo}-{d}", f"{hh}:{mm}:{ss}"

def read_text_raw(p: Path) -> str:
    """
    尽可能原样读取：
    - 不做 strip
    - 不替换换行
    - 只处理常见编码 utf-8 / utf-8-sig
    """
    data = p.read_bytes()
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    # 兜底：保留内容，替换不可解码字符
    return data.decode("utf-8", errors="replace")

def main():
    if not INPUT_DIR.exists() or not INPUT_DIR.is_dir():
        raise SystemExit(
            f"ERROR: transcripts folder not found:\n  {INPUT_DIR}\n"
            f"Make sure your txt files are in: ~/Desktop/transcripts/"
        )

    txt_files = sorted(INPUT_DIR.glob("*.txt"))
    if not txt_files:
        raise SystemExit(
            f"ERROR: no .txt files found in:\n  {INPUT_DIR}\n"
            f"Put your transcript txt files there and run again."
        )

    items: List[Tuple[str, str, str, str]] = []
    skipped: List[str] = []

    for p in txt_files:
        ts = extract_ts(p.name)
        if not ts:
            skipped.append(p.name)
            continue
        date_str, time_str = ts
        content = read_text_raw(p)
        items.append((date_str, time_str, p.name, content))

    if not items:
        raise SystemExit(
            "ERROR: No files with valid timestamp in filename.\n"
            "Expected filename to include: YYYY_MM_DD_HH_MM_SS\n"
            "Example: 2026_01_25_18_02_43 (translated on ...).txt"
        )

    # 排序：日期、时间、文件名（防止同秒冲突）
    items.sort(key=lambda x: (x[0], x[1], x[2]))

    lines: List[str] = []
    current_date = None

    for date_str, time_str, fname, content in items:
        if date_str != current_date:
            current_date = date_str
            if lines:
                lines.append("\n")  # 不同日期之间空一行
            lines.append(f"# {date_str}\n\n")

        lines.append(f"## {time_str}\n\n")

        # 正文原样写入
        lines.append(content)

        # 确保每条后面至少有一个换行，方便下条标题不黏住正文
        if not content.endswith("\n"):
            lines.append("\n")
        lines.append("\n")

    OUTPUT_MD.write_text("".join(lines), encoding="utf-8")

    print("Done ✅")
    print(f"Input folder : {INPUT_DIR}")
    print(f"Output file  : {OUTPUT_MD}")
    print(f"Total merged : {len(items)}")
    if skipped:
        print(f"Skipped (no timestamp in filename): {len(skipped)}")
        for name in skipped[:10]:
            print(f"  - {name}")
        if len(skipped) > 10:
            print("  ...")

if __name__ == "__main__":
    main()
