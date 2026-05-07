#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot migration: legacy Books/ + Movies/ -> 40_Books/ + 41_Movies/.

For every file in the legacy directories under year subfolders:
  - Find a counterpart file in the new directory by exact name first,
    then by fuzzy stem match (case-insensitive substring overlap).
  - If a counterpart exists: extract `### YYYY-MM-DD · ...` blocks from
    the legacy file's `## 后续笔记` section, append any blocks whose
    "date + heading" combo is NOT already in the counterpart's
    `## 后续笔记` section.
  - If no counterpart: move the legacy file as-is into the new directory.

Asset files (cover images) are moved if absent in the new Assets folder.
After migration the legacy file/dir is deleted only when fully drained.

Run with --dry-run first to preview.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

VAULT_ROOT = Path(
    "/Users/bearliu/Library/Mobile Documents/iCloud~md~obsidian/Documents/Bear Vault"
)
PAIRS = [
    (VAULT_ROOT / "Books", VAULT_ROOT / "40_Books"),
    (VAULT_ROOT / "Movies", VAULT_ROOT / "41_Movies"),
]

ENTRY_HEADING_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2})\s*·\s*(.+?)\s*$", re.MULTILINE)
SECTION_RE = re.compile(r"##\s*后续笔记\s*\n", re.MULTILINE)


def extract_followups(text):
    """Return list of (date, title, full_block_text) for each ### entry
    under '## 后续笔记'. full_block_text spans the heading line through
    the line before the next ### or end of file.
    """
    m = SECTION_RE.search(text)
    if not m:
        return []
    section = text[m.end():]
    headings = list(ENTRY_HEADING_RE.finditer(section))
    if not headings:
        return []
    blocks = []
    for i, h in enumerate(headings):
        start = h.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(section)
        block = section[start:end].rstrip() + "\n"
        blocks.append((h.group(1), h.group(2).strip(), block))
    return blocks


def _tokens(stem):
    """Lowercase alphanumeric token set, ignoring punctuation/spaces."""
    return {t for t in re.split(r"[^a-zA-Z0-9一-鿿]+", stem.lower()) if t}


def match_counterpart(legacy_file, new_year_dir):
    """Find counterpart file in new_year_dir by exact name, substring,
    or token Jaccard >= 0.5."""
    exact = new_year_dir / legacy_file.name
    if exact.exists():
        return exact
    if not new_year_dir.exists():
        return None

    legacy_stem = legacy_file.stem.lower()
    legacy_tokens = _tokens(legacy_file.stem)
    candidates = []
    for candidate in new_year_dir.glob("*.md"):
        cand_stem = candidate.stem.lower()
        cand_tokens = _tokens(candidate.stem)
        # Substring (either direction)
        norm_l = re.sub(r"[\s\-—_:.,'\"]+", "", legacy_stem)
        norm_c = re.sub(r"[\s\-—_:.,'\"]+", "", cand_stem)
        if norm_l and (norm_l in norm_c or norm_c in norm_l):
            score = min(len(norm_l), len(norm_c)) / max(len(norm_l), len(norm_c), 1)
            candidates.append((candidate, score))
            continue
        # Token Jaccard
        if legacy_tokens and cand_tokens:
            inter = legacy_tokens & cand_tokens
            union = legacy_tokens | cand_tokens
            jaccard = len(inter) / len(union)
            if jaccard >= 0.5:
                candidates.append((candidate, jaccard))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


def merge_followups(target_path, new_blocks, dry_run):
    """Append any missing followup blocks to target's '## 后续笔记' section."""
    text = target_path.read_text(encoding="utf-8")
    existing = {(d, t) for d, t, _ in extract_followups(text)}
    to_add = [(d, t, b) for d, t, b in new_blocks if (d, t) not in existing]
    if not to_add:
        return 0
    if dry_run:
        return len(to_add)
    if SECTION_RE.search(text):
        # append at end of file under the existing section
        if not text.endswith("\n"):
            text += "\n"
        text += "\n---\n\n" + "\n---\n\n".join(b for _, _, b in to_add)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += "\n## 后续笔记\n\n" + "\n---\n\n".join(b for _, _, b in to_add)
    target_path.write_text(text, encoding="utf-8")
    return len(to_add)


def move_assets(legacy_assets, new_assets, dry_run):
    """Move legacy asset files into new_assets dir; skip if same name exists."""
    moved, skipped = [], []
    if not legacy_assets.exists():
        return moved, skipped
    new_assets.mkdir(parents=True, exist_ok=True)
    for f in legacy_assets.iterdir():
        if not f.is_file():
            continue
        target = new_assets / f.name
        if target.exists():
            skipped.append(f.name)
            continue
        if dry_run:
            moved.append(f.name)
            continue
        shutil.move(str(f), str(target))
        moved.append(f.name)
    return moved, skipped


def migrate_pair(legacy_root, new_root, dry_run):
    print(f"\n=== {legacy_root.name} -> {new_root.name} ===")
    if not legacy_root.exists():
        print("  (skip) legacy dir does not exist")
        return
    for year_dir in sorted(p for p in legacy_root.iterdir() if p.is_dir() and p.name != "Assets"):
        new_year_dir = new_root / year_dir.name
        new_year_dir.mkdir(parents=True, exist_ok=True)

        for f in sorted(year_dir.glob("*.md")):
            counterpart = match_counterpart(f, new_year_dir)
            if counterpart:
                new_blocks = extract_followups(f.read_text(encoding="utf-8"))
                added = merge_followups(counterpart, new_blocks, dry_run)
                if added:
                    print(f"  [merge] {f.name} -> {counterpart.name}: +{added} 后续笔记")
                else:
                    print(f"  [dup ] {f.name} -> {counterpart.name}: already in sync")
                if not dry_run:
                    f.unlink()
            else:
                target = new_year_dir / f.name
                print(f"  [move ] {f.name} -> {new_year_dir.relative_to(VAULT_ROOT)}/")
                if not dry_run:
                    shutil.move(str(f), str(target))

        # Assets within the year folder
        legacy_assets = year_dir / "Assets"
        new_assets = new_year_dir / "Assets"
        if legacy_assets.exists():
            moved, skipped = move_assets(legacy_assets, new_assets, dry_run)
            for n in moved:
                print(f"  [asset move ] {year_dir.name}/Assets/{n}")
            for n in skipped:
                print(f"  [asset dup  ] {year_dir.name}/Assets/{n} (already in new)")

        # Cleanup empty legacy year dirs
        if not dry_run:
            try:
                if legacy_assets.exists() and not any(legacy_assets.iterdir()):
                    legacy_assets.rmdir()
                if not any(year_dir.iterdir()):
                    year_dir.rmdir()
                    print(f"  [rmdir] {legacy_root.name}/{year_dir.name}/")
            except OSError:
                pass

    # Top-level legacy root cleanup
    if not dry_run:
        try:
            if legacy_root.exists() and not any(legacy_root.iterdir()):
                legacy_root.rmdir()
                print(f"  [rmdir] {legacy_root.name}/")
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(description="Migrate legacy Books/Movies to 40_Books/41_Movies.")
    parser.add_argument("--dry-run", action="store_true", help="preview only")
    args = parser.parse_args()

    for legacy, new in PAIRS:
        migrate_pair(legacy, new, args.dry_run)

    print("\n✅ migration done" + (" (dry-run)" if args.dry_run else ""))


if __name__ == "__main__":
    sys.exit(main())
