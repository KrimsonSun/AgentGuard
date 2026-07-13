# AgentGuard · 语音门卫访客登记 Voice Agent

驾驶员拨打园区张贴的号码 → AI 门卫自然对话采集访客信息 → 结构化推送至保安企业微信 → 确认放行。
目标：从接通到微信送达 **< 25 秒**，对话**像真人门卫一样自然**（3 轮≈15 秒，非机械问答）。

## 架构

```mermaid
flowchart LR
    U["📞 访客"] -->|"WebRTC链接(demo) · SIP/PSTN(生产) · 企微语音(通道2)"| LK["LiveKit<br/>媒体"]
    LK --> STT["流式STT<br/>中文"] --> BRAIN["LLM大脑<br/>OpenRouter"] --> TTS["流式TTS<br/>中文"] --> LK
    BRAIN <-->|回访/统计| DB[("Neon PG<br/>visits·profiles·ledger")]
    BRAIN -->|notify_guard| WX["企业微信<br/>群机器人"]
    BRAIN -.->|读/写 token 记账| DB
```

> 完整架构图见 [`docs/diagrams/architecture.mmd`](docs/diagrams/architecture.mmd)。选型理由与 trade-off 见 [`docs/HANDOFF.md`](docs/HANDOFF.md)。

**一句话选型**：自建**链式** pipeline（STT→LLM→TTS）而非端到端语音——为了把 LLM 大脑收敛到 **OpenRouter**（统一计费、读/写 token 可精确对账）并对 slot 填充逻辑保留完全控制；记忆用**精简 Postgres**（结构化访问事件 + 精确聚合）而非图数据库，图-lite 层仅作能力展示。详见 HANDOFF。

## 部署步骤（本地）

```bash
# 1. 依赖（Python 3.11+）
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 配置环境变量（⚠️ 注释独立成行，勿写行内注释）
cp .env.example .env

# 3. 初始化数据库 (Neon)
psql "$DATABASE_URL" -f db/schema.sql

# 4. Admin Console：选择/切换 LLM 模型（运行时生效，下一通电话即用）
uvicorn admin.server:app --port 8100      # → http://localhost:8100

# 5. 启动门卫 Agent worker（常驻，等待派单；接通即固定开场白秒回）
python -m app.agent dev

# 6. 呼入 demo：打开 WebRTC 通话链接即可对话（SIP/PSTN 生产接入见 docs/HANDOFF.md §决策3）
```

> `requirements.txt` / `db/schema.sql` / `app/` 将在实现阶段落地，详见 [`docs/TODO.md`](docs/TODO.md)。

## 环境变量

见 [`.env.example`](.env.example)。核心：`OPENROUTER_API_KEY`、`TWILIO_*`、`LIVEKIT_*`、`STT_*`/`TTS_*`、`DATABASE_URL`、`WECOM_WEBHOOK_URL`。

## 项目文档（harness）

| 文档 | 用途 |
|---|---|
| [PROJECT_PLAN](docs/PROJECT_PLAN.md) | 整体规划 · 架构分层 · 7 天时间线 · 风险登记 |
| [HANDOFF](docs/HANDOFF.md) | 关键决策与 trade-off · 未决项 · **答辩要点** |
| [TODO](docs/TODO.md) | 待做清单（MVP / 加分，按优先级） |
| [PROGRESS](docs/PROGRESS.md) | 已做（按日志记录） |
| [TOKEN_ACCOUNTING](docs/TOKEN_ACCOUNTING.md) | 读/写 token 与成本对账设计 |
