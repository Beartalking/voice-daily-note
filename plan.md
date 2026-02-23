# Voice Daily Note — Project Plan

## Overview

One-command pipeline that converts voice memos into polished daily Markdown notes, then generates multi-platform social posts from selected entries.

```
Recording/*.wav → transcripts/*.txt → output/YYYY-MM-DD.md → Obsidian Daily Notes
                                                    ↓ (#Share entries)
                              Bear Content Vault/Social Posts/drafts/manual/YYYY-MM/
                              (Twitter CN + LinkedIn EN + YouTube Shorts per post)
```

---

## Completed

### Core Pipeline (v1.0)
- `config.py` — constants, CLI argument parsing, `.env` support
- `transcribe.py` — Buzz CLI primary + whisper Python fallback, dual filename pattern support
- `refine.py` — date grouping, Claude API with retry, YAML front matter output
- `pipeline.py` — orchestrator: transcribe → refine → archive with summary
- `run-overnight.sh` — caffeinate + nohup + macOS notification + log file
- Bilingual output: auto-detect language, preserve English + append Chinese translation
- `--force`, `--dry-run`, `--no-archive`, `--engine` CLI flags

### Obsidian Integration (v1.1)
- `OUTPUT_DIR` env var routes daily notes to Obsidian vault
- Daily notes land in Bear Vault/Daily notes/

### Share Pipeline (v1.2)
- `share_pipeline.py` — extract `#Share` entries from daily notes → Claude refinement → save individual posts to Bear Content Vault
- Support for multi-tag entries (`#Diary #Share`, `#Work #Share`)
- Per-post MD files saved to `Social Posts/drafts/manual/YYYY-MM/YYYY-MM-DD-title.md`

### Social Post Generation (v1.3)
- `share_to_social.py` — replaces `share_to_linkedin.py`
- Single Claude API call generates all 3 platforms per entry:
  - Twitter CN: full-length Chinese, no character limit
  - LinkedIn EN: English, LinkedIn-optimised tone
  - YouTube Shorts: title + 1–3 hashtags
- Output saves directly to Bear Content Vault manual drafts folder
- Fixed token budget (4x input multiplier to prevent truncation)

### Buzz CLI Fix
- Fixed Buzz CLI: added missing `add` subcommand (was launching GUI and timing out)
- Added output filename rename logic (Buzz appends timestamp; normalize to `stem.txt`)

---

## Backlog

- [ ] **会议/通话录音总结**：单独的 pipeline，输入一段会议或通话录音，输出结构化摘要（议题、决策、行动项），存入 Obsidian 或 Content Vault

- [ ] Chunk long audio before transcription (support recordings > 30 min)

- [ ] Post-refinement character count validation with auto-retry if content shrinks > 15%

- [ ] iPhone Voice Memo `.m4a` filename pattern support

- [ ] `sharing_input/` auto-cleanup: remove processed files after successful vault save
