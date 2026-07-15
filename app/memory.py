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


async def save_visit(call_id: str, s: VisitSlots, elapsed_s: float | None = None) -> int:
    """落访问事件 + 解析/建访客(按手机) + 记录车辆(一人多车)。返回 visit_id。

    elapsed_s：接通→保安送达耗时（25s SLA 指标），落库供值守台/对账展示。
    """
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
            """INSERT INTO visits (call_id, visitor_id, plate, company, phone, purpose, visitor_name, elapsed_s)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
            call_id, visitor_id, s.plate, s.company, s.phone, s.purpose, s.visitor_name, elapsed_s,
        )
    return visit_id


# ============ 门卫台 Agent 用的读/写操作（改+合并，写操作在端点层走 HITL 确认）============

async def find_candidates(name: str = "", phone: str = "", plate: str = "") -> list[dict]:
    """按 姓名/手机/车牌 找候选访客（用于消歧“是哪个张师傅”）。任一条件命中即返回，带名下车牌。"""
    conds, args = [], []
    if name:
        args.append(f"%{name}%"); conds.append(f"v.visitor_name ILIKE ${len(args)}")
    if phone:
        args.append(f"%{phone}%"); conds.append(f"v.phone LIKE ${len(args)}")
    if plate:
        args.append(f"%{plate}%")
        conds.append(f"EXISTS (SELECT 1 FROM vehicles ve WHERE ve.visitor_id=v.id AND ve.plate ILIKE ${len(args)})")
    if not conds:
        return []
    sql = f"""SELECT v.id, v.phone, v.visitor_name, v.usual_company, v.usual_purpose,
                     v.visit_count, v.last_visit_at,
                     COALESCE((SELECT string_agg(plate, '、' ORDER BY last_seen DESC)
                               FROM vehicles WHERE visitor_id=v.id), '') AS plates
              FROM visitors v WHERE {' OR '.join(conds)}
              ORDER BY v.last_visit_at DESC NULLS LAST LIMIT 20"""
    rows = await (await pool()).fetch(sql, *args)
    return [dict(r) for r in rows]


async def visitor_report(visitor_id: int) -> dict | None:
    """某访客的完整画像 + 按事由拆分的来访明细（门卫台确认身份后作答用）。

    返回：身份(姓名/手机/车牌) + 总次数 + by_purpose[{purpose, n, last_at}]。
    次数以 visits 实际行数为准（与拆分之和一致），不用可能被 seed 改过的 visit_count。
    """
    p = await pool()
    v = await p.fetchrow(
        """SELECT id, phone, visitor_name, visit_count, last_visit_at,
                  COALESCE((SELECT string_agg(plate, '、' ORDER BY last_seen DESC)
                            FROM vehicles WHERE visitor_id = $1), '') AS plates
           FROM visitors WHERE id = $1""", visitor_id)
    if not v:
        return None
    rows = await p.fetch(
        """SELECT purpose, count(*) AS n, max(entered_at) AS last_at
           FROM visits WHERE visitor_id = $1 GROUP BY purpose ORDER BY n DESC, last_at DESC""",
        visitor_id)
    total = await p.fetchval("SELECT count(*) FROM visits WHERE visitor_id = $1", visitor_id)
    return {**dict(v), "visits_total": total, "by_purpose": [dict(r) for r in rows]}


async def update_visitor(visitor_id: int, visitor_name: str | None = None, phone: str | None = None,
                         usual_company: str | None = None, usual_purpose: str | None = None) -> dict | None:
    """更新访客信息（只改传入的非空字段）。返回更新后的行。"""
    fields = {"visitor_name": visitor_name, "phone": phone,
              "usual_company": usual_company, "usual_purpose": usual_purpose}
    sets, args = [], []
    for k, val in fields.items():
        if val is not None:
            args.append(val); sets.append(f"{k} = ${len(args)}")
    if not sets:
        return None
    args.append(visitor_id)
    sql = f"UPDATE visitors SET {', '.join(sets)} WHERE id = ${len(args)} RETURNING *"
    row = await (await pool()).fetchrow(sql, *args)
    return dict(row) if row else None


async def merge_visitors(keep_id: int, merge_id: int) -> dict | None:
    """把 merge_id 合并进 keep_id（治车牌听花的重复画像）：车辆/访问归到 keep，次数累加，删被合并者。"""
    if keep_id == merge_id:
        return None
    p = await pool()
    async with p.acquire() as conn, conn.transaction():
        # 删掉 merge 名下、keep 已有的重复车牌，避免 UNIQUE(visitor_id,plate) 冲突
        await conn.execute(
            """DELETE FROM vehicles m WHERE m.visitor_id = $2
               AND EXISTS (SELECT 1 FROM vehicles k WHERE k.visitor_id = $1 AND k.plate = m.plate)""",
            keep_id, merge_id)
        # 其余车辆 + 全部访问记录 归到 keep
        await conn.execute("UPDATE vehicles SET visitor_id = $1 WHERE visitor_id = $2", keep_id, merge_id)
        await conn.execute("UPDATE visits SET visitor_id = $1 WHERE visitor_id = $2", keep_id, merge_id)
        # 次数累加 + 取更近的最近来访 + 补全 keep 的空字段
        await conn.execute(
            """UPDATE visitors k SET
                 visit_count   = k.visit_count + m.visit_count,
                 last_visit_at = GREATEST(k.last_visit_at, m.last_visit_at),
                 visitor_name  = COALESCE(k.visitor_name, m.visitor_name),
                 usual_company = COALESCE(k.usual_company, m.usual_company),
                 usual_purpose = COALESCE(k.usual_purpose, m.usual_purpose)
               FROM visitors m WHERE k.id = $1 AND m.id = $2""",
            keep_id, merge_id)
        await conn.execute("DELETE FROM visitors WHERE id = $1", merge_id)
        row = await conn.fetchrow("SELECT * FROM visitors WHERE id = $1", keep_id)
    return dict(row) if row else None
