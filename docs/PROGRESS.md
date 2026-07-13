# AgentGuard · 已做进展

> 倒序记录，每条含日期。实现阶段请顺手记录**用 AI 辅助编码的关键决策与审查点**（答辩要考）。

## Day 1 · 2026-07-13
- **Admin Console 上线**（`admin/`）：FastAPI + 单页前端，OpenRouter 341 个模型列表
  （过滤 -1 价伪模型）/搜索/按价排序/一键切换；密钥只在服务端。冒烟测试三端点全通。
- **运行时配置**：`app_config` 表 + `runtime_config.py`；每通电话读一次（不在接听路径），
  通话内固定，下通即生效——由用户质疑"15s TTL 能秒接吗"推动砍掉 TTL，设计更简。
- **秒接路径**：开场白改 `session.say(GREETING)` 固定文案直走 TTS，LLM 移出接听路径。
- OpenRouter key 验证有效（345 模型可用）；venv 升 Python 3.13。
- **坑**：`.env.example` 行内注释被当值读 → 已修（注释独立成行），user 的 .env 同步清理；
  实际只有 OPENROUTER_API_KEY 有值，其余待填（DATABASE_URL/LIVEKIT/WECOM）。

## Day 0+ · 2026-07-13 凌晨
- GitHub 公开仓库建立并推送：https://github.com/KrimsonSun/AgentGuard
- **决策3 修订 v2**（呼入通道）：Twilio 注册摩擦 + 微信无实时通话 API（查证）→ 可插拔呼入边缘：
  demo 主线 WebRTC 网页通话 / 企微语音消息第二通道（QClaw/OpenClaw 方向）/ SIP·PSTN 生产路径。
  已同步 PLAN/TODO/README/架构图。待办：向对接人确认口径。
- 评估并否决 WhatsApp Calling API（场景不符/大陆不可用/门槛高，见 HANDOFF §决策3）。
- **代码骨架落地**（无密钥可写部分）：`db/schema.sql`（三表+对账视图+pgvector）、
  `app/`（config/slots/prompts/memory/ledger/wecom/agent 单Agent骨架，STT/TTS 留 [Day1] 接线点）、
  `channels/wechat_voice/` 与 `workers/` 设计稿、requirements.txt。
- Figma 权限验证通过（Yijun Sun's team），架构图待推送。
- AI辅助编码记录：骨架由 Claude 生成；人工审查点=车牌/手机号正则、upsert 画像的并发语义、
  ledger 以 provider 回传为准原则、livekit-agents 版本敏感处已标注 [Day1] 待校准。

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
