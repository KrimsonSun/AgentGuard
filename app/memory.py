"""长期记忆 = Neon Postgres（唯一事实源）。

边界：LLM 不直接看库，只拿这里检索出的一小段（回访摘要）。
详见 docs/HANDOFF.md §决策1。
"""
import asyncpg

from .config import settings
from .slots import VisitSlots

_pool: asyncpg.Pool | None = None


async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
    return _pool


async def lookup_returning_visitor(plate: str = "", phone: str = "") -> dict | None:
    """回访识别：车牌/手机号索引点查（O(1)），返回可直接注入的画像。"""
    row = await (await pool()).fetchrow(
        """SELECT plate, phone, visitor_name, usual_company, usual_purpose,
                  visit_count, last_visit_at, summary
           FROM visitor_profiles
           WHERE ($1 <> '' AND plate = $1) OR ($2 <> '' AND phone = $2)
           LIMIT 1""",
        plate, phone,
    )
    return dict(row) if row else None


async def save_visit(call_id: str, s: VisitSlots) -> int:
    """落一条访问事件（不可变历史），并 upsert 访客画像。"""
    p = await pool()
    async with p.acquire() as conn, conn.transaction():
        visit_id = await conn.fetchval(
            """INSERT INTO visits (call_id, plate, company, phone, purpose, visitor_name)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            call_id, s.plate, s.company, s.phone, s.purpose, s.visitor_name,
        )
        summary = f"{s.visitor_name or '访客'}，常来{s.company}{s.purpose}"
        await conn.execute(
            """INSERT INTO visitor_profiles
                 (plate, phone, visitor_name, usual_company, usual_purpose,
                  visit_count, last_visit_at, summary)
               VALUES ($1, $2, $3, $4, $5, 1, now(), $6)
               ON CONFLICT (plate) DO UPDATE SET
                 phone = EXCLUDED.phone,
                 visitor_name  = COALESCE(EXCLUDED.visitor_name, visitor_profiles.visitor_name),
                 usual_company = EXCLUDED.usual_company,
                 usual_purpose = EXCLUDED.usual_purpose,
                 visit_count   = visitor_profiles.visit_count + 1,
                 last_visit_at = now(),
                 summary       = EXCLUDED.summary""",
            s.plate, s.phone, s.visitor_name, s.company, s.purpose, summary,
        )
    return visit_id
