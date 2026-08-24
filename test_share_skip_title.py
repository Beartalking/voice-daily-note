#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained regression check for 流水线 B 的 --skip-title 排除机制.

This repo has no test suite and no test framework installed — so this is a
plain script, not a pytest file. Run it directly:

    python3 test_share_skip_title.py

It exits 0 and prints "OK" on success, or prints a traceback and exits 1.

Why it exists: before --skip-title, the only reliable way to stop a #Share
entry from being turned into a post was to go back into the daily note and
remove the tag. Editing sharing_output/01_extracted.md did nothing (Step 1
overwrites it unconditionally), and deleting the generated draft did nothing
either (dedup only looks for titles that still exist in the Content Vault),
so any entry still inside the look-back window came straight back on the next
run. Bear hit this twice — 2026-08-13 and again 2026-08-20 (《深夜惊魂记》).

Nothing real is touched: the daily notes are fixtures in a temp directory
(passed via input_dir) and _collect_processed_titles is monkeypatched to an
empty result, so the real Obsidian vault and Content Vault are never read.
No network call is made — extraction runs entirely before the Claude step.
"""
from __future__ import annotations

import io
import shutil
import tempfile
import traceback
from contextlib import redirect_stdout
from pathlib import Path

import share_to_social

# Well outside any realistic look-back window, so the fixture dates below
# never age out and the check stays deterministic.
DAYS_BACK = 3650

NOTE = """---
date: 2026-08-14
---

## 第二次美术馆人体速写练习
**场景**：个人生活与艺术学习
**标签**： #Diary #Share

---
今天是第二次到美术馆画人体速写，先画腰部会容易一些。

## 深夜惊魂记
**场景**：生活记录
**标签**： #Diary #Share

---
晚上一个人看恐怖片，阳台的门突然自己打开了。

## Obsidian vs Notion
**场景**：工具思考
**标签**： #Work #Share

---
两个工具的定位其实完全不同。
"""


def _make_vault(base: Path) -> None:
    note_dir = base / "2026" / "08"
    note_dir.mkdir(parents=True)
    (note_dir / "2026-08-14.md").write_text(NOTE, encoding="utf-8")


def _extract(base: Path, skip_titles=None, force: bool = False):
    """Run extraction against the fixture vault, swallowing progress output."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        entries = share_to_social.extract_share_entries_from_daily_notes(
            input_dir=str(base),
            force=force,
            days_back=DAYS_BACK,
            skip_titles=skip_titles,
        )
    return entries, buf.getvalue()


def test_skip_title_excludes_that_entry_and_keeps_the_rest():
    """The named entry is dropped; every other #Share entry still comes through."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="share_skip_check_"))
    try:
        _make_vault(tmp_dir)

        baseline, _ = _extract(tmp_dir)
        titles = [e.title for e in baseline]
        assert titles == [
            "第二次美术馆人体速写练习",
            "深夜惊魂记",
            "Obsidian vs Notion",
        ], f"fixture should yield 3 entries, got {titles}"

        entries, out = _extract(tmp_dir, skip_titles=["深夜惊魂记"])
        titles = [e.title for e in entries]
        assert titles == [
            "第二次美术馆人体速写练习",
            "Obsidian vs Notion",
        ], f"skipped entry should be gone, got {titles}"
        assert "深夜惊魂记" in out, "the skip should be reported on stdout, not silent"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_skip_title_matches_a_partial_title():
    """Bear can type a fragment instead of the exact title."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="share_skip_check_"))
    try:
        _make_vault(tmp_dir)

        entries, _ = _extract(tmp_dir, skip_titles=["深夜惊魂"])
        titles = [e.title for e in entries]
        assert "深夜惊魂记" not in titles, f"partial title should match, got {titles}"
        assert len(titles) == 2, f"only the one entry should be dropped, got {titles}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_skip_title_ignores_case_and_punctuation():
    """Matching is normalised the same way dedup normalises titles."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="share_skip_check_"))
    try:
        _make_vault(tmp_dir)

        entries, _ = _extract(tmp_dir, skip_titles=["obsidian  vs.  notion"])
        titles = [e.title for e in entries]
        assert "Obsidian vs Notion" not in titles, f"should match, got {titles}"
        assert len(titles) == 2, f"only the one entry should be dropped, got {titles}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_skip_title_still_applies_under_force():
    """--force turns off dedup; an explicit exclusion must still be honoured."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="share_skip_check_"))
    try:
        _make_vault(tmp_dir)

        entries, _ = _extract(tmp_dir, skip_titles=["深夜惊魂记"], force=True)
        titles = [e.title for e in entries]
        assert "深夜惊魂记" not in titles, f"--force must not defeat --skip-title, got {titles}"
        assert len(titles) == 2, f"force should keep the other entries, got {titles}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_no_skip_titles_changes_nothing():
    """The default path is untouched when the flag is absent."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="share_skip_check_"))
    try:
        _make_vault(tmp_dir)

        for skip in (None, []):
            entries, _ = _extract(tmp_dir, skip_titles=skip)
            assert len(entries) == 3, f"skip_titles={skip!r} should keep all 3, got {len(entries)}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> int:
    # Dedup normally scans the real Content Vault; stub it so this check never
    # depends on what happens to be sitting in drafts/ or published/.
    real_collect = share_to_social._collect_processed_titles
    share_to_social._collect_processed_titles = lambda: (set(), {})
    try:
        for test in (
            test_skip_title_excludes_that_entry_and_keeps_the_rest,
            test_skip_title_matches_a_partial_title,
            test_skip_title_ignores_case_and_punctuation,
            test_skip_title_still_applies_under_force,
            test_no_skip_titles_changes_nothing,
        ):
            test()
            print(f"  ok  {test.__name__}")
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        share_to_social._collect_processed_titles = real_collect

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
