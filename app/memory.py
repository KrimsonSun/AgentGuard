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
    """回访识别（决策18）：手机为主、车牌经 vehicles 兜底，返回可注入的画像。

    返回含 plate=该访客最近一辆车（兼容旧调用方用 prof['plate']）。
    """
    p = await pool()
    row = None
    if phone:
        row = await p.fetchrow(
            """SELECT v.id, v.phone, v.visitor_name, v.usual_company, v.usual_purpose,
                      v.visit_count, v.last_visit_at, v.summary,
                      (SELECT plate FROM vehicles WHERE visitor_id = v.id ORDER BY last_seen DESC LIMIT 1) AS plate
               FROM visitors v WHERE v.phone = $1""",
            phone,
        )
    if not row and plate:
        row = await p.fetchrow(
            """SELECT v.id, v.phone, v.visitor_name, v.usual_company, v.usual_purpose,
                      v.visit_count, v.last_visit_at, v.summary, ve.plate
               FROM visitors v JOIN vehicles ve ON ve.visitor_id = v.id
               WHERE ve.plate = $1 ORDER BY ve.last_seen DESC LIMIT 1""",
            plate,
        )
    return dict(row) if row else None


async def save_visit(call_id: str, s: VisitSlots) -> int:
    """落访问事件 + 解析/建访客(按手机) + 记录车辆(一人多车)。返回 visit_id。"""
    p = await pool()
    summary = f"{s.visitor_name or '访客'}，常来{s.company}{s.purpose}"
    async with p.acquire() as conn, conn.transaction():
        # 1) 按手机解析或新建访客（身份主键=手机）
        visitor_id = await conn.fetchval(
            """INSERT INTO visitors
                 (phone, visitor_name, usual_company, usual_purpose, visit_count, last_visit_at, summary)
               VALUES ($1, $2, $3, $4, 1, now(), $5)
               ON CONFLICT (phone) DO UPDATE SET
                 visitor_name  = COALESCE(EXCLUDED.visitor_name, visitors.visitor_name),
                 usual_company = EXCLUDED.usual_company,
                 usual_purpose = EXCLUDED.usual_purpose,
                 visit_count   = visitors.visit_count + 1,
                 last_visit_at = now(),
                 summary       = EXCLUDED.summary
               RETURNING id""",
            s.phone, s.visitor_name, s.company, s.purpose, summary,
        )
        # 2) 记录/更新车辆（一人可多车）
        if s.plate:
            await conn.execute(
                """INSERT INTO vehicles (visitor_id, plate) VALUES ($1, $2)
                   ON CONFLICT (visitor_id, plate) DO UPDATE SET last_seen = now()""",
                visitor_id, s.plate,
            )
        # 3) 落访问事件
        visit_id = await conn.fetchval(
            """INSERT INTO visits (call_id, visitor_id, plate, company, phone, purpose, visitor_name)
               VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id""",
            call_id, visitor_id, s.plate, s.company, s.phone, s.purpose, s.visitor_name,
        )
    return visit_id
