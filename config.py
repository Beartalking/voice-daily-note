#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Configuration constants, CLI argument parsing, and directory setup."""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

# ── Directory Structure ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent

# Load .env file from project root
load_dotenv(BASE_DIR / ".env")
RECORDING_DIR = BASE_DIR / "Recording"
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", str(BASE_DIR / "output")))
ARCHIVE_DIR = BASE_DIR / "archive"
SHARING_INPUT_DIR = BASE_DIR / "sharing_input"
SHARING_OUTPUT_DIR = BASE_DIR / "sharing_output"

# ── Transcription ────────────────────────────────────────────────────
BUZZ_CLI = "/Applications/Buzz.app/Contents/MacOS/Buzz"
WHISPER_MODEL_SIZE = "medium"
TRANSCRIBE_LANGUAGE = "zh"
AUDIO_EXTENSIONS = {".wav", ".m4a", ".mp3"}
BUZZ_TIMEOUT = 120  # 2 minutes per file; falls back to Whisper on timeout

# ── Claude API ───────────────────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
MIN_MAX_TOKENS = 4096
TOKEN_MULTIPLIER = 1.2
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds

# ── Quality Check ────────────────────────────────────────────────────
MAX_CHAR_SHRINK_RATIO = 0.15  # warn if refined text shrinks more than 15%


def get_api_key() -> str:
    """Get Anthropic API key from environment."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise SystemExit(
            "ERROR: ANTHROPIC_API_KEY environment variable not set.\n"
            "Export it before running the refine step:\n"
            "  export ANTHROPIC_API_KEY='sk-ant-...'"
        )
    return key


def ensure_dirs():
    """Create required directories if they don't exist."""
    for d in (RECORDING_DIR, TRANSCRIPTS_DIR, OUTPUT_DIR, ARCHIVE_DIR):
        d.mkdir(parents=True, exist_ok=True)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Voice Daily Note: automated transcription & refinement pipeline"
    )
    parser.add_argument(
        "--step",
        choices=["transcribe", "refine"],
        default=None,
        help="Run only a specific step (default: run full pipeline)",
    )
    parser.add_argument(
        "--engine",
        choices=["buzz", "whisper"],
        default="buzz",
        help="Transcription engine (default: buzz, falls back to whisper automatically)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-processing even if output files already exist",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be processed without actually running",
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Skip archiving audio files after processing",
    )
    return parser.parse_args()
