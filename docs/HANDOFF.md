# AgentGuard · HANDOFF（决策 · trade-off · 答辩要点）

> 跨会话 / 交接 / 答辩的上下文承载文档。**每做一个关键技术决策就在此追加一条 ADR**，
> 写清「选了什么 / 为什么 / 放弃了什么 / 代价」。这是 30 分钟技术答辩的弹药库。

## 当前状态（截至 Day 0 · 2026-07-12）

- ✅ 选型定稿、仓库建立（`~/Documents/Git/AgentGuard`）、harness 文档全套、Mermaid 架构图。
- ⏳ 未开工：电话/媒体 spike、对话核心、记忆、微信推送、对账、报告。
- 🔓 未决：STT/TTS 具体 provider、OpenRouter 模型、题目实际收到日、Figma 授权。

---

## 决策 1 — 记忆：精简 Postgres + 图-lite，**不用**完整图记忆

**选择**：Neon Postgres 作唯一事实源（`visits` / `visitor_profiles` / `usage_ledger`），
在 Postgres 内加一层 **图-lite**（pgvector 语义索引 / 可选 Apache AGE 实体-关系）作能力展示；
**不引入** Neo4j + Graphiti/Zep 这类独立时序知识图谱。

**两层记忆边界**：
- **长期记忆 = Postgres**（事实源，精确、可聚合、可对账）。
- **工作记忆 = 单次通话内的有界状态**（slot 填充进度 +（若回访）一段注入的压缩摘要），活在进程里、不进 DB。
- LLM 的 context 永远只有：静态系统提示（可 prompt cache）+ 当前 slots +（可选）回访摘要 + 最新一句。→ context 极小 = 又便宜又快，边界清晰。

**为什么不用完整图记忆（trade-off，答辩要点）**：
1. **数据形态相反**。图记忆（Graphiti/Zep）为**非结构化、随时间变化、需消解矛盾、需模糊语义召回**的长对话而生（如"用户经理从 A 变成 B"）。本场景是 **schema 固定的结构化访客事件**，字段就 5 个。
2. **不可变历史事件**。一次访问是历史记录，不会"被推翻/失效"——Graphiti 的核心卖点（`valid_at`/`invalid_at` 时序有效期、矛盾消解）在这里没有用武之地。
3. **聚合要精确，图/向量给近似**。"本周多少车 / 某人本月几次 / 峰值时段"是**精确聚合**，SQL 一句给确定答案；图遍历或向量召回只能给近似结果，对这类问题是**降级**。
4. **成本与延迟**。独立图库 = 多一套基础设施 + 图遍历 50–150ms（对比向量 10–50ms、索引点查更快），与本项目"又轻又高效"的目标背离。
5. **2026 行业风向也在"回归 SQL"**（Memori、Letta on Postgres），普遍认为独立图库对多数结构化场景是过度设计。

**图-lite 保留的意义**：用 pgvector 对自由文本（来访事由 / 公司别名）做模糊匹配、"相似访问"检索，既覆盖少数模糊召回需求，又能在答辩中展示 KG/向量能力——但明确定位为**加分展示，非核心**。核心正确性不依赖它。

**何时才该上完整图记忆**（答辩加分：说清边界）：若未来 agent 要跨多类实体追踪**会演化、需消解矛盾的非结构化事实**（如同一司机身份在多公司/多角色间变化、需要多跳关系推理），那时图记忆才划算。

---

## 决策 2 — 语音链路：自建**链式** STT→LLM(OpenRouter)→TTS，**不用**端到端 S2S

**选择**：LiveKit Agents（或 Pipecat）编排流式 STT → LLM(经 OpenRouter) → 流式 TTS，配 turn detection / barge-in。

