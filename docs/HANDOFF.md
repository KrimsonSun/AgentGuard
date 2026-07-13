# AgentGuard · HANDOFF（决策 · trade-off · 答辩要点）

> 跨会话 / 交接 / 答辩的上下文承载文档。**每做一个关键技术决策就在此追加一条 ADR**，
> 写清「选了什么 / 为什么 / 放弃了什么 / 代价」。这是 30 分钟技术答辩的弹药库。

## 当前状态（截至 Day 1 · 2026-07-13）

- ✅ 选型定稿、公开仓库、harness 文档全套、Figma+Mermaid 架构图。
- ✅ Neon 接通并建表；Admin Console（模型运行时切换）落库端到端验证通过。
- ✅ 代码骨架：`app/`（单Agent + 记忆 + 台账 + 企微推送）、`admin/`、`db/schema.sql`。
- ⏳ 进行中：Day1 语音回环 + STT/TTS 实测；对话大脑验证。
- 🔓 未决：STT/TTS provider（Day1 实测选）、LiveKit Secret（待补）、企业微信（07-14 自建）。

## 平台与环境（凭证一律在 `.env`，本仓库不含任何密文）

| 平台 | 用途 | 状态 | 免费 |
|---|---|---|---|
| OpenRouter | LLM 大脑 | ✅ 有效 | 按量，全程 <$5 |
| Neon Postgres | 记忆/台账/运行时配置 | ✅ 已接通建表 | ✅ 免费档 |
| LiveKit Cloud | 实时媒体 + WebRTC 呼入 | ⚠️ 待补 API Secret | ✅ 免费档 |
| 企业微信群机器人 | 保安推送 | ⬜ 待自建 | ✅ 免费 |
| 中文流式 STT/TTS | 识别/合成 | ⬜ Day1 实测选 | 按量 |
| CF Workers / GH Actions | 门卫查询API / CI（加分） | ⬜ Day6 | ✅ 公开仓库免费 |

> 环境变量清单见 `.env.example`；私密凭证与账号交接见 repo 外的 `~/Documents/Git/Yijun/`。

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
**注意**：STT/TTS 必须用**专用流式服务**（带 LiveKit 插件），**不是** OpenRouter 音频端点（那是文件/批处理，会把转写/合成堆到关键路径上，延迟不可接受）——理由详见决策8纠正。LLM 才在 OpenRouter。

**为什么不用端到端 Speech-to-Speech**（OpenAI Realtime / Gemini Live）：
1. **OpenRouter 目前没有 realtime 语音对语音**（只有文本 chat + 分离的 STT/TTS 端点，且转写是文件式）。要把大脑收敛到 OpenRouter，就得走链式。
2. **token 对账**：链式每轮是离散的文本 LLM 调用，读/写 token 精确可查（对账是本项目硬指标）；S2S 的音频 token 计费更糊。
3. **控制力**：slot 填充、工具调用、回访注入都在文本层，逻辑可控可测。

**代价**：链式端到端延迟天然高于 S2S。**缓解**：流式 STT + 快模型 + 流式 TTS + 良好 turn detection，把"接通→采集→推送"压进 25s，对话做到 3 轮≈15s。若延迟/自然度实测不达标，S2S 作为答辩中讨论的备选。

**框架**：默认 **LiveKit Agents**（SIP/telephony 成熟、有 turn-detector 模型、与 Twilio SIP 集成好）；Pipecat 为备选。

---

## 决策 3（v2 修订 2026-07-12）— 呼入通道：可插拔边缘；demo 主线 WebRTC 网页通话 + 企微语音消息第二通道；PSTN 为生产路径

**修订原因**：v1 定 Twilio 优先；随后确认 Twilio 注册对用户有实际摩擦（国际支付/身份验证不便）。重新评估。

