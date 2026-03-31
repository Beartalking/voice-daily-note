# Voice Daily Note — Project Plan

## Overview

One-command pipeline that converts voice memos into polished daily Markdown notes, then generates Twitter CN social posts from selected entries.

```
Recording/*.wav → transcripts/*.txt → refine → Obsidian Daily Notes
                                        ↓ (#Convo entries)
                                   auto-append structured summary
                                        ↓ (#Share entries)
                              Bear Content Vault/Social Posts/drafts/manual/YYYY-MM/
                              (Twitter CN only, reads Daily Notes directly)
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

### Share 流水线简化 (v1.6)
- `share_to_social.py` 去掉 `sharing_input/` 中间目录，直接从 Obsidian Daily Notes 扫描 `#Share` 条目
- 保留 7 天窗口 + 按标题去重的幂等逻辑（v1.6.1 从按日期去重改为按标题去重，同一天新增 #Share 条目不再被跳过）
- 输出仍写入 `Social Posts/drafts/manual/`

### #Convo 对话摘要 (v1.7)
- `refinement_prompt.py` 新增 `#Convo` 标签，支持多标签组合（如 `#Work #Convo`）
- `convo_summary.py` 扫描精修笔记中的 `#Convo` 条目，调 Claude 生成结构化摘要（场景、参与者、要点、下一步行动）
- 摘要追加在原文下方，幂等：已有摘要自动跳过
- 缺少上下文时用 `[待补充]` 占位；录音开头/结尾有场景说明时自动提取
- `pipeline.py` Step 2 精修后自动执行 Step 2.5 Convo 摘要

### Append 模式 + Ledger 去重 (v1.8)
- `refine.py` 已有笔记不再跳过，改为 append 新内容（`---` 分隔），保留用户手写内容
- 新增 `.refined_ledger.json` 追踪已精修的 transcript 文件名，按 date 分组
- 只精修新增 transcript，已处理的自动跳过；`--force` 跳过 ledger 全量重跑
- 修复旧逻辑：之前已有笔记直接跳过，导致当天新录音内容丢失

### 流水线 A→B 衔接 + 可配置回溯 (v1.9)
- `share_to_social.py` 新增 `--days` 参数，回溯天数可配置（默认 7 天），替代硬编码
- 流水线 B 默认直接从 Obsidian vault 扫描，A 完成后 B 自动衔接，不再需要手动复制文件到 `sharing_input/`
- `--input-dir` 保留作为 override，但不再是主流程
- SKILL.md 文档同步更新

---

## Backlog

- [ ] Chunk long audio before transcription (support recordings > 30 min)

- [ ] Post-refinement character count validation with auto-retry if content shrinks > 15%

- [ ] iPhone Voice Memo `.m4a` filename pattern support（当前需手动重命名为 `YYYYMMDD-N.m4a` 格式）
