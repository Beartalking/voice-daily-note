#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 1: Audio transcription via Buzz CLI with whisper fallback."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple

from config import (
    AUDIO_EXTENSIONS,
    BUZZ_CLI,
    RECORDING_DIR,
    TRANSCRIBE_LANGUAGE,
    TRANSCRIPTS_DIR,
    WHISPER_MODEL_SIZE,
)

# ── Timestamp extraction patterns ────────────────────────────────────
# Recorder: TX00_MIC031_20260212_175200_orig.wav
TS_FULL_RE = re.compile(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})")
# Voice Memo: 20260212-1.wav
TS_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})-(\d+)")


@dataclass
class AudioFile:
    """Represents a discovered audio file with its extracted metadata."""

    path: Path
    date: str  # YYYY-MM-DD
    time: str  # HH:MM:SS or "00:00:00" if unknown
    seq: int  # sequence number for ordering within same timestamp

    @property
    def transcript_path(self) -> Path:
        return TRANSCRIPTS_DIR / f"{self.path.stem}.txt"


def extract_timestamp(filename: str) -> Optional[tuple[str, str, int]]:
    """Extract (date, time, seq) from filename. Returns None if no match."""
    # Try full timestamp first: YYYYMMDD_HHMMSS
    m = TS_FULL_RE.search(filename)
    if m:
        y, mo, d, hh, mm, ss = m.groups()
        return f"{y}-{mo}-{d}", f"{hh}:{mm}:{ss}", 0

    # Try date-only: YYYYMMDD-N
    m = TS_DATE_RE.match(filename)
    if m:
        y, mo, d, seq = m.groups()
        return f"{y}-{mo}-{d}", "00:00:00", int(seq)

    return None


def discover_audio_files() -> list[AudioFile]:
    """Find all audio files in Recording/ and extract timestamps."""
    if not RECORDING_DIR.exists():
        return []

    files = []
    skipped = []

    for p in sorted(RECORDING_DIR.iterdir()):
        if p.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        ts = extract_timestamp(p.name)
        if ts is None:
            skipped.append(p.name)
            continue
        date, time, seq = ts
        files.append(AudioFile(path=p, date=date, time=time, seq=seq))

    if skipped:
        print(f"  Skipped {len(skipped)} files (no timestamp in name):")
        for name in skipped[:5]:
            print(f"    - {name}")
        if len(skipped) > 5:
            print(f"    ... and {len(skipped) - 5} more")

    # Sort by date, time, then sequence
    files.sort(key=lambda f: (f.date, f.time, f.seq))
    return files


def _transcribe_buzz(audio_path: Path) -> bool:
    """Transcribe using Buzz CLI. Returns True on success."""
    cmd = [
        BUZZ_CLI,
        "--task", "transcribe",
        "--model-type", "whisper",
        "--model-size", WHISPER_MODEL_SIZE,
        "--language", TRANSCRIBE_LANGUAGE,
        "--txt",
        "--output-directory", str(TRANSCRIPTS_DIR),
        "--hide-gui",
        str(audio_path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600
        )
        if result.returncode == 0:
            return True
        print(f"    Buzz CLI error (code {result.returncode}): {result.stderr[:200]}")
        return False
    except FileNotFoundError:
        print("    Buzz CLI not found at expected path")
        return False
    except subprocess.TimeoutExpired:
        print("    Buzz CLI timed out (10 min)")
        return False


def _transcribe_whisper(audio_path: Path) -> bool:
    """Transcribe using whisper Python library. Returns True on success."""
    try:
        import whisper
    except ImportError:
        print("    whisper Python package not available")
        return False

    try:
        model = whisper.load_model(WHISPER_MODEL_SIZE)
        result = model.transcribe(str(audio_path), language=TRANSCRIBE_LANGUAGE)
        text = result.get("text", "")
        if not text.strip():
            print("    whisper returned empty transcription")
            return False
        output_path = TRANSCRIPTS_DIR / f"{audio_path.stem}.txt"
        output_path.write_text(text, encoding="utf-8")
        return True
    except Exception as e:
        print(f"    whisper error: {e}")
        return False


def _buzz_available() -> bool:
    """Check if Buzz CLI is available."""
    return Path(BUZZ_CLI).exists()


def transcribe_all(
    files: list[AudioFile],
    engine: str = "buzz",
    force: bool = False,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """
    Transcribe all audio files.
    Returns (success_count, skipped_count, failed_count).
    """
    success = 0
    skipped = 0
    failed = 0

    use_buzz = engine == "buzz" and _buzz_available()
    if engine == "buzz" and not use_buzz:
        print("  Buzz CLI not available, falling back to whisper")

    for af in files:
        # Idempotency: skip if transcript exists
        if af.transcript_path.exists() and not force:
            print(f"  [SKIP] {af.path.name} (transcript exists)")
            skipped += 1
            continue

        if dry_run:
            print(f"  [DRY-RUN] Would transcribe: {af.path.name} -> {af.transcript_path.name}")
            skipped += 1
            continue

        print(f"  Transcribing: {af.path.name}")

        ok = False
        if use_buzz:
            ok = _transcribe_buzz(af.path)
            if not ok:
                print("    Buzz failed, trying whisper fallback...")
                ok = _transcribe_whisper(af.path)
        else:
            ok = _transcribe_whisper(af.path)

        if ok:
            print(f"    -> {af.transcript_path.name}")
            success += 1
        else:
            print(f"    FAILED: {af.path.name}")
            failed += 1

    return success, skipped, failed