**为什么不用端到端 Speech-to-Speech**（OpenAI Realtime / Gemini Live）：
1. **OpenRouter 目前没有 realtime 语音对语音**（只有文本 chat + 分离的 STT/TTS 端点，且转写是文件式）。要把大脑收敛到 OpenRouter，就得走链式。
2. **token 对账**：链式每轮是离散的文本 LLM 调用，读/写 token 精确可查（对账是本项目硬指标）；S2S 的音频 token 计费更糊。
3. **控制力**：slot 填充、工具调用、回访注入都在文本层，逻辑可控可测。

**代价**：链式端到端延迟天然高于 S2S。**缓解**：流式 STT + 快模型 + 流式 TTS + 良好 turn detection，把"接通→采集→推送"压进 25s，对话做到 3 轮≈15s。若延迟/自然度实测不达标，S2S 作为答辩中讨论的备选。

**框架**：默认 **LiveKit Agents**（SIP/telephony 成熟、有 turn-detector 模型、与 Twilio SIP 集成好）；Pipecat 为备选。

---

## 决策 3 — 电话：Twilio 优先

**选择**：Twilio 号码 → SIP → LiveKit ingress。

**核实到的事实（勿凭记忆）**：
- Twilio 自 2023-11 起**不支持向中国大陆外呼**；中国大陆手机拨打 Twilio 海外号码质量不稳。
- 题目明确电话方案"本身就是考察的一部分"，要求记录困难、答辩讨论。

**取舍**：用户在国内，Twilio 为已知量、最快拿到可跑 demo 的一通电话；接受它**非国内本地号**（答辩讲清）。**Day1 spike 优先消除此最高风险**。
**fallback**：国内 SIP trunk / 阿里云语音（需实名/企业资质，保真度高但周期长）；或 SaaS 自带号码。

---

## 决策 4 — 微信推送：企业微信群机器人 Webhook

**选择**：企业微信群机器人 Webhook（HTTP POST JSON，支持 text/markdown/模板卡片，限 20 条/分钟，webhook 需保密）。用户单开一个企业微信承载。

**为什么不用个人微信**：个人微信机器人（itchat/wechaty 类）违反 ToS、易封、不稳。企业微信是合规可靠路径。

**可选升级**：保安"点按钮放行"的双向交互需**企业微信自建应用 + 回调 URL**，列为有时间再做（用户："有时间可以做微信工作流"）。

---

## 决策 5 — Serverless：混合架构

实时语音是长连接、有状态的媒体环路，**不适合无状态 Serverless**。媒体 worker 跑常驻主机（LiveKit Cloud / 便宜 VM）；OpenRouter(LLM)、Neon(DB)、企业微信 webhook、CF Workers(门卫查询)、GH Actions(CI/CD) 才是 Serverless 层。把这个"混合"讲清楚本身就是答辩素材。

---

## 决策 6 — 单 Agent，不做 multi-agent 编排

一个门卫大脑 + 工具（`lookup_returning_visitor / save_visit / notify_guard / query_stats`）。
加分项"门卫查询 Agent"是**同一单 agent 模式换入口 + 一个查询工具**，不是 agent 集群。
理由：轻量、上下文边界清晰、延迟可控、token 可对账。

---

## 未决项 / 待确认

- [ ] 题目实际收到日（校准 Day 7 截止）——问对接人。
- [ ] Figma MCP 授权（claude.ai connector 或交互式 `/mcp`），以便把架构图同步到 Yijun Sun team draft。
- [ ] STT/TTS 中文 provider 定稿（Day1-2 spike 对比延迟/自然度）。
- [ ] OpenRouter 模型定稿（快 + 中文强 + 便宜）。

## 答辩速览（30 分钟）

- 为什么链式而非 S2S / 为什么精简 Postgres 而非图记忆 / 为什么 Twilio（及其中国取舍）——见上。
- 如何用 AI 辅助编码、如何审查生成代码——实现阶段随手记进 PROGRESS。
- 遇到的困难与尝试（尤其电话接入）——如实记录，比硬凑半成品更有价值。
