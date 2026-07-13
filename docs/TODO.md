# AgentGuard · 待做清单

> 优先级：🔴 阻断风险 / 🟢 MVP 必须 / 🔵 加分项 / ⚪ 打磨。完成后移入 [PROGRESS](PROGRESS.md)。

## 🔴 Day 1 — 先消除最大风险（呼入 + 媒体）
- [ ] 向对接人发呼入口径确认（WebRTC 网页通话 / 企微语音消息 是否可作 demo）
- [ ] LiveKit Cloud 拉起；WebRTC 网页呼入跑通：打开链接 → Agent 播报第一句（语音回环）
- [ ] 中文流式 STT/TTS 双方向实测对比（国内 火山/阿里/腾讯 vs 国际 Deepgram/Cartesia），出延迟数据定稿
- [ ] （可选，15min 封顶）试 Twilio 试用注册；成则记 SIP 接入为 Day5 任务，败则记录摩擦点（答辩素材）
- [ ] 记录接入过程中的坑（答辩用）→ HANDOFF / PROGRESS

## 🟢 MVP 必须
### 对话核心（单 Agent）
- [x] 系统提示：真人门卫口吻、一次问多字段、简洁自然（对齐"3 轮 15s"正例）— 离线验证通过
- [x] slot 填充状态机：车牌/单位/手机号/事由（入场时间自动）— slots.py + 校验
- [x] LLM 大脑经 OpenRouter 接入（function calling）— 4 模型实测，选定 gemini-2.5-flash-lite
- [ ] Day2 难例回归：模糊车牌 / 纠错("不是A是B") / 一句话全给 / 听不清重问
- [ ] 开 prompt cache 降读 token；成本列接 usage.include
- [ ] turn detection / barge-in，压端到端延迟 < 25s
- [ ] 工具：`save_visit()` `notify_guard()`

### 记忆 / 数据
- [ ] Neon 建库 + `db/schema.sql`：`visits` / `visitor_profiles` / `usage_ledger`
- [ ] `save_visit()` 落库 + 更新 `visitor_profiles`

### 微信推送
- [ ] 企业微信群机器人 Webhook，`notify_guard()` 推送结构化卡片（含 5 字段 + 时间）
- [ ] 25s 计时埋点（Agent 开口 → 微信发出）

### 交付
- [ ] README 一页（架构图 + 部署 + 环境变量）✅ 骨架已建，补实
- [ ] `requirements.txt` / 运行脚本
- [ ] 亲朋实拨测试，收集反馈 → 迭代

## 🔵 加分项
- [x] 回访识别：Path A 主叫号+Path B 报车牌+确认闸门，prompts/agent/memory 已落地，revisit_demo 3 场景实测通过（待接语音）
  - [ ] WebRTC demo 把主叫号带进 participant 属性（Path A 依赖）；语音端接线后端到端回归
- [x] 门卫查询 Agent：NL→只读SQL（本周多少车/某人本月几次/峰值时段）— console /api/ask 已实测通过
- [ ] 门卫查询 Day2：公司名归一化、时区、"本周"口径（见 HANDOFF §决策9）
- [ ] 图-lite 层：pgvector 语义索引（事由/公司别名模糊匹配）/ 可选 Apache AGE
- [ ] token 对账：`usage_ledger` 读/写 token + STT/TTS 秒数 + 电话分钟；per-call 成本报告
- [x] 完整 trace/log：`app/trace.py` 双写 Neon + JSONL；console Trace tab 回放 — 已验证
- [ ] Admin Console 扩展（可选）：成本看板 / 温度参数 / 提示词版本管理
- [ ] Serverless：CF Workers（门卫查询 API）+ GitHub Actions CI/CD + Neon
- [ ] 多路并发（多车同时拨打）
- [ ] 企业微信双向：自建应用 + 回调，保安"点按钮放行"

## ⚪ 打磨 / 交付物
- [ ] 对话自然度调优，达"像真人"标准
- [ ] 并发 / 异常 / 静音 / 听不清 兜底话术
- [ ] Figma 架构图（等授权，存 Yijun Sun team draft）
- [ ] 中英双语选型报告 doc + pdf
- [ ] 1–2 分钟 demo 视频（拨号 → 采集 → 微信收到）
- [ ] 答辩材料整理

## 📌 事务性
- [ ] 向对接人确认题目实际收到日
- [ ] 授权 Figma MCP
- [ ] 建 GitHub 远程仓库并 push（需用户确认后进行）
