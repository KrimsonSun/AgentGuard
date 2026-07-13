-- AgentGuard schema · Neon Postgres（唯一事实源）
-- 初始化：psql "$DATABASE_URL" -f db/schema.sql
-- 设计依据：docs/HANDOFF.md §决策1（精简Postgres+图lite）、docs/TOKEN_ACCOUNTING.md

CREATE EXTENSION IF NOT EXISTS vector;  -- 图-lite：pgvector（Neon 内置可用）

-- ============ 访问事件（不可变历史，驱动统计与回访） ============
CREATE TABLE IF NOT EXISTS visits (
  id            BIGSERIAL PRIMARY KEY,
  call_id       TEXT NOT NULL,                     -- 关联一通通话
  plate         TEXT NOT NULL,                     -- 车牌号，如 沪A12345
  company       TEXT NOT NULL,                     -- 来访单位
  phone         TEXT NOT NULL,                     -- 手机号
  purpose       TEXT NOT NULL,                     -- 来访事由
  visitor_name  TEXT,                              -- 可选（"张师傅"）
  entered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),-- 入场时间（系统自动）
  purpose_embedding vector(1024)                   -- 图-lite：事由语义索引（加分层，可空）
);
CREATE INDEX IF NOT EXISTS idx_visits_plate    ON visits (plate);
CREATE INDEX IF NOT EXISTS idx_visits_entered  ON visits (entered_at);

-- ============ 访客画像（回访识别 = O(1) 点查，save_visit 时 upsert） ============
CREATE TABLE IF NOT EXISTS visitor_profiles (
  plate          TEXT PRIMARY KEY,
  phone          TEXT,
  visitor_name   TEXT,
  usual_company  TEXT,                             -- 最常来访单位
  usual_purpose  TEXT,                             -- 最常事由
  visit_count    INT NOT NULL DEFAULT 1,
  last_visit_at  TIMESTAMPTZ NOT NULL,
  summary        TEXT                              -- 注入 LLM 的一句话压缩摘要（工作记忆边界）
);
CREATE INDEX IF NOT EXISTS idx_profiles_phone ON visitor_profiles (phone);

-- ============ 运行时配置（admin console 写；agent 每通电话开始读一次，通话内固定） ============
CREATE TABLE IF NOT EXISTS app_config (
  key        TEXT PRIMARY KEY,        -- 如 'openrouter_model'
  value      TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ token/成本台账（读/写分列，禁止事后估算） ============
CREATE TABLE IF NOT EXISTS usage_ledger (
  id            BIGSERIAL PRIMARY KEY,
  call_id       TEXT NOT NULL,
  turn_index    INT,
  component     TEXT NOT NULL,             -- 'llm' | 'stt' | 'tts' | 'telephony'
  provider      TEXT,
  model         TEXT,
  prompt_tokens      INT DEFAULT 0,        -- 读 token
  completion_tokens  INT DEFAULT 0,        -- 写 token
  cache_read_tokens  INT DEFAULT 0,
  cache_write_tokens INT DEFAULT 0,
  audio_seconds  NUMERIC(10,2) DEFAULT 0,  -- STT/TTS/通话时长
  char_count     INT DEFAULT 0,            -- TTS 字符
  cost           NUMERIC(12,6) DEFAULT 0,  -- USD
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ledger_call ON usage_ledger (call_id);

-- ============ 通话 trace（可回放的完整推理/行为日志，独立于计费台账） ============
CREATE TABLE IF NOT EXISTS call_traces (
  id          BIGSERIAL PRIMARY KEY,
  call_id     TEXT NOT NULL,
  turn_index  INT,
  event_type  TEXT NOT NULL,   -- greeting|user_utterance|llm_message|tool_call|tool_result|error|hangup
  role        TEXT,            -- system|user|assistant|tool
  content     TEXT,            -- 文本 / 工具参数json / 工具结果
  tool_name   TEXT,
  latency_ms  INT,             -- 该步耗时（LLM 调用等）
  model       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_traces_call ON call_traces (call_id, id);

-- per-call 对账视图
CREATE OR REPLACE VIEW call_cost_summary AS
SELECT
  call_id,
  SUM(prompt_tokens)      AS read_tokens,
  SUM(completion_tokens)  AS write_tokens,
  SUM(cache_read_tokens)  AS cache_read,
  SUM(cache_write_tokens) AS cache_write,
  SUM(audio_seconds) FILTER (WHERE component='stt')       AS stt_seconds,
  SUM(char_count)    FILTER (WHERE component='tts')       AS tts_chars,
  SUM(audio_seconds) FILTER (WHERE component='telephony') AS call_seconds,
  SUM(cost)               AS total_cost
FROM usage_ledger
GROUP BY call_id;
