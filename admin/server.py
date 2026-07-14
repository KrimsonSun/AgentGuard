"""AgentGuard Admin Console — 运行时配置（模型切换等）。

启动（仓库根目录）：uvicorn admin.server:app --port 8100  →  http://localhost:8100
安全边界：OPENROUTER_API_KEY 只在服务端使用，前端永远看不到；本服务只应跑在本机/内网。
"""
import re
import secrets
import time
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from openai import AsyncOpenAI
from pydantic import BaseModel

from app import memory, runtime_config, trace  # 包名 app 在下方被 FastAPI 实例遮蔽，导入须在此之前
from app.config import settings

_basic = HTTPBasic()


def require_auth(cred: HTTPBasicCredentials = Depends(_basic)) -> str:
    """全局 HTTP Basic 认证。未设 ADMIN_PASSWORD 则一律拒绝（拒裸奔）。"""
    ok_user = secrets.compare_digest(cred.username, settings.admin_user)
    ok_pass = bool(settings.admin_password) and secrets.compare_digest(cred.password, settings.admin_password)
    if not (ok_user and ok_pass):
        detail = "未配置 ADMIN_PASSWORD（在 .env 设置后重启）" if not settings.admin_password else "账号或密码错误"
        raise HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Basic"})
    return cred.username


# 全局依赖：所有路由（含首页 HTML）都要过认证
app = FastAPI(title="AgentGuard Admin", dependencies=[Depends(require_auth)])
STATIC = Path(__file__).parent / "static"
_oai = AsyncOpenAI(api_key=settings.openrouter_api_key, base_url=settings.openrouter_base_url)

# /models 结果 5 分钟缓存：345+ 个模型的列表没必要每次刷新都打 OpenRouter
_models_cache: tuple[float, list[dict]] | None = None


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/models")
async def list_models() -> dict:
    global _models_cache
    if _models_cache and time.monotonic() - _models_cache[0] < 300:
        return {"data": _models_cache[1]}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"{settings.openrouter_base_url}/models",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
        )
        r.raise_for_status()
        raw = r.json()["data"]
    slim = []
    for m in raw:
        prompt_p = float(m.get("pricing", {}).get("prompt") or 0)
        completion_p = float(m.get("pricing", {}).get("completion") or 0)
        if prompt_p < 0 or completion_p < 0:
            continue  # openrouter/* 动态路由伪模型价格为 -1，无固定单价没法对账，直接排除
        slim.append({
            "id": m["id"],
            "name": m.get("name") or m["id"],
            "context": m.get("context_length") or 0,
            "prompt_1m": round(prompt_p * 1e6, 4),
            "completion_1m": round(completion_p * 1e6, 4),
        })
    _models_cache = (time.monotonic(), slim)
    return {"data": slim}


class ModelSelection(BaseModel):
    model: str


@app.get("/api/config")
async def get_config() -> dict:
    return {
        "model": await runtime_config.get_model() or "(未选择)",
        "env_fallback": settings.openrouter_model or "(未设置)",
    }


@app.put("/api/config")
async def put_config(sel: ModelSelection) -> dict:
    try:
        await runtime_config.set("openrouter_model", sel.model)
    except Exception as exc:  # DATABASE_URL 未配置 / schema 未初始化
        raise HTTPException(503, f"写入失败（检查 DATABASE_URL 与 db/schema.sql 是否已执行）：{exc}")
    return {"ok": True, "model": sel.model}


# ============ 访客查询（结构化搜索 / 统计 / 门卫查询Agent / trace） ============

@app.get("/api/visits")
async def search_visits(q: str = "", company: str = "", since_days: int = 0, limit: int = 50) -> dict:
    """结构化搜索：q 模糊匹配车牌/单位/称呼；可加单位、时间范围过滤。"""
    where, args = [], []
    if q:
        args.append(f"%{q}%")
        where.append(f"(plate ILIKE ${len(args)} OR company ILIKE ${len(args)} OR "
                     f"visitor_name ILIKE ${len(args)} OR phone ILIKE ${len(args)})")
    if company:
        args.append(company); where.append(f"company = ${len(args)}")
    if since_days > 0:
        args.append(since_days); where.append(f"entered_at >= now() - (${len(args)} || ' days')::interval")
    args.append(min(limit, 200))
    sql = (f"SELECT plate, company, phone, purpose, visitor_name, entered_at FROM visits"
           f"{' WHERE ' + ' AND '.join(where) if where else ''} ORDER BY entered_at DESC LIMIT ${len(args)}")
    rows = await (await memory.pool()).fetch(sql, *args)
    return {"count": len(rows), "visits": [dict(r) for r in rows]}