**题面事实（引用原文，防走偏）**：
- 必须交付："用户拨打号码（可用你自己的电话作为Demo）→ Agent接听"；25s 从"电话接通（Agent开始说话）"计时。
- 但 FAQ 同时说：号码方案"本身就是考察的一部分……你说了算""遇到困难请记录下来，答辩时讨论"；并鼓励"涉及微信或电话的方案大胆想象不受局限"、点名 QClaw/OpenClaw。

**核实到的事实（勿凭记忆）**：
- Twilio 自 2023-11 不支持向中国大陆外呼；大陆手机拨 Twilio 海外号质量不稳；注册需国际支付方式。
- 微信侧**没有实时通话 API**：企业微信/微信客服只支持**语音消息**，bot 无法"接起"一通微信语音电话；协议破解方案封号风险大，违背"跑通且稳定"。
- 2026-03 腾讯官方把 OpenClaw 接入微信/QQ（QClaw，内测），企业微信有官方 OpenClaw 接入页——**语音消息 bot 通道可跑通且相对稳定**。

**决策（分层解耦，答辩主线）**：
1. **呼入边缘做成可插拔**：核心（LiveKit 房间 + STT→LLM→TTS + 记忆 + 企微推送 + 台账）与呼入方式无关。
2. **Demo 主线 = LiveKit WebRTC 网页通话**：扫码/点链接即"拨打"，真实时语音，25s 口径成立；零号码成本、零注册摩擦、大陆直连。
3. **第二通道 = 企业微信语音消息 agent**（QClaw/OpenClaw 方向）：加分 + 兜底。
4. **生产路径 = SIP/PSTN**（Twilio/阿里云/SIP trunk），文档讲清接入点；若 Twilio 试用注册顺利（试用号免费），SIP 一插即回题面最字面形态。

**风险与对策**：WebRTC/微信都不是字面的"拨打电话号码"——**已列为向对接人确认的第一问题**（题目鼓励提问）。确认前按可插拔架构开工，不被阻塞。

**成本澄清（"为什么要买号"）**：接 PSTN 来电必须有一个电话号（DID）。但 Twilio **试用号几乎免费**（送试用额度，够 demo；仅有试用前置提示音），正式号也只 ~$1/月 + ~$0.0085/分钟。号本身不是成本问题，**中国可达性**才是。更便宜的同类：Telnyx / SignalWire（Twilio 兼容 API，更省）/ Plivo，媒体模型一样。demo 甚至可用 SIP 软电话/浏览器 WebRTC 呼入，完全不花号钱。

**WhatsApp 方案评估（否决，答辩可讲）**：WhatsApp Business Calling API 2025 起可用、原则上能把来电经 SIP 路由到 AI 语音 agent，但对本场景是坏选择——① **场景不符**：司机在门口用手机拨号盘拨 PSTN 号，不是 WhatsApp 应用内呼叫（需双方都装 WhatsApp）；② **中国不可用**：WhatsApp 在大陆被墙，上海园区司机不会用；③ **门槛更高**：需 Meta 商业认证 + 业务号"每日 2000+ 消息额度"+ 开通通话权限；④ **仍需 SIP**：底层照样走 SIP trunk/webhook，没省掉媒体管道，反而多一层 Meta 审批。→ 既不省钱也不省事，且和"电话拨号 + 中国环境"不匹配。

---

## 决策 4 — 微信推送：企业微信群机器人 Webhook

**选择**：企业微信群机器人 Webhook（HTTP POST JSON，支持 text/markdown/模板卡片，限 20 条/分钟，webhook 需保密）。用户单开一个企业微信承载。

**为什么不用个人微信**：个人微信机器人（itchat/wechaty 类）违反 ToS、易封、不稳。企业微信是合规可靠路径。

**可选升级**：保安"点按钮放行"的双向交互需**企业微信自建应用 + 回调 URL**，列为有时间再做（用户："有时间可以做微信工作流"）。

---

## 决策 5 — Serverless：混合架构

