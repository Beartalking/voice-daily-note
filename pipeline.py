#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Voice Daily Note: main pipeline orchestrating transcribe → refine → archive."""
from __future__ import annotations

import shutil
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from config import ARCHIVE_DIR, ARCHIVE_RETENTION_DAYS, RECORDING_DIR, ensure_dirs, parse_args
from convo_summary import summarize_convo_all
from refine import refine_all
from transcribe import discover_audio_files, transcribe_all


def archive_files(files, dry_run: bool = False) -> int:
    """Move processed audio files to archive/YYYY-MM-DD/ directories."""
    if not files:
        return 0

    # Group by date for archive subdirectories
    by_date: dict[str, list] = defaultdict(list)
    for af in files:
        by_date[af.date].append(af)

    moved = 0
    for date, date_files in sorted(by_date.items()):
        dest_dir = ARCHIVE_DIR / date
        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)

        for af in date_files:
            dest = dest_dir / af.path.name
            if dry_run:
                print(f"  [DRY-RUN] Would archive: {af.path.name} -> archive/{date}/")
            else:
                shutil.move(str(af.path), str(dest))
                print(f"  Archived: {af.path.name} -> archive/{date}/")
            moved += 1

    return moved


def cleanup_old_archives(dry_run: bool = False, retention_days: int = ARCHIVE_RETENTION_DAYS) -> int:
    """Delete archive subdirectories older than retention_days. Returns count of deleted dirs."""
    cutoff = date.today() - timedelta(days=retention_days)
    deleted = 0

    if not ARCHIVE_DIR.exists():
        return 0

    for subdir in sorted(ARCHIVE_DIR.iterdir()):
        if not subdir.is_dir():
            continue
        try:
            dir_date = date.fromisoformat(subdir.name)
        except ValueError:
            continue  # skip non-date directories

        if dir_date < cutoff:
            if dry_run:
                print(f"  [DRY-RUN] Would delete: archive/{subdir.name}/")
            else:
                shutil.rmtree(subdir)
                print(f"  Deleted: archive/{subdir.name}/")
            deleted += 1

    return deleted


def print_summary(
    step: Optional[str],
    audio_files: list,
    t_ok: int, t_skip: int, t_fail: int,
    r_ok: int, r_skip: int, r_fail: int,
    archived: int,
    deleted: int = 0,
):
    """Print a summary of the pipeline run."""
    print("\n" + "=" * 50)
    print("Pipeline Summary")
    print("=" * 50)

    if step is None or step == "transcribe":
        print(f"  Audio files found : {len(audio_files)}")
        dates = sorted(set(af.date for af in audio_files)) if audio_files else []
        if dates:
            print(f"  Date range        : {dates[0]} to {dates[-1]}")
        print(f"  Transcribed       : {t_ok} ok, {t_skip} skipped, {t_fail} failed")

    if step is None or step == "refine":
        print(f"  Refined           : {r_ok} ok, {r_skip} skipped, {r_fail} failed")

    if step is None and archived > 0:
        print(f"  Archived          : {archived} files")
    if step is None and deleted > 0:
        print(f"  Old archives del. : {deleted} dir(s) (>{ARCHIVE_RETENTION_DAYS}d)")

    print("=" * 50)


def main():
    args = parse_args()
    ensure_dirs()

    print("Voice Daily Note Pipeline")
    print("-" * 40)

    # Track results
    audio_files = []
    t_ok = t_skip = t_fail = 0
    r_ok = r_skip = r_fail = 0
    archived = 0
    deleted = 0

    # ── Step 1: Transcribe ───────────────────────────────────────
    if args.step is None or args.step == "transcribe":
        print("\n[Step 1] Discovering audio files...")
        audio_files = discover_audio_files()

        if not audio_files:
            print("  No audio files found in Recording/")
            if args.step == "transcribe":
                return
        else:
            dates = sorted(set(af.date for af in audio_files))
            print(f"  Found {len(audio_files)} files across {len(dates)} day(s)")
            for d in dates:
                count = sum(1 for af in audio_files if af.date == d)
                print(f"    {d}: {count} file(s)")

            print("\n[Step 1] Transcribing...")
            t_ok, t_skip, t_fail = transcribe_all(
                audio_files,
                engine=args.engine,
                force=args.force,
                dry_run=args.dry_run,
            )

    # ── Step 2: Refine ───────────────────────────────────────────
    if args.step is None or args.step == "refine":
        print("\n[Step 2] Refining transcripts...")
        r_ok, r_skip, r_fail = refine_all(
            force=args.force,
            dry_run=args.dry_run,
        )

    # ── Step 2.5: Convo Summaries ─────────────────────────────────
    if args.step is None or args.step == "refine":
        print("\n[Step 2.5] Generating #Convo summaries...")
        c_files, c_summaries = summarize_convo_all(
            force=args.force,
            dry_run=args.dry_run,
        )
        if c_summaries > 0:
            print(f"  Generated {c_summaries} summary(ies) across {c_files} file(s)")
        else:
            print("  No #Convo entries to summarize")

    # ── Step 3: Archive ──────────────────────────────────────────
    if args.step is None and not args.no_archive and audio_files:
        # Only archive if both transcribe and refine succeeded (no failures)
        if t_fail == 0 and r_fail == 0 and not args.dry_run:
            print("\n[Step 3] Archiving processed audio files...")
            archived = archive_files(audio_files)
        elif args.dry_run:
            print("\n[Step 3] Archive preview...")
            archived = archive_files(audio_files, dry_run=True)
        elif t_fail > 0 or r_fail > 0:
            print("\n[Step 3] Skipping archive (there were failures)")

    # ── Step 4: Cleanup old archives ─────────────────────────────
    if args.step is None:
        print(f"\n[Step 4] Cleaning up archives older than {ARCHIVE_RETENTION_DAYS} days...")
        deleted = cleanup_old_archives(dry_run=args.dry_run)
        if deleted == 0:
            print("  Nothing to clean up.")

    # ── Summary ──────────────────────────────────────────────────
    print_summary(
        args.step, audio_files,
        t_ok, t_skip, t_fail,
        r_ok, r_skip, r_fail,
        archived, deleted,
    )


if __name__ == "__main__":
    main()
