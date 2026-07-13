"""运行时配置：Postgres app_config 表（admin console 写，agent 读）。

设计（HANDOFF §决策7）：
- 无 TTL 缓存 —— agent 每通电话开始读一次（索引点查 ~20ms，与媒体通道建立并行，
  不在接听路径上），通话内固定（保证 prompt cache 命中与账单口径一致），下一通即用新值。
- DB 不可用时兜底 .env，绝不阻断接听。
"""
from . import memory
from .config import settings


async def get(key: str, fallback: str = "") -> str:
    try:
        row = await (await memory.pool()).fetchrow(
            "SELECT value FROM app_config WHERE key = $1", key
        )
        return row["value"] if row else fallback
    except Exception:
        return fallback  # DB 未就绪/抖动 → 兜底 env，不影响通话


async def set(key: str, value: str) -> None:
    await (await memory.pool()).execute(
        """INSERT INTO app_config (key, value, updated_at)
           VALUES ($1, $2, now())
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
        key, value,
    )


async def get_model() -> str:
    return await get("openrouter_model", settings.openrouter_model)
