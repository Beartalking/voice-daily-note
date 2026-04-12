#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared utility for writing/appending entries to Obsidian Daily Notes."""
from __future__ import annotations

from pathlib import Path

from config import OUTPUT_DIR


def get_daily_note_path(date):
    # type: (str) -> Path
    """Return the full path for a daily note: OUTPUT_DIR/YYYY/MM/YYYY-MM-DD.md"""
    year, month = date[:4], date[5:7]
    return OUTPUT_DIR / year / month / f"{date}.md"


def write_daily_note(date, entry_count, text, append=False):
    # type: (str, int, str, bool) -> Path
    """Write or append a daily note entry.

    Args:
        date: ISO date string (YYYY-MM-DD)
        entry_count: number of entries (used in front matter for new files)
        text: formatted markdown text to write
        append: if True and file exists, append with separator

    Returns:
        Path to the written file
    """
    output_path = get_daily_note_path(date)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if append and output_path.exists():
        existing = output_path.read_text(encoding="utf-8")
        separator = "\n\n---\n\n"
        content = existing.rstrip() + separator + text
        output_path.write_text(content, encoding="utf-8")
    else:
        front_matter = f"---\ndate: {date}\ntype: daily-note\nentries: {entry_count}\n---\n\n"
        content = front_matter + text
        output_path.write_text(content, encoding="utf-8")

    return output_path
