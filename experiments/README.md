# 实验记录（Day1 spike · LLM 半场）

> 只用 OpenRouter + Neon 跑的离线验证，不含语音/微信。复现：`.venv/bin/python -m experiments.brain_test`

## 门卫大脑 · 候选快模型对比（2026-07-13）

同一剧本（司机第一句给 3 项「沪A12345，来蓝色鲸鱼送货的」，随后补手机号），跑真实工具调用循环，
真实写 Neon（visits/usage_ledger，测后已清理）。原始数据见 `brain_test_result.json`。

| 模型 | 首字延迟 | LLM轮次 | 读token | 写token | 收齐 | 结论 |
|---|---|---|---|---|---|---|
| **google/gemini-2.5-flash-lite** | **0.74s** | **4** | **2453** | **138** | ✅ | 🏆 最快·最省·最少轮次 → **选为默认** |
| z-ai/glm-4.7-flash | 1.77s | 4 | 3637 | 312 | ❌ | **漏手机号却硬说"已通知门卫"**（幻觉式收尾，正确性红旗，淘汰） |
| qwen/qwen3.5-flash-02-23 | 2.35s | 6 | 6155 | 576 | ✅ | 对，但拆成 6 轮工具调用 → 语音里累积延迟更高 |
| deepseek/deepseek-v4-flash | 5.69s | 5 | 5536 | 401 | ✅ | 对，但首字 5.69s，不适合实时语音 |

**决策**：默认模型 = `google/gemini-2.5-flash-lite`（已写入 Neon `app_config`，可在 admin console 改）。

## STT/TTS 中文实测 bench（`stt_tts_bench.py`，2026-07-13）

可插拔 provider（有 key 才跑）；重点评车牌/手机号（门卫场景最易错）。今晚基线用 macOS `say` 合成音频 + OpenRouter voxtral。

| provider | 均延迟 | 均准确 | 车牌 | 手机 |
|---|---|---|---|---|
| openrouter/voxtral（批处理基线） | 1006ms | 45% | 0/2 ❌ | 1/1 ✅ |

**读数（都是有用信号）**：
1. **车牌是最难的**：voxtral 把"沪A12345"听成"12345"、"沪B88888"听成"B88888"——省份简称+字母最易丢。门卫场景车牌是主键，这项必须过关 → 需要**流式+中文强**的 ASR，且可能要加车牌纠错/受限词表。
2. **手机号 OK**：11 位数字准确转出。
3. **再次印证决策8**：批处理 voxtral 又慢又差，生产必须用专用流式 ASR。
4. **合成音频偏乐观**：`say` 语音干净，真实电话噪声下更低；且合成车牌读法不自然 → 真实对比要用**真人录音或高质量 TTS 音频**。

**下一步（key 到位）**：优先补 **火山引擎 volcengine**（一账号 STT+TTS、官方 livekit 插件、中文原生）；对比 Deepgram/Cartesia。
TTS 比 **首字节延迟(TTFB)**（语音体验关键）。骨架已在 `stt_tts_bench.py` 的 STT_PROVIDERS/PROVIDERS。

## 发现 / 待办

1. **正确性 > 速度**：glm 更快但幻觉收尾（漏项硬收），实测才抓得到 → Day2 加**难例**：
   模糊车牌、纠错（"不是A是B"）、一句话全给、听不清重问。单场景不足以定终选。
2. **读 token 偏高**：系统提示每轮重复且未开 prompt cache（2453~6155 读）→ 开缓存可显著降本，
   对应 `usage_ledger` 的 cache_read/write 列。
3. **成本列暂为 0**：OpenRouter usage 默认不含 cost → 加 `extra_body={"usage":{"include":true}}`
   或查 `/generation`。读/写 token（硬指标）已准确落库。
4. **音频端点定性发现**：OpenRouter 仅有 `openai/gpt-audio`、`mistralai/voxtral`（批处理/LLM-audio），
   **无流式 ASR**；`/audio/transcriptions`(Whisper) 是文件式 → **坐实决策8**：实时语音走专用流式厂商。
5. **对账闭环验证通过**：4 个模型的读/写 token 均从 Neon `call_cost_summary` 视图正确回读。
