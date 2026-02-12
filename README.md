# Voice Daily Note

One command to turn voice memos into polished daily Markdown notes.

一条命令，将语音备忘录转化为精修的每日 Markdown 笔记。

---

## How It Works / 工作原理

```
Recording/*.wav  →  transcripts/*.txt  →  output/YYYY-MM-DD.md
   (audio)          (Buzz/whisper)         (Claude API refinement)
```

1. **Transcribe** — Converts audio to text using [Buzz](https://buzzcaptions.com/) (primary) or OpenAI Whisper (fallback)
2. **Refine** — Sends transcripts to Claude API for editing: fix typos, add paragraphs, add structure. Zero content deletion.
3. **Archive** — Moves processed audio to `archive/YYYY-MM-DD/`

1. **转录** — 使用 Buzz（主引擎）或 OpenAI Whisper（备选）将音频转为文字
2. **精修** — 调用 Claude API 编辑：修正错别字、分段、添加结构。零删减原则。
3. **归档** — 将已处理的音频移至 `archive/YYYY-MM-DD/`

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

### All Options / 所有选项

| Flag | Description / 说明 |
|------|-------------------|
| `--dry-run` | Preview without processing / 预览模式，不实际处理 |
| `--step transcribe` | Transcribe only / 仅转录 |
| `--step refine` | Refine only / 仅精修 |
| `--force` | Re-process all files / 强制重新处理所有文件 |
| `--engine whisper` | Use whisper instead of Buzz / 使用 whisper 代替 Buzz |
| `--no-archive` | Keep originals in Recording/ / 不归档原始音频 |

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
├── Recording/           # Input: drop audio files here / 输入：放入音频文件
├── transcripts/         # Intermediate: raw transcriptions / 中间产物：原始转录
├── output/              # Output: refined daily notes / 输出：精修后的每日笔记
├── archive/             # Archive: processed audio / 归档：已处理的音频
│
├── pipeline.py          # Main entry point / 主入口
├── transcribe.py        # Step 1: audio → text / 音频转文字
├── refine.py            # Step 2: text → polished MD / 文字转精修 MD
├── config.py            # Configuration & CLI / 配置与命令行参数
├── refinement_prompt.py # LLM system prompt / LLM 系统提示词
├── run-overnight.sh     # Background runner / 后台运行脚本
└── plan.md              # Project roadmap / 项目路线图
```

---

## Requirements / 依赖

- Python 3.9+
- [Buzz.app](https://buzzcaptions.com/) (or `pip install openai-whisper` as fallback)
- `requests` Python package
- `ANTHROPIC_API_KEY` environment variable

---

## Design Principles / 设计原则

- **Zero deletion / 零删减**：Refinement never summarizes or removes content. Only fixes typos, grammar, and formatting.
- **Idempotent / 幂等**：Safe to re-run. Already-processed files are skipped unless `--force` is used.
- **Fault tolerant / 容错**：Buzz fails → whisper fallback. API errors → exponential retry. Single file failure → continue with the rest.
- **No new dependencies / 无新依赖**：Built entirely on tools already installed on the machine.
