# Voice Daily Note

一条命令，将录音笔的语音备忘录转化为精修的每日 Markdown 笔记，并自动生成适合三个平台发布的社交帖子。

---

## 工作流程

### v1.0 — 每日笔记流水线

```
Recording/*.wav  →  transcripts/*.txt  →  output/YYYY-MM-DD.md  →  Obsidian Daily Notes
   (录音文件)          (Buzz/Whisper)         (Claude API 精修)
```

1. **转写**：用 [Buzz](https://buzzcaptions.com/) 调用本地 Whisper 模型转文字，失败时自动 fallback 到 Python whisper 库
2. **精修**：发送转写文本给 Claude API，修正错别字、补充分段、整理结构。零删减，原始信息全量保留
3. **归档**：精修完成后将音频移入 `archive/YYYY-MM-DD/`

### v1.3 — 社交帖子流水线

```
Daily Notes/*.md  →  01_extracted.md  →  02_social.md  →  Bear Content Vault
  (Obsidian vault)    (#Share 条目)       (三平台版本)       manual/YYYY-MM/
```

1. **提取**：扫描每日笔记，提取打了 `#Share` 标签的条目
2. **生成**：一次 Claude API 调用，同时生成三个平台版本：
   - `---twitter-cn---`：完整中文内容，不限字数
   - `---linkedin-en---`：英文，LinkedIn 调性
   - `---youtube-shorts---`：标题 + hashtags
3. **存档**：每条帖子单独存为 `YYYY-MM-DD-标题.md`，写入 Bear Content Vault

---

## 快速开始

### 配置

```bash
# 在 .env 文件里设置（复制 .env.example）
ANTHROPIC_API_KEY=sk-ant-...
OUTPUT_DIR=/path/to/Obsidian/Daily notes   # 输出到 Obsidian vault
```

### 每日笔记

```bash
# 把音频文件放入 Recording/，然后：
python3 pipeline.py

# 仅预览，不处理
python3 pipeline.py --dry-run

# 夜间批量运行（防止 Mac 休眠，完成后发通知）
./run-overnight.sh
```

| 参数 | 说明 |
|------|------|
| `--dry-run` | 预览模式，不实际处理 |
| `--step transcribe` | 仅转写 |
| `--step refine` | 仅精修 |
| `--force` | 强制重新处理已有文件 |
| `--engine whisper` | 跳过 Buzz，直接用 whisper |
| `--no-archive` | 不归档原始音频 |

### 社交帖子

```bash
# 把要处理的每日笔记放入 sharing_input/，然后：
python3 share_to_social.py

# 仅预览提取结果
python3 share_to_social.py --dry-run

# 指定输入目录
python3 share_to_social.py --input-dir /path/to/notes

# 分步运行
python3 share_to_social.py --step extract    # 仅提取
python3 share_to_social.py --step generate   # 提取 + 生成（不存 vault）
```

---

## 支持的音频格式

| 来源 | 文件名示例 | 提取到的时间 |
|------|-----------|------------|
| 录音笔 | `TX00_MIC031_20260212_175200_orig.wav` | `2026-02-12 17:52:00` |
| iPhone 语音备忘录 | `20260212-1.m4a` | `2026-02-12` |

---

## 每日笔记输出格式

```markdown
---
date: 2026-02-12
type: daily-note
entries: 3
---

## 关于设计系统的思考
**场景**：通勤路上 | **标签**：#Work | **记录时间**：17:52:00
---
精修后的全文内容...
```

## 社交帖子输出格式

```markdown
## 帖子标题

一两句话的核心摘要。

---twitter-cn---
完整中文内容...

---linkedin-en---
English LinkedIn content...

---youtube-shorts---
Title for YouTube Shorts #Hashtag1 #Hashtag2
```

---

## 项目结构

```
voice-daily-note/
├── Recording/              # 放入音频文件
├── transcripts/            # 中间产物：原始转录文本
├── archive/                # 已处理音频的归档
├── sharing_input/          # 放入待提取 #Share 的每日笔记
├── sharing_output/         # 中间产物：提取和生成的中间文件
│   ├── 01_extracted.md
│   └── 02_social.md
│
├── pipeline.py             # 每日笔记主入口
├── transcribe.py           # Step 1: 音频 → 文字
├── refine.py               # Step 2: 文字 → 精修 MD
├── refinement_prompt.py    # LLM 系统提示词
├── share_to_social.py      # 社交帖子流水线
├── share_pipeline.py       # 从每日笔记存到 Content Vault（轻量版）
├── config.py               # 共享配置与路径
├── .env                    # API 密钥（不提交 git）
└── run-overnight.sh        # 后台运行脚本
```

---

## 依赖

- Python 3.9+
- [Buzz.app](https://buzzcaptions.com/)（或 `pip install openai-whisper` 作为 fallback）
- `requests`, `python-dotenv`
- `ANTHROPIC_API_KEY`

---

## 设计原则

- **零删减**：精修只修格式和错别字，不压缩、不总结、不删内容
- **幂等**：重复运行安全，已处理文件自动跳过，除非加 `--force`
- **容错**：Buzz 失败自动切 whisper，API 超时自动重试，单文件失败不影响整批

---

## 版本历史

| 版本 | 内容 |
|------|------|
| v1.0 | 核心流水线：录音 → 转写 → 精修 Markdown，按日期归档 |
| v1.1 | Obsidian 集成：OUTPUT_DIR 路由到 vault，双语输出支持 |
| v1.2 | 分享流水线：#Share 标签提取，存入 Bear Content Vault |
| v1.3 | 社交帖子生成：一次 API 调用生成 Twitter CN + LinkedIn EN + YouTube Shorts |
