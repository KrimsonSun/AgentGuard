# AgentGuard · Token 与成本对账设计

> 硬指标：**读 token（input/prompt）与写 token（output/completion）分列**，可逐通电话对账。
> LLM 按 token 计费，STT/TTS 按音频秒数/字符计费，电话按分钟计费——三类分开记，最后汇总。

## 1. 数据来源

| 组件 | 计量单位 | 取数方式 |
|---|---|---|
| LLM（OpenRouter） | prompt / completion token（+ cache 读/写） | 响应体 `usage`；精确成本用 `GET /api/v1/generation?id=`（`native_tokens_*`, `total_cost`） |
| STT | 音频秒数 | provider 返回 / 本地计时 |
| TTS | 字符数或音频秒数 | 合成请求字符数 / provider 返回 |
| 电话（Twilio） | 通话分钟 | Twilio 通话记录 / webhook |

## 2. `usage_ledger` 表（草案）

```sql
CREATE TABLE usage_ledger (
  id            BIGSERIAL PRIMARY KEY,
  call_id       TEXT NOT NULL,            -- 关联一通电话
  turn_index    INT,                      -- 第几轮（LLM 用）
  component     TEXT NOT NULL,            -- 'llm' | 'stt' | 'tts' | 'telephony'
  provider      TEXT,                     -- openrouter / deepgram / twilio ...
  model         TEXT,                     -- 具体模型或号码
  -- LLM 专用（读/写 token）
  prompt_tokens      INT DEFAULT 0,       -- 读 token
  completion_tokens  INT DEFAULT 0,       -- 写 token
  cache_read_tokens  INT DEFAULT 0,       -- 命中缓存的读 token
  cache_write_tokens INT DEFAULT 0,       -- 写入缓存的 token
  -- 媒体/电话专用
  audio_seconds  NUMERIC(10,2) DEFAULT 0, -- STT/TTS/电话 时长
  char_count     INT DEFAULT 0,           -- TTS 字符
  -- 成本（统一币种，如 USD）
  cost           NUMERIC(12,6) DEFAULT 0,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON usage_ledger (call_id);
```

## 3. 记账纪律（写进 CLAUDE.md 强约束）

- **每一次** LLM / STT / TTS 调用后，立刻写一行 `usage_ledger`（component 对应）。
- LLM 行必须填 `prompt_tokens`（读）与 `completion_tokens`（写）；启用 prompt cache 时另填 cache 读/写。
- 严禁"事后估算"——以 provider 回传为准；OpenRouter 成本以 `/generation` 为准。

## 4. per-call 对账视图（草案）

```sql
CREATE VIEW call_cost_summary AS
SELECT
  call_id,
  SUM(prompt_tokens)      AS read_tokens,      -- 读 token 合计
  SUM(completion_tokens)  AS write_tokens,     -- 写 token 合计
  SUM(cache_read_tokens)  AS cache_read,
  SUM(cache_write_tokens) AS cache_write,
  SUM(audio_seconds) FILTER (WHERE component='stt') AS stt_seconds,
  SUM(char_count)    FILTER (WHERE component='tts') AS tts_chars,
  SUM(audio_seconds) FILTER (WHERE component='telephony') AS call_seconds,
  SUM(cost)               AS total_cost
FROM usage_ledger
GROUP BY call_id;
```

## 5. 报告呈现

- 每通电话结束 → 控制台 / 日志打印一行对账（读 token / 写 token / 各项成本 / 合计）。
- 可选：把成本摘要附在门卫查询 Agent 的结果里，或做一个 CF Workers 小页面看累计。
- 中英双语报告里放一张"单通成本拆解"表，体现工程严谨度。
