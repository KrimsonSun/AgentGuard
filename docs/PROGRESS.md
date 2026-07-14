# AgentGuard · 已做进展

> 倒序记录，每条含日期。实现阶段请顺手记录**用 AI 辅助编码的关键决策与审查点**（答辩要考）。

## Day 1 · 2026-07-13（架构转向 Vapi）
- **关键约束更新**：用户人在美国（非国内）→ 推翻"你在国内"前提：火山不合适（国内实名+跨境延迟），Twilio 从美国好办。
- **决策12**：媒体层改用 **Vapi 托管**（电话+STT+TTS+打断，自带发号，$10 免费额度）。只替换未建成的媒体管道，
  大脑(OpenRouter)/记忆/回访/对账/trace/门卫查询全保留（作为 Vapi tools 打 Neon 后端）。平台 5→3。
- 中文语音在 Vapi 内选 Azure（美国可用、中文近母语）或 OpenAI，实测定。企业微信暂搁置。
- 待办：用户注册 Vapi 拿 key；我可先 scaffold Vapi 集成（assistant 配置 + tools webhook 后端）。

## Day 1 · 2026-07-13（回访真实感设计+验证）
- **回访方案**（HANDOFF §决策10）：Path A 主叫号码匹配→personalized 秒接开场；Path B 报车牌兜底；确认闸门防幻觉。
- `experiments/revisit_demo.py` 用真实种子张师傅画像实测 3 场景全过：完整确认(1轮放行)/中途改目的地(只改变化项)/含糊不乱登记。
- 落地：`prompts.py`(returning_greeting/context/human_last_visit + 回访铁律)；`agent.py` Path A 接线(`_caller_phone` + 注入)；py_compile 通过。
- 待办：WebRTC demo 需把主叫号带进 participant 属性（Path A 依赖）。

## Day 1 · 2026-07-13（深夜 · 自主调试第二轮 · 回答用户 Q2/Q3）
- **完整 trace/log 系统**（回答 Q2）：`app/trace.py` 双写 Neon `call_traces` + JSONL；
  `experiments/trace_demo.py` 跑真实通话验证——17 事件完整时间线，每步 latency，5 次 LLM 累计 ~5.6s。
- **console 三 tab**（回答 Q3）：模型切换 / 访客查询 / 通话 Trace。
  新端点 visits(搜索)/stats(统计)/ask(门卫查询Agent NL→只读SQL)/traces(回放)。浏览器实测三 tab 全通。
- **门卫查询 Agent**（加分项）实测：NL→SQL→作答，"张师傅这个月几次→6次送货"✅；恶意 DELETE 被只读护栏拦截✅。
  修了一个误杀：LLM 尾分号被当多语句拦，改为先去尾分号。
- **播种 16 条真实感演示数据** + 1 通真实 trace 通话（`seed_demo_data.py`/`reset_demo_data.py` 可控）。
- 发现（Day2）：公司名归一化、时区（UTC 偏移）、NL"本周"口径——已记 HANDOFF §决策9。

## Day 1 · 2026-07-13（夜间 · Claude 自主调试）
- **门卫大脑离线验证 + 候选模型对比**（`experiments/brain_test.py`，真实 OpenRouter 调用 + 真实写 Neon）：
  同一剧本跑 4 个快模型的完整工具调用循环。结果（详见 `experiments/README.md`）：
  - 🏆 **google/gemini-2.5-flash-lite**：首字 0.74s / 4 轮 / 读2453写138 / 收齐✅ → 设为默认（写入 app_config）
  - glm-4.7-flash：更快但**漏手机号硬收尾**（幻觉，正确性红旗，淘汰）；qwen 对但 6 轮偏慢；deepseek 首字 5.69s 太慢
  - **验证通过**：prompts/slots/memory.save_visit/ledger.record_llm 全链路真跑；对账视图正确回读读/写 token
  - 测试数据已从 Neon 清理（visits/usage_ledger/profiles 归零）
- **发现**：单场景不足 → Day2 加难例（模糊车牌/纠错/一句全给/听不清）；系统提示未缓存致读 token 偏高 → 开 prompt cache 降本。
- **LiveKit**：写入 URL + API Key（`APIimfqYXNGVED8` 待用户核对），**缺 API Secret**（用户 07-14 补）。
- **私密交接**：`~/Documents/Git/Yijun/`（repo 外）存含凭证的 handoff；公开 repo 文档只列平台不含密文。

## Day 1 · 2026-07-13
- **Neon 接通**：DATABASE_URL 写入 .env（gitignore 确认）；schema 应用成功——
  4 表(visits/visitor_profiles/usage_ledger/app_config)+1 视图(call_cost_summary)+pgvector 启用。
- **Admin Console 端到端验证**：PUT 启用模型 → 落 Neon app_config → GET/前端横幅读回，闭环成活。
- **纠正决策8的 STT/TTS 收敛**（用户质疑延迟推动）：OpenRouter 音频端点是文件/批处理，
  会把转写/合成堆到关键路径（每轮 +几百ms~1s+），延迟不可接受。改回**专用流式 STT/TTS**（LiveKit 插件）；
  LLM 仍在 OpenRouter。对账靠 usage_ledger 分厂商记账，不损失。平台净 +1（理想选中文 ASR+TTS 一体厂商）。
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