实时语音是长连接、有状态的媒体环路，**不适合无状态 Serverless**（CF Workers/Lambda 有执行时限、无持久媒体套接字）。媒体 worker 跑常驻主机；其余上 Serverless。

**与题目加分组合的对齐**：题目建议的 serverless 例子是 `GitHub Actions CI/CD + Cloudflare Workers + OpenRouter + Neon PostgreSQL + Auth`。我们的选型**直接命中其中两项**——OpenRouter(LLM，serverless SaaS) + Neon(serverless Postgres)；再补 **CF Workers**（门卫查询 API）+ **GH Actions**（CI/CD）即可凑齐整套。所以 OpenRouter/Neon 不是随意选，是贴着评审给的组合走。

**媒体这一块怎么尽量"serverless"**：用 **LiveKit Cloud** 托管媒体 + **托管 Agent 部署**（你把 agent 部署上去、由它常驻运行，你不管服务器），这是媒体组件最接近 serverless 的做法；或退而求其次跑一台便宜 VM。

**结论**：可辩护的**混合架构**——能 serverless 的全 serverless（LLM/DB/查询API/CI/微信webhook），只有天然需要长连接的媒体用托管常驻。"为什么实时媒体不能纯 serverless、我们怎么处理"本身就是很强的答辩点。

---

## 决策 6 — 单 Agent，不做 multi-agent 编排

一个门卫大脑 + 工具（`lookup_returning_visitor / save_visit / notify_guard / query_stats`）。
加分项"门卫查询 Agent"是**同一单 agent 模式换入口 + 一个查询工具**，不是 agent 集群。
理由：轻量、上下文边界清晰、延迟可控、token 可对账。

---

## 决策 7（2026-07-13）— 运行时配置 + Admin Console；模型哲学：快而非聪明

**问题**：模型 id 硬编码 .env → 切换要改文件重启，没法快速实测对比。
**选择**：Postgres `app_config` 表为配置事实源；`admin/`（FastAPI + 单页前端，`uvicorn admin.server:app --port 8100`）
列出 OpenRouter 全部模型（价格/上下文，服务端代理，**前端不见密钥**）一键切换。
**读取语义**：agent **每通电话开始读一次**（索引点查 ~20ms，与媒体建立并行，**不在接听路径**），
通话内固定（prompt cache 命中 + 账单口径一致），下一通即生效。否决：TTL 缓存（多余）、改 env 重启（慢）。

**秒接澄清（用户质疑推动）**：接听速度与配置读取无关。开场白是固定文案，接通后直接 `session.say()`
走 TTS（可预合成缓存）——**LLM 不在接听路径上**。开口延迟 ≈ TTS 首包（几百 ms）。

**模型哲学（用户校准："不需要 agent 太聪明"）**：任务是 slot 抽取 + 短句 + 工具调用 = 中等难度，flash 级足够。
每轮响应间隙的瓶颈排序：**轮次数 >> 端点检测静音等待(300-700ms) > LLM TTFT(200-800ms) > TTS首包(100-300ms) > STT增量**。
最大杠杆是对话设计（一次问多项→3轮）与 turn-detection 调优；console 的价值 = 用实测数据选"够用且最快"。
候选：qwen3.5-flash / deepseek-v4-flash / gemini-2.5-flash-lite（Day2 实测定）。

**坑记录（答辩素材）**：① `.env.example` 行内注释被 dotenv 读进值里 → 注释必须独立成行；
② OpenRouter `openrouter/*` 动态路由伪模型价格为 -1，无固定单价无法对账 → console 已过滤；
③ 系统 Python 3.9 过老，venv 用 Homebrew 3.13。

---

## 决策 8（2026-07-13）— 平台收敛与成本控制

