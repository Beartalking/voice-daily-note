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

### 流水线 B：#Share 配图随帖同步 (v2.1.1, 2026-07-22)
- **Bug**：配图完全丢失。图片 markdown 混在正文里喂给 Claude，改写时被吃掉；`save_to_content_vault()` 又把 frontmatter 的 `images:` 写死为空
- `ShareEntry` / `SocialPost` 新增 `images` 字段
- 新增 `_extract_images_from_body()`：抠出 `![[...]]` 与本地 `![](...)`，按 Obsidian `attachmentFolderPath`（`./99_Assets`）解析绝对路径，兜底按文件名全库搜；同时把图片 markdown 从正文剥掉，**正文只留纯文字给 Claude 改写**
- 存 vault 时写进 frontmatter `images:` 块。跨 vault 必须用绝对路径，指向日记那侧的 `99_Assets`，发布前别移走或清理那些附件，否则路径断掉
- 下游 content-publisher 的 `_resolve_image` 负责发布时上传 Cloudinary
- 验证：3 条带图条目图片全解析到真实文件（含一条 2 张），正文无残留，跑两次幂等无重复
- *（本条 2026-08-24 补记：功能 2026-07-22 就上线了，SKILL.md 当时同步了，plan.md 漏记）*

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

### 流水线 B：`--skip-title` 排除机制 (v2.4, 2026-08-24)
- **背景**：排除一条不想发的 `#Share` 条目，此前唯一可靠的方式是回日记摘标签。踩了两次（2026-08-13、2026-08-20 的《深夜惊魂记》）后落地
- **为什么原来的两条路都不通**（现状确认，未改）：Step 1 无条件 `write_extracted()` 覆盖 `sharing_output/01_extracted.md`，且位置在 `--dry-run` 分支之前 → 手动编辑 `01_extracted.md` 删条目不起作用；去重维度只有「Content Vault drafts + published 里存在同名标题」→ **删草稿 ≠ 排除**，只要还在回溯窗口内就会被重抽
- **新增 `--skip-title TITLE`**：`action="append"` 可重复。命中即在提取阶段丢弃并打印 `Skipped by --skip-title: <标题>`，不静默
- 匹配走 `_matches_skip()`，复用 `_normalize_title()` 做归一化子串匹配 → 大小写、标点、空格不敏感，**打片段就够**（`深夜惊魂` 命中《深夜惊魂记》）
- 归一化后为空的 pattern 直接忽略。否则 `--skip-title ""` 会匹配所有标题，整批静默清空，排除机制自己变成新的丢内容事故
- **排除优先于 `--force`**：`--force` 只关去重，显式排除是更强的信号，两者叠加时排除仍生效
- **没有选「Step 1 在 `01_extracted.md` 已存在时跳过重写」那条路**：那会把一个中间产物变成隐式状态文件，和「dry-run 绝不写状态文件」的既定规矩气质冲突，也留下一个删了就复活的坑
- **验证**：新增 `test_share_skip_title.py`（自包含脚本，无框架依赖，fixture 日记在临时目录，monkeypatch 掉 `_collect_processed_titles`，不发网络请求也不碰真 vault）。五条断言全过：命中即排除且其余条目不受影响、片段匹配、大小写/标点不敏感、`--force` 下仍生效、不传参数时行为不变。真 vault 上 `--dry-run --days 14` 复现了《深夜惊魂记》被重抽，加 `--skip-title 深夜惊魂` 后消失；`test_text_inbox_skip.py` / `test_text_inbox_lock.py` 无回归

---

## Backlog

- [ ] **流水线 A 也有同样的并发缺陷**：这次的锁只护 text inbox。音频那条（transcribe → refine，共用 `.refined_ledger.json`）两个进程同时跑同样会互相踩，只是这次没触发。修法同 C，把 `_inbox_lock()` 抽成共用工具即可（2026-08-06 Bear 决定先只修 C）

- [ ] Chunk long audio before transcription (support recordings > 30 min)

- [ ] Post-refinement character count validation with auto-retry if content shrinks > 15%

- [ ] iPhone Voice Memo `.m4a` filename pattern support（当前需手动重命名为 `YYYYMMDD-N.m4a` 格式）

- [ ] **清死代码**（2026-08-24 开工检查发现）：`share_pipeline.py`（v1.2 的轻量版）和 `share_to_linkedin.py` 早在 v1.3 就被 `share_to_social.py` 取代，两个文件仍留在仓里；`README.md:147` 还把 `share_pipeline.py` 列为「从每日笔记存到 Content Vault（轻量版）」，会误导下一个来读的人（包括未来的 Claude）

- [ ] **两个 launchd 启动脚本没纳管**（2026-08-24 开工检查发现）：`run_text_inbox.sh`、`run_bookshelf_sync.sh` 一直是 untracked，也不在 `.gitignore` 里。换机器或重装就丢，而流水线 C / D 的定时运行全靠它们
