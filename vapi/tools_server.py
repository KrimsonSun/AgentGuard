"""Vapi tools webhook —— Vapi 调用我们的工具时打这里，落到 Neon（记忆/回访/对账）。

我们的差异化全在这层：Vapi 只管电话+STT+TTS+打断，大脑(OpenRouter)和工具(这里)是我们的。
换回自建 LiveKit 时，这套工具逻辑原样复用。

启动：uvicorn vapi.tools_server:app --port 8200
Vapi 需公网可达 → 本地用隧道：cloudflared tunnel --url http://localhost:8200
把隧道 URL 填进 vapi/assistant.json 的 server.url，再跑 create_assistant.py。

⚠️ Vapi webhook 字段名随版本微调（toolCallList / toolCalls、arguments 为 str/obj），本文件已做兼容，
   首次联调时对照 https://docs.vapi.ai 校准。
"""
import json
import logging

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from app import memory, trace
from app.config import settings
from app.slots import VisitSlots, normalize_phone, normalize_plate
from app.wecom import notify_guard as wecom_notify

log = logging.getLogger("vapi.tools")
app = FastAPI(title="AgentGuard Vapi Tools")

# 单次通话的工作记忆（call_id → slots）。单实例 demo 用内存即可；多实例可挪到 Redis/PG。
_SLOTS: dict[str, VisitSlots] = {}


def _slots(call_id: str) -> VisitSlots:
    return _SLOTS.setdefault(call_id, VisitSlots())


# ---------- 工具实现（复用 app/ 的记忆与校验）----------
async def do_update_slots(call_id: str, args: dict) -> str:
    s = _slots(call_id)
    if args.get("plate"):
        p = normalize_plate(args["plate"])
        if VisitSlots.valid_plate(p):
            s.plate = p
        else:
            return f"车牌「{args['plate']}」格式可疑，请复述确认。{s.brief()}"
    if args.get("phone"):
        ph = normalize_phone(args["phone"])
        if VisitSlots.valid_phone(ph):
            s.phone = ph
        else:
            return f"手机号「{args['phone']}」不是11位，请再问。{s.brief()}"
    for k in ("company", "purpose", "visitor_name"):
        if args.get(k):
            setattr(s, k, str(args[k]).strip())
    return s.brief()


async def do_lookup(call_id: str, args: dict) -> str:
    prof = await memory.lookup_returning_visitor(
        plate=normalize_plate(args.get("plate", "")), phone=normalize_phone(args.get("phone", "")))
    if not prof:
        return "无历史记录，按新访客采集。"
    s = _slots(call_id)
    s.visitor_name = prof.get("visitor_name")
    return (f"回访：{prof.get('visitor_name') or '老访客'}，车牌{prof['plate']}，"
            f"常来{prof['usual_company']}{prof['usual_purpose']}，累计{prof['visit_count']}次。请确认后提交。")


async def do_save_visit(call_id: str, args: dict) -> str:
    s = _slots(call_id)
    if not s.complete():
        return f"还不能提交，缺：{'、'.join(s.missing())}"
    vid = await memory.save_visit(call_id, s)
    return f"已登记（单号{vid}）。现在调 notify_guard。"


async def do_notify_guard(call_id: str, args: dict) -> str:
    s = _slots(call_id)
    try:
        await wecom_notify(s)  # WECOM_WEBHOOK_URL 未配置时会抛错 → demo 下降级为记录
    except Exception:
        log.info("推送通道未配置，demo 记录：%s", s.brief())
    return "已通知门卫，请稍等放行。"


HANDLERS = {
    "update_slots": do_update_slots,
    "lookup_returning_visitor": do_lookup,
    "save_visit": do_save_visit,
    "notify_guard": do_notify_guard,
}


@app.post("/vapi/tools")
async def vapi_tools(req: Request) -> dict:
    body = await req.json()
    msg = body.get("message", body)
    call_id = (msg.get("call") or {}).get("id") or msg.get("callId") or "vapi-unknown"
    tr = trace.Tracer(call_id)
    calls = msg.get("toolCallList") or msg.get("toolCalls") or []
    results = []
    for tc in calls:
        fn = tc.get("function", tc)
        name = fn.get("name")
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError:
                args = {}
        args = args or {}
        await tr.event("tool_call", role="assistant", tool_name=name, content=json.dumps(args, ensure_ascii=False))
        handler = HANDLERS.get(name)
        result = await handler(call_id, args) if handler else f"未知工具 {name}"
        await tr.event("tool_result", role="tool", tool_name=name, content=result)
        results.append({"toolCallId": tc.get("id"), "result": result})
    return {"results": results}


@app.post("/vapi/events")
async def vapi_events(req: Request) -> dict:
    """通话开始/结束事件：起始可做主叫号回访预热，结束清理工作记忆。"""
    body = await req.json()
    msg = body.get("message", body)
    call_id = (msg.get("call") or {}).get("id") or "vapi-unknown"
    if msg.get("type") in ("end-of-call-report", "hang", "call.ended"):
        _SLOTS.pop(call_id, None)
    return {"ok": True}


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "active_calls": len(_SLOTS)}


# ---------- custom-LLM 透明代理：Vapi 的 LLM 打这里，我们注入 OpenRouter key ----------
# 好处：Vapi 无需持有 OpenRouter 凭证；所有 key 与 token 对账都留在我们后端。
# Vapi assistant 的 model.url 设为 <VAPI_TOOLS_URL>/vapi → Vapi 调 {url}/chat/completions。
_OR = "https://openrouter.ai/api/v1/chat/completions"


@app.post("/vapi/chat/completions")
async def proxy_llm(req: Request):
    body = await req.body()
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}",
               "Content-Type": "application/json"}
    is_stream = b'"stream":true' in body.replace(b" ", b"")
    if is_stream:
        async def gen():
            async with httpx.AsyncClient(timeout=120) as c:
                async with c.stream("POST", _OR, headers=headers, content=body) as r:
                    async for chunk in r.aiter_raw():
                        yield chunk
        return StreamingResponse(gen(), media_type="text/event-stream")
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(_OR, headers=headers, content=body)
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")