@app.get("/api/stats")
async def stats() -> dict:
    p = await memory.pool()
    total = await p.fetchval("SELECT count(*) FROM visits")
    week = await p.fetchval("SELECT count(*) FROM visits WHERE entered_at >= now() - interval '7 days'")
    by_hour = await p.fetch("SELECT extract(hour FROM entered_at)::int h, count(*) c FROM visits GROUP BY h ORDER BY c DESC")
    by_company = await p.fetch("SELECT company, count(*) c FROM visits GROUP BY company ORDER BY c DESC")
    by_purpose = await p.fetch("SELECT purpose, count(*) c FROM visits GROUP BY purpose ORDER BY c DESC")
    top = await p.fetch("SELECT visitor_name, phone, visit_count, usual_company FROM visitors ORDER BY visit_count DESC LIMIT 5")
    peak = by_hour[0]["h"] if by_hour else None
    return {
        "total": total, "this_week": week,
        "peak_hour": f"{peak:02d}:00-{peak+1:02d}:00" if peak is not None else None,
        "by_company": [dict(r) for r in by_company],
        "by_purpose": [dict(r) for r in by_purpose],
        "top_visitors": [dict(r) for r in top],
    }


class Ask(BaseModel):
    question: str


_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|truncate|grant|revoke|create|copy)\b|;|--|/\*|pg_", re.I)
_SCHEMA_HINT = (
    "表 visits(id, visitor_id 归属访客, plate 车牌, company 来访单位, phone 手机号, purpose 来访事由, visitor_name 称呼, entered_at 入场时间)；"
    "表 visitors(id, phone 手机=身份, visitor_name 称呼, usual_company 常访单位, usual_purpose 常访事由, visit_count 累计来访次数, last_visit_at 最近来访)；"
    "表 vehicles(id, visitor_id, plate 车牌)——一人可多车。"
    "按人计次用 visitors.visit_count；按车/按事由拆分用 visits 表 GROUP BY。"
    "注意：『某人来了几次』要取该访客的 visit_count（或按 visits 行数计），不是数 visitors 表的行数。"
    "今天是 2026-07-14。"
)


@app.post("/api/ask")
async def ask(a: Ask) -> dict:
    """门卫查询 Agent：自然语言 → 只读 SQL → 执行 → 自然语言作答。加分项。"""
    model = await runtime_config.get_model()
    # 1) NL → SQL
    gen = await _oai.chat.completions.create(
        model=model, temperature=0,
        messages=[
            {"role": "system", "content":
                f"你是只读数据分析助手。根据问题生成**一条** PostgreSQL SELECT。{_SCHEMA_HINT} "
                "只准 SELECT，只查上述两表，末尾加 LIMIT 100。只输出 SQL 本身，不要 markdown、不要解释。"},
            {"role": "user", "content": a.question},
        ],
    )
    sql = (gen.choices[0].message.content or "").strip().strip("`").removeprefix("sql").strip()
    sql = sql.rstrip(";").strip()  # 允许 LLM 习惯性的尾分号；下方 _FORBIDDEN 仍拦内部分号（多语句）
    # 2) 护栏校验
    if not sql.lower().startswith("select") or _FORBIDDEN.search(sql):
        raise HTTPException(400, f"生成的查询未通过只读校验：{sql[:200]}")
    if "limit" not in sql.lower():
        sql += " LIMIT 100"
    # 3) 只读事务执行
    try:
        async with (await memory.pool()).acquire() as conn:
            async with conn.transaction(readonly=True):
                await conn.execute("SET LOCAL statement_timeout = '4s'")
                rows = [dict(r) for r in await conn.fetch(sql)]
    except Exception as exc:
        raise HTTPException(400, f"查询执行失败：{str(exc)[:200]}\nSQL: {sql[:200]}")
    # 4) 结果 → 自然语言
    ans = await _oai.chat.completions.create(
        model=model, temperature=0.2,
        messages=[
            {"role": "system", "content": "根据查询结果，用一句简洁中文回答保安的问题。"},
            {"role": "user", "content": f"问题：{a.question}\n结果(JSON前20行)：{rows[:20]}"},
        ],
    )
    return {"answer": ans.choices[0].message.content, "sql": sql, "rows": rows[:50]}


@app.get("/api/calls")
async def recent_calls() -> dict:
    rows = await (await memory.pool()).fetch(
        "SELECT call_id, count(*) events, min(created_at) started FROM call_traces GROUP BY call_id ORDER BY started DESC LIMIT 20")
    return {"calls": [dict(r) for r in rows]}


@app.get("/api/traces/{call_id}")
async def get_call_trace(call_id: str) -> dict:
    return {"call_id": call_id, "trace": await trace.get_trace(call_id)}
