# AgentGuard · 已做进展

> 倒序记录，每条含日期。实现阶段请顺手记录**用 AI 辅助编码的关键决策与审查点**（答辩要考）。

## Day 0 · 2026-07-12
- 读题、确定业务场景与验收标准。
- 技术选型定稿（详见 [HANDOFF](HANDOFF.md) 六条决策）：
  - 记忆 = 精简 Postgres + 图-lite（不用完整图记忆）
  - 语音 = 自建链式 STT→LLM(OpenRouter)→TTS（不用 S2S）
  - 电话 = Twilio 优先
  - 微信 = 企业微信群机器人 Webhook
  - Serverless = 混合架构；单 Agent
- 建立仓库 `~/Documents/Git/AgentGuard`（git init，main 分支，.gitignore）。
- 建立 harness 文档全套：README / PROJECT_PLAN / HANDOFF / TODO / PROGRESS / TOKEN_ACCOUNTING / CLAUDE.md。
- 产出 Mermaid 架构图 `docs/diagrams/architecture.mmd`。
- 核实关键事实（避免过时/不合规方案）：OpenRouter 无 realtime S2S、Twilio 对华限制、企业微信 webhook 能力与限额、2026 agent memory 现状。
