"""token/成本台账 —— 每次 LLM/STT/TTS 调用后立即记账（CLAUDE.md 原则4）。

读 token = prompt_tokens；写 token = completion_tokens。以 provider 回传为准，禁止事后估算。
OpenRouter 精确成本可用 GET /api/v1/generation?id= 二次核对（total_cost）。
"""
from . import memory


async def record_llm(
    call_id: str,
    turn_index: int,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cost: float = 0.0,
) -> None:
    await (await memory.pool()).execute(
        """INSERT INTO usage_ledger
             (call_id, turn_index, component, provider, model,
              prompt_tokens, completion_tokens, cache_read_tokens, cache_write_tokens, cost)
           VALUES ($1, $2, 'llm', 'openrouter', $3, $4, $5, $6, $7, $8)""",
        call_id, turn_index, model,
        prompt_tokens, completion_tokens, cache_read_tokens, cache_write_tokens, cost,
    )


async def record_media(
    call_id: str,
    component: str,  # 'stt' | 'tts' | 'telephony'
    provider: str,
    audio_seconds: float = 0.0,
    char_count: int = 0,
    cost: float = 0.0,
) -> None:
    await (await memory.pool()).execute(
        """INSERT INTO usage_ledger
             (call_id, component, provider, audio_seconds, char_count, cost)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        call_id, component, provider, audio_seconds, char_count, cost,
    )


async def call_summary(call_id: str) -> dict | None:
    row = await (await memory.pool()).fetchrow(
        "SELECT * FROM call_cost_summary WHERE call_id = $1", call_id
    )
    return dict(row) if row else None


def format_summary(d: dict) -> str:
    """通话结束时打印的一行对账。"""
    return (
        f"[对账 {d['call_id']}] 读token={d['read_tokens'] or 0} 写token={d['write_tokens'] or 0} "
        f"cache读={d['cache_read'] or 0} STT={d['stt_seconds'] or 0}s TTS={d['tts_chars'] or 0}字 "
        f"通话={d['call_seconds'] or 0}s 成本=${d['total_cost'] or 0:.4f}"
    )
