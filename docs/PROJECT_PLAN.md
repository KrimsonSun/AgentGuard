# AgentGuard · 项目整体规划

> 语音门卫访客登记 Voice Agent。本文件是长期规划主文档；决策与 trade-off 见 [HANDOFF](HANDOFF.md)，
> 待做见 [TODO](TODO.md)，进展见 [PROGRESS](PROGRESS.md)。

## 1. 目标与验收

| 项 | 标准 | 来源 |
|---|---|---|
| 全链路跑通 | 拨号 → Agent 接听 → 自然对话采集 → 推送保安企业微信 | 必须 |
| 时延 | 接通（Agent 开口）到微信发出 **< 25s**（不含振铃） | 必须 |
| 对话自然度 | 像真人门卫，3 轮≈15s；非机械一问一答 | 必须 |
| 可演示部署 | 至少本地可运行 | 必须 |
| 交付 | GitHub 仓库 + 一页 README + 1–2min demo 视频 + 中英双语选型报告(doc+pdf) | 必须 |
| 实战测试 | 亲朋实拨、收集反馈迭代 | 必须 |
| 回访识别 | 按车牌/手机号关联历史，直接确认而非重采 | 加分 |
| 门卫查询 Agent | NL 查询统计（本周多少车 / 某人本月几次 / 峰值时段） | 加分 |
| Serverless / 多路并发 | 云原生部署；多车同时拨打 | 加分 |

**需采集字段**：车牌号、来访单位、手机号、来访事由、入场时间（系统自动）。

## 2. 采集信息的五个字段

| 字段 | 说明 | 示例 |
|---|---|---|
| 车牌号 | 访客车辆牌照 | 沪A12345 |
| 来访单位 | 园区内目标公司 | 蓝色鲸鱼科技 |
| 手机号 | 访客联系电话 | 138xxxx1234 |
| 来访事由 | 送货 / 拜访 / 面试… | 送货 |
| 入场时间 | 系统自动记录 | 2026-07-12 14:30 |

## 3. 架构分层（决策已锁定）

```
访客 ──WebRTC链接(demo) / 企微语音消息(通道2) / SIP·PSTN(生产)──▶ LiveKit 媒体
                                          │
                        ┌─────────────────┴─────────────────┐
                        │  门卫 Agent Worker（单 Agent）      │
                        │  流式STT → LLM大脑(OpenRouter) → 流式TTS  │
                        │  + turn detection / barge-in       │
                        └───────┬───────────────────┬────────┘
                     工具调用    │                   │  notify_guard
              ┌──────────────────┴──────┐            ▼
              │ Neon Postgres（事实源）  │      企业微信群机器人 Webhook → 保安
              │ visits/profiles/ledger  │
              │ + 图-lite(pgvector/AGE) │
              └─────────────────────────┘
   Serverless 层：OpenRouter(LLM) · Neon(DB) · 企业微信 webhook · CF Workers(门卫查询) · GH Actions(CI/CD)
```

- **语音链路**：自建**链式** STT→LLM→TTS（非端到端 S2S）。理由见 HANDOFF §决策2。
- **LLM 大脑**：单 agent，经 **OpenRouter**；工具 `lookup_returning_visitor / save_visit / notify_guard / query_stats`。
- **记忆**：精简 Postgres 为唯一事实源；图-lite 层仅作能力展示。理由见 HANDOFF §决策1。
- **呼入**：可插拔边缘——demo 主线 WebRTC 网页通话；企微语音消息第二通道；SIP/PSTN 为生产路径。见 HANDOFF §决策3(v2)。
- **微信**：企业微信群机器人 Webhook（MVP 单向）；双向放行为可选升级。
- **Serverless**：混合架构——媒体环路常驻，其余上 Serverless。

> 完整框图：[`diagrams/architecture.mmd`](diagrams/architecture.mmd)。Figma 版本待授权后同步到 Yijun Sun team draft。

## 4. 7 天时间线

> Day 0 = 2026-07-12（**请确认题目实际收到日**以校准 Day 7 截止）。

| Day | 目标 | 关键产出 |
|---|---|---|
| **0** | 立项 · 选型定稿 · 仓库 + harness · 架构图 | 本套文档 ✅ |
| **1** | 🔴 呼入+媒体打通 | LiveKit WebRTC 网页呼入跑通（Agent 说第一句）；STT/TTS 双方向实测定稿；向对接人发口径确认；（可选15min）试注册 Twilio |
| **2** | 单 agent 对话核心 | slot 填充 5 字段 + 自然对话 prompt + OpenRouter 接入 + 延迟调优；PG schema + save_visit |
| **3** | 记忆闭环 + 全链路 | visitor_profiles + 回访识别；企业微信 webhook 推送；跑通全链路 + 25s 计时 |
| **4** | 对账 + 加分项 | usage_ledger 读/写 token 台账 + per-call 成本报告；图-lite 层；门卫查询 query_stats(NL→SQL) |
| **5** | 打磨 + 实测 | 对话达"3 轮 15s"标准；亲朋实拨收集反馈迭代；并发/异常处理 |
| **6** | 文档与交付 | README/架构 Figma/中英双语 doc+pdf 报告；Serverless 加分(CF Workers/GH Actions) |
| **7** | Demo + 提交 | 录 1–2min demo 视频；最终测试；提交；答辩准备 |

## 5. 风险登记

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | 呼入口径：WebRTC/微信非字面"拨打号码" | 🔴 交付合规 | 第一时间向对接人确认；架构可插拔，SIP 随时可插回 |
| R2 | 中文 STT/TTS 延迟与自然度 | 25s + "像人"标准 | 多 provider 对比测；流式优先 |
| R3 | 链式 pipeline 延迟天然高于 S2S | 25s 预算 | 流式 STT/TTS + 快模型 + turn detection；分段并行 |
| R4 | 个人微信推送不合规/不稳 | 交付可靠性 | 已选企业微信 webhook 规避 |
| R5 | 实时媒体不能纯 serverless | 加分项误区 | 混合架构：媒体常驻 + 其余 serverless |
| R6 | 题目截止日未校准 | 交付节奏 | 向对接人确认收到日 |

## 6. 非目标（本期不做）

- 完整图数据库记忆（Neo4j/Graphiti）——见 HANDOFF §决策1 trade-off。
- 保安端 App / 复杂后台管理界面。
- 海康门禁真实对接（仅模拟"未登记"触发点）。
