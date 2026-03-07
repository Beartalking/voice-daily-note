# Voice Daily Note — Project Plan

## Overview

One-command pipeline that converts voice memos into polished daily Markdown notes, then generates Twitter CN social posts from selected entries.

```
Recording/*.wav → transcripts/*.txt → output/YYYY-MM-DD.md → Obsidian Daily Notes
                                                    ↓ (#Share entries)
                              Bear Content Vault/Social Posts/drafts/manual/YYYY-MM/
                              (Twitter CN only)
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

### Social Post Generation (v1.3 → v1.4)
- `share_to_social.py` — replaces `share_to_linkedin.py`
- 简化为仅生成 Twitter CN（全文中文，无字数限制）
- LinkedIn EN 和 YouTube Shorts 已移除
- Output saves directly to Bear Content Vault manual drafts folder

### Buzz CLI Fix
- Fixed Buzz CLI: added missing `add` subcommand (was launching GUI and timing out)
- Added output filename rename logic (Buzz appends timestamp; normalize to `stem.txt`)

### Writing Style Integration (v1.5)
- `share_to_social.py` prompt 从简化版升级为基于 `writing-style.md` 的完整写作风格
- 注入：声音定位、70/30 叙事比例、句式节奏、标志性词汇、情绪回收技术、禁止清单、Twitter 结构模板、中英文混合规则
- 任务从"润色口语"升级为"用 Bear 声音重写"
- `#Share` 标签匹配改为大小写不敏感（`#share`、`#Share` 均可）
- 新增 `_sanitize_output()` 后处理：自动清除破折号（`—`/`——` → `，`）

---

## Backlog

- [ ] **会议/通话录音总结**：单独的 pipeline，输入一段会议或通话录音，输出结构化摘要（议题、决策、行动项），存入 Obsidian 或 Content Vault

- [ ] Chunk long audio before transcription (support recordings > 30 min)

- [ ] Post-refinement character count validation with auto-retry if content shrinks > 15%

- [ ] iPhone Voice Memo `.m4a` filename pattern support

- [ ] `sharing_input/` auto-cleanup: remove processed files after successful vault save
