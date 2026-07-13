# CLAUDE.md — AgentGuard 编码代理工作指南

语音门卫访客登记 Voice Agent。开工前先读 [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) 与 [docs/HANDOFF.md](docs/HANDOFF.md)。

## 核心原则（不可违背）

1. **单 Agent，不做 multi-agent 编排**。一个门卫大脑 + 工具调用。"门卫查询"是同一模式换入口，不是 agent 集群。
2. **上下文最小化 + 边界清晰**。DB（Postgres）是唯一事实源；LLM 的 context 只放：静态系统提示（尽量 prompt cache）+ 当前 slot 状态 +（若回访）注入的压缩摘要 + 最新一句。**绝不把历史/整库灌进 context。**
3. **记忆用精简 Postgres，不引入图数据库**。图-lite（pgvector/AGE）仅作加分展示，核心正确性不依赖它。理由见 HANDOFF §决策1。
4. **每次 LLM/STT/TTS 调用后立即写 `usage_ledger`**（读/写 token 分列）。见 [docs/TOKEN_ACCOUNTING.md](docs/TOKEN_ACCOUNTING.md)。禁止事后估算。
5. **轻量高效优先**。能一条 SQL 解决的不上向量/图；能不加依赖就不加。

## 技术栈约定

- 语音 Agent worker：**Python**（LiveKit Agents）。LLM 经 **OpenRouter**。
- STT/TTS：中文、流式；provider 在 Day1-2 spike 定（见 .env.example）。
- DB：**Neon Postgres**；schema 放 `db/schema.sql`。
- 门卫查询 API / Serverless：**TypeScript**（Cloudflare Workers）。
- 秘钥只经 `.env`（已 gitignore）；`.env.example` 保持同步。

## 目录约定（实现时逐步落地）

```
app/            # 门卫 Agent（Python）：agent 主逻辑、tools、prompt、slot 状态机
db/             # schema.sql、迁移
workers/        # CF Workers：门卫查询 API（TS）
docs/           # 规划/决策/对账/图（本套 harness）
```

## 文档维护纪律

- 完成一项 → 勾掉 [TODO](docs/TODO.md)，追加 [PROGRESS](docs/PROGRESS.md)（含 AI 辅助编码的关键决策/审查点，答辩要考）。
- 做出技术决策 → 追加 [HANDOFF](docs/HANDOFF.md) 一条 ADR（选了什么/为什么/放弃什么/代价）。
- 遇到坑（尤其电话接入）→ 如实记 HANDOFF，答辩讲"尝试了什么、卡在哪"。

## 硬约束回顾（验收）

接通(Agent 开口)→微信发出 **< 25s**；对话像真人门卫（3 轮≈15s，非机械问答）；全链路本地可跑；README 一页。
