# Vapi 托管媒体层（决策12）

Vapi 管电话+STT+TTS+打断；**大脑(OpenRouter)和工具(记忆/回访/对账)是我们的**，在 `tools_server.py`。
换回自建 LiveKit 时这套工具原样复用（前面那层可插拔）。

## 组成
- `tools_server.py` — Vapi 调工具时打这里 → Neon（save_visit/lookup/notify + slot 累积 + trace）。**已本地冒烟通过。**
- `assistant.json` — 门卫助手配置（prompt、custom-llm 指 OpenRouter、中文语音 Azure、STT Deepgram、4 个工具）。
- `create_assistant.py` — 把配置推到 Vapi 建助手。

## 上线四步（拿到 VAPI_API_KEY 后）
```bash
# 1. 起工具后端
uvicorn vapi.tools_server:app --port 8200
# 2. 隧道给 Vapi 公网可达（Vapi 在云端，要能回调你）
cloudflared tunnel --url http://localhost:8200      # 或 ngrok http 8200
#    把输出的 https URL 填进 .env 的 VAPI_TOOLS_URL
# 3. 建助手
.venv/bin/python -m vapi.create_assistant
# 4. Vapi 控制台 → Phone Numbers → 免费测试号绑定此助手 → 拨打即 demo
```

## 成本备忘（决策12 修正）
Vapi 全算下来 ~$0.08/min，自建 ~$0.03/min，**约 2.5–3×**，差距是 Vapi $0.05/min 平台费。
demo 量级 $10 免费额度全覆盖；**生产长期跑则自建更省** → 定位：**原型/demo 用 Vapi，生产可转自建 LiveKit**（工具层不变）。

## 联调注意
Vapi webhook 字段名随版本微调（toolCallList/toolCalls、arguments str/obj、custom-llm 鉴权字段）；
`tools_server.py` 已做兼容，首次联调对照 https://docs.vapi.ai 校准。
