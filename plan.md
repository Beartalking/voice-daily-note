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
- Daily notes land in Bear Vault/10_Daily/YYYY/MM/

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

### 流水线 D：书架同步 (v2.0)
- 新增 `#Book` / `#Movie` 标签（`refinement_prompt.py` 第 38–43、56、66 行）
- 新增 `bookshelf_sync.py`：扫 Daily Notes 带标签条目 → Claude 提取作品 → 模糊匹配 Books/Movies 现有文件 → 在目标文件 `## 后续笔记` 段末尾 append 新日期分节
- 独立 `bookshelf_sync_tracker.json` 做去重，键为 `{daily_note_path}#{timestamp}`
- 0 命中时自动调 `reader-library/add_book.py` 或 `movie-library/add_movie.py` 建档（游戏除外，需人工指定 Steam URL）
- 多命中时交互选择（`--batch` 模式跳过）
- 与流水线 B 并行工作，同一条笔记可同时带 `#Share #Book` 被两个流水线独立处理

### 流水线 A→B 衔接 + 可配置回溯 (v1.9)
- `share_to_social.py` 新增 `--days` 参数，回溯天数可配置（默认 7 天），替代硬编码
- 流水线 B 默认直接从 Obsidian vault 扫描，A 完成后 B 自动衔接，不再需要手动复制文件到 `sharing_input/`
- `--input-dir` 保留作为 override，但不再是主流程
- SKILL.md 文档同步更新

### 流水线 D 修复：按作品 type 分流 (v2.1)
- **Bug**：`bookshelf_sync.py` 用日记条目的标签（`entry["tag_type"]`）决定去 `40_Books/` 还是 `41_Movies/`，而不是用 Claude 提取出的每部作品自己的 `type`。后果：一条 `#Book` 笔记里顺口提到的电影会被 `add_book.py` 建进书库（2026-07-20《克拉拉与太阳》条目里提到的《人工智能》即中招）
- **修复**：`target_dir` 和 `auto_create()` 的分流点都下移到 work 循环内，按 `work["type"]` 判断，条目标签仅作兜底。一条笔记里书 / 电影 / 游戏混着提也能各归各库
- **同批发现的 TMDB 错配**：「后室」被译成 `The Backrooms` 后匹配到 *Into the Backrooms*（2019，12 分钟短片），真实片名是 `Backrooms`（2026，Kane Parsons，tmdb 1083381）。**译名多/少一个冠词就足以撞进同题材的另一部作品**，且光看片名核对不出来 —— 核对时要拿笔记里的具体情节去对 TMDB 简介（这次靠"家具店老板"对上 overview 里的 furniture showroom 才确认）
- 同类前科：commit 4d6bb0c（Chuck's Life 撞库）、`feedback_bookshelf_sync_chinese_title_hallucination` 记忆条目。**自动建档结果必须逐条核对，这条规矩不能省**
- 未动：「顺带提及也建档」的行为暂不收紧（Bear 决定先观察一轮），提取 prompt 保持原样

### 流水线 D 修复：跳过 voice-capture 归档块 (v2.2, 2026-07-31)
- **Bug**：`bookshelf_sync.py` 读日记后直接 `split_blocks`，没剥掉 voice-capture 的折叠归档块。归档块里的已路由命令自带 `**标签**` 行，一条 `#Note #Book` 的提醒（2026-07-12「下载 Jim Dale 版哈利波特有声书」）因此被当成读书条目，且归属错到了它前面那个 `## ` 条目的标题上
- **后果**：每次运行都提取失败 → `all_ok=False` → 永不写 tracker → 30 天窗口内每跑一次白调一次 Claude
- **修复**：新增 `ROUTED_ARCHIVE_RE`，`extract_tagged_entries()` 读文件后先 sub 掉再切块。正则与 `insight-finder/note_utils.py` 的 `strip_routed_archive` 保持一致（两个项目各自独立仓，六行正则选择复制而非跨仓 import）
- **验证**：dry-run 命中数 11 → 10，误报条目消失，其余 10 条识别与匹配不受影响
- 同批同步：《一个故事的99种讲法》→ Books、《杀手》三部曲 → `Hitman Trilogy.md`。后者是多候选人工选的，Claude 把 Alan Wake 也列为候选 —— 又一次印证中文标题模糊匹配要人工把关

### 流水线 C 修复：并发锁 (v2.3, 2026-08-06)
- **Bug**：launchd 每天 09:30 跑流水线 C，同一分钟手动跑 `/capture` 会和它撞车。两个进程各自 `_load_ledger()` 读到同一份旧 ledger，谁都没看见对方的工作，同一个 inbox 文件被追加进日记两遍
- **实例**：`2026-08-04_220755.txt`（「ChatGPT 语音对话体验」）在 `2026-08-04.md` 里出现两次，已手工去重
- **修复**：`text_inbox.py` 新增 `_inbox_lock()`，用 `fcntl.flock(LOCK_EX | LOCK_NB)` 把整轮运行（discover → 处理 → 写 ledger → 移文件）串行化。原 `process_inbox()` 函数体改名 `_process_inbox()`，外层负责拿锁；拿不到就打印 `[LOCKED]` 返回 `(0,0,0)`，不抛异常，pipeline 汇总照常显示
- **为什么用 flock 而不是 PID 文件**：内核在进程退出时自动释放。崩溃/被 kill 的运行不会留下永久堵死后续每一次运行的死锁 —— PID 文件方案的典型失败模式是几个月后才发现管道悄悄停摆
- **锁文件位置**：`BASE_DIR/.text_inbox.lock`（本地磁盘，挨着它保护的 ledger），**不放** iCloud inbox 目录。flock 在同步路径上不可靠，且锁只需被本机进程看到。已加进 `.gitignore`
- **`--dry-run` 不拿锁**：它不写 ledger、不写笔记、不建锁文件，所以既不需要锁，也不应该有能力挡住排在后面的真实运行（符合「dry-run 绝不写任何状态文件」规则）
- **验证**：新增 `test_text_inbox_lock.py`（自包含脚本，无框架依赖，函数体 monkeypatch，不发网络请求也不碰真 vault）。四条断言全过：并发时第二个进程完全不执行函数体、SIGKILL 掉持锁进程后锁立刻可用、无竞争时正常拿放、dry-run 不被挡。已有 `test_text_inbox_skip.py` 仍通过（函数改名的回归点）

---

## Backlog

- [ ] **流水线 A 也有同样的并发缺陷**：这次的锁只护 text inbox。音频那条（transcribe → refine，共用 `.refined_ledger.json`）两个进程同时跑同样会互相踩，只是这次没触发。修法同 C，把 `_inbox_lock()` 抽成共用工具即可（2026-08-06 Bear 决定先只修 C）

- [ ] Chunk long audio before transcription (support recordings > 30 min)

- [ ] Post-refinement character count validation with auto-retry if content shrinks > 15%

- [ ] iPhone Voice Memo `.m4a` filename pattern support（当前需手动重命名为 `YYYYMMDD-N.m4a` 格式）
