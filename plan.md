# Voice Daily Note — Project Plan

## Overview

One-command pipeline that converts voice memos into polished daily Markdown notes. Drop WAV files, run one command, get structured notes organized by date.

```
Recording/*.wav → transcripts/*.txt → output/YYYY-MM-DD.md → archive/
```

---

## Completed

### Phase 1: Core Pipeline ✅
- [x] `config.py` — constants, CLI argument parsing, directory setup
- [x] `refinement_prompt.py` — system prompt extracted from existing refinement instructions
- [x] `transcribe.py` — Buzz CLI primary + whisper Python fallback, dual filename pattern support
- [x] `refine.py` — date grouping, Claude API (Sonnet 4.5) with retry, YAML front matter output
- [x] `pipeline.py` — orchestrator: transcribe → refine → archive with summary
- [x] `.gitignore` + git repo initialized

### Phase 2: Reliability & Usability ✅
- [x] Buzz CLI output verification (check file actually exists after exit code 0)
- [x] Buzz timeout bumped to 30 min (was 10 min, caused false fallbacks)
- [x] `run-overnight.sh` — caffeinate + nohup + macOS notification + log file
- [x] First real-world test: 4 files across 3 days, all processed successfully

---

## Future Improvements

### Phase 3: Obsidian Integration
- [ ] Auto-copy output MD files to Obsidian vault directory
- [ ] Configurable vault path via `config.py` or `.env`
- [ ] Optional: add Obsidian-compatible tags and links

### Phase 4: Scheduling
- [ ] macOS LaunchAgent for fully automatic nightly runs
- [ ] Watch folder mode: auto-trigger when new files appear in `Recording/`

### Phase 5: Quality
- [ ] Post-refinement character count validation with auto-retry
- [ ] Support for longer recordings: chunk audio before transcription
- [ ] Side-by-side diff view of original vs refined text

### Phase 6: Multi-source
- [ ] iPhone Voice Memo `.m4a` filename pattern support (currently date-seq only)
- [ ] Drag-and-drop web UI for non-technical use
- [ ] Support additional LLM providers as refinement backend

---

## Architecture

```
pipeline.py          — Entry point, CLI, orchestration
├── config.py        — All constants and argument parsing
├── transcribe.py    — Audio → text (Buzz CLI / whisper)
├── refine.py        — Text → polished MD (Claude API)
└── refinement_prompt.py — System prompt for LLM refinement

run-overnight.sh     — Background runner with sleep prevention
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Buzz CLI first, whisper fallback | Buzz is ~3x faster but sometimes produces no output |
| `requests` instead of `anthropic` SDK | Zero new dependencies |
| One MD per day, not per recording | Matches daily note workflow in Obsidian |
| Archive after full success only | Prevents data loss if pipeline fails mid-run |
| Idempotent by default | Safe to re-run; `--force` to override |

## Dependencies

- Python 3.9+ (system)
- `requests` (already installed)
- Buzz.app 1.2.0 (already installed)
- `openai-whisper` (already installed, fallback)
- `ANTHROPIC_API_KEY` environment variable