**问题（用户质疑）**：要管理的平台是否太多？
**收敛结果**：必须新开的账号仅 3 个，全部免费档——**Neon**（记忆/台账事实源，加分组合点名）、
**LiveKit Cloud**（免费档解决 WebRTC 公网可达/TURN，自建要开端口配 TURN 不值）、
**企业微信**（个人可注册"团队"类型，无需营业执照，群机器人 webhook 免费）。
**关键收敛（❌ 已纠正，见下）**：曾计划 STT/TTS 用 OpenRouter 音频端点三合一收敛。

> **⚠️ 纠正（2026-07-13，用户质疑推动）**：该收敛**做错了**——为省一个平台牺牲了核心链路延迟，本末倒置。
> **原因**：OpenRouter 音频端点是**文件式（批处理）**：音频必须整段说完→上传→从头转完才出文字，
> 全部堆在"说完之后的关键路径"串行发生，且耗时随句长增加（每轮 +几百ms~1s+）；TTS 同理要整段合成完才开口。
> 而**流式** STT/TTS 把识别/合成叠在说话与播放时间里，说完即基本转好。延迟差源于**流式 vs 批处理**，
> **与"是否同一平台"无关**：OpenRouter 是网关不是管道，三次调用仍独立，音频还被分发到不同后端（多一跳）。
> **"合并对账"理由也不成立**：usage_ledger 本就按 component=stt/tts/llm 分厂商记账，独立厂商不损失对账。
> **最终架构**：LLM 留 OpenRouter（文本流式 OK）；**STT/TTS 用专用流式服务（带 LiveKit 插件）**，
> 理想选一家中文 ASR+TTS 都做的厂商（火山/阿里，+1 平台）。Day1 实测延迟+中文自然度定。
**GH Actions 角色澄清**：只做 CI/CD（lint/test/部署 Workers），**不托管常驻 agent**；公开仓库免费。
**成本预期**：全项目 < $5，全部在 OpenRouter 扣费，usage_ledger 逐笔可对账。
**依据**：① 题目加分组合原文点名；② 用户约束（OpenRouter 收口/轻量/可对账）；
③ free-tier 优先；④ 事实现查现验（非 LLM 记忆）。

---

## 决策 9（2026-07-13 夜）— 可观测性（trace/log）+ 查询 console（回答用户 Q2/Q3）

**Q2 reasoning/trace/log**：Agent 是**单 Agent 工具调用循环**（非长链思考模型，门卫要快）；"推理"=判断缺哪些字段并转成工具调用。
新增 `app/trace.py`：**双写** Neon `call_traces`（可查询）+ 本地 JSONL（`logs/traces/{call_id}.jsonl`，gitignored，可 grep/回放）。
记录 greeting/user_utterance/llm_message(含 latency_ms)/tool_call/tool_result/hangup。已用 `experiments/trace_demo.py` 跑真实通话验证：
一通电话 5 次 LLM 调用累计 ~5.6s（1882+1240+1369+585+508ms）——为 25s 预算拆解提供真数据。

**Q3 console 查询**：admin console 扩为三 tab——模型切换 / **访客查询** / **通话 Trace**。新端点：
`/api/visits`(结构化搜索) `/api/stats`(统计:峰值时段/回访榜/单位分布) `/api/ask`(**门卫查询Agent**:NL→只读SQL→自然语言作答) `/api/traces`(回放)。
**门卫查询安全护栏**：LLM 生成 SQL 后强制校验（必须 SELECT、禁 DML/多语句/pg_/注释、去尾分号、限两表、加 LIMIT），
只读事务 + `statement_timeout`。实测："张师傅这个月几次→6次送货"✅、"把手机号删掉"→拦截✅。

**发现（Day2 待办）**：① 公司名归一化——LLM 抽取出"蓝色鲸鱼"vs 播种"蓝色鲸鱼科技"，统计会分裂 → 需受控词表/别名归一；
② 时间戳时区——naive datetime 写入 TIMESTAMPTZ 显示为 UTC，峰值时段标签偏移 → 用 tz-aware；
③ NL"本周"= ISO 周一起算，与用户"近7天"直觉不同 → prompt 里明确口径。

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
