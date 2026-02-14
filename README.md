# Voice Daily Note

One command to turn voice memos into polished daily Markdown notes — and share them on LinkedIn.

一条命令，将语音备忘录转化为精修的每日 Markdown 笔记，并一键生成 LinkedIn 双语帖子。

---

## How It Works / 工作原理

### v1.0 — Daily Note Pipeline / 每日笔记流水线

```
Recording/*.wav  →  transcripts/*.txt  →  output/YYYY-MM-DD.md
   (audio)          (Buzz/Whisper)         (Claude API refinement)
```

1. **Transcribe** — Converts audio to text using [Buzz](https://buzzcaptions.com/) (primary) or OpenAI Whisper (fallback)
2. **Refine** — Sends transcripts to Claude API for editing: fix typos, add paragraphs, add structure. Zero content deletion.
3. **Archive** — Moves processed audio to `archive/YYYY-MM-DD/`

### v1.1 — Share-to-LinkedIn Pipeline / LinkedIn 分享流水线

```
sharing_input/*.md  →  01_extracted.md  →  02_twitter.md   →  03_linkedin.md
  (daily notes)        (#Share entries)    (推特可发中文)      (LinkedIn 中英双语)
```

1. **Extract** — Scans daily notes for `#Share` tagged entries, strips metadata
2. **Twitter** — Polishes into Twitter-ready Chinese posts via Claude API
3. **LinkedIn** — Filters by professional relevance, translates to bilingual (中/EN) posts

---

## Quick Start / 快速开始

### Setup / 配置

```bash
# Set your API key (one-time)
# 设置 API 密钥（一次性）
echo "export ANTHROPIC_API_KEY='sk-ant-...'" >> ~/.zshrc
source ~/.zshrc
```

### Usage / 使用

```bash
# Drop audio files into Recording/, then:
# 将音频文件放入 Recording/，然后：

cd voice-daily-note

# Full pipeline / 完整流水线
python3 pipeline.py

# Preview only / 仅预览
python3 pipeline.py --dry-run

# Run overnight (prevents Mac sleep, sends notification when done)
# 夜间运行（阻止 Mac 休眠，完成后发送通知）
./run-overnight.sh
```

### Share to LinkedIn / 分享到 LinkedIn

```bash
# Copy daily notes with #Share entries into sharing_input/
# 将含有 #Share 标签的日记复制到 sharing_input/
cp output/2026-02-11.md sharing_input/

# Full pipeline (extract → refine → LinkedIn bilingual posts)
# 完整流水线（提取 → 润色 → LinkedIn 中英双语帖子）
python3 share_to_linkedin.py

# Preview extracted entries without calling API
# 预览提取结果，不调用 API
python3 share_to_linkedin.py --dry-run

# Run individual steps / 运行单个步骤
python3 share_to_linkedin.py --step extract     # Extract only / 仅提取
python3 share_to_linkedin.py --step twitter     # Extract + Twitter / 提取+推特润色

# Custom input directory / 自定义输入目录
python3 share_to_linkedin.py --input-dir ./output
```

### All Options — pipeline.py / 所有选项

| Flag | Description / 说明 |
|------|-------------------|
| `--dry-run` | Preview without processing / 预览模式，不实际处理 |
| `--step transcribe` | Transcribe only / 仅转录 |
| `--step refine` | Refine only / 仅精修 |
| `--force` | Re-process all files / 强制重新处理所有文件 |
| `--engine whisper` | Use whisper instead of Buzz / 使用 whisper 代替 Buzz |
| `--no-archive` | Keep originals in Recording/ / 不归档原始音频 |

### All Options — share_to_linkedin.py / 所有选项

| Flag | Description / 说明 |
|------|-------------------|
| `--dry-run` | Preview extracted entries, skip API / 预览提取结果，不调 API |
| `--step extract` | Extract #Share entries only / 仅提取 |
| `--step twitter` | Extract + Twitter polish / 提取+推特润色 |
| `--step linkedin` | All 3 steps (default) / 全部三步（默认） |
| `--input-dir PATH` | Custom input directory / 自定义输入目录 |

---

## Supported Filename Formats / 支持的文件名格式

| Source / 来源 | Example / 示例 | Date Extracted / 提取日期 |
|--------------|---------------|------------------------|
| Recorder / 录音笔 | `TX00_MIC031_20260212_175200_orig.wav` | `2026-02-12 17:52:00` |
| Voice Memo / 语音备忘录 | `20260212-1.wav` | `2026-02-12` |

---

## Output Format / 输出格式

Each day produces one Markdown file with YAML front matter:

每天生成一个带 YAML 头信息的 Markdown 文件：

```markdown
---
date: 2026-02-12
type: daily-note
entries: 3
---

## 关于设计系统的思考
**场景**：通勤路上 | **标签**：#Work | **记录时间**：17:52:00
---
[精修后的全文内容...]
```

---

## Project Structure / 项目结构

```
voice-daily-note/
├── Recording/              # Input: drop audio files here / 输入：放入音频文件
├── transcripts/            # Intermediate: raw transcriptions / 中间产物：原始转录
├── output/                 # Output: refined daily notes / 输出：精修后的每日笔记
├── archive/                # Archive: processed audio / 归档：已处理的音频
│
├── sharing_input/          # Input: daily notes for LinkedIn / LinkedIn 输入
├── sharing_output/         # Output: LinkedIn bilingual posts / LinkedIn 输出
│   ├── 01_extracted.md     #   Raw #Share entries / 提取的 #Share 条目
│   ├── 02_twitter.md       #   Twitter-ready Chinese / 推特可发中文版
│   └── 03_linkedin.md      #   Final bilingual posts / 最终中英双语帖子
│
├── pipeline.py             # v1.0 main entry / 主入口
├── transcribe.py           # v1.0 Step 1: audio → text / 音频转文字
├── refine.py               # v1.0 Step 2: text → polished MD / 文字转精修 MD
├── refinement_prompt.py    # v1.0 LLM system prompt / LLM 系统提示词
├── share_to_linkedin.py    # v1.1 Share-to-LinkedIn pipeline / LinkedIn 分享流水线
├── config.py               # Shared configuration / 共享配置
├── .env                    # API keys (gitignored) / API 密钥（不提交）
├── run-overnight.sh        # Background runner / 后台运行脚本
└── plan.md                 # Project roadmap / 项目路线图
```

---

## Requirements / 依赖

- Python 3.9+
- [Buzz.app](https://buzzcaptions.com/) (or `pip install openai-whisper` as fallback)
- `requests`, `python-dotenv` Python packages
- `ANTHROPIC_API_KEY` in `.env` or environment variable

---

## Design Principles / 设计原则

- **Zero deletion / 零删减**：Refinement never summarizes or removes content. Only fixes typos, grammar, and formatting.
- **Idempotent / 幂等**：Safe to re-run. Already-processed files are skipped unless `--force` is used.
- **Fault tolerant / 容错**：Buzz fails → whisper fallback. API errors → exponential retry. Single file failure → continue with the rest.

---

## Version History / 版本历史

| Version | Description |
|---------|-------------|
| **v1.0** | Daily note pipeline: audio → transcript → polished Markdown, grouped by date |
| **v1.1** | Share-to-LinkedIn pipeline: extract #Share entries → refine → bilingual LinkedIn posts |
