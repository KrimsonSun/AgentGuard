"""Vapi tools webhook —— Vapi 调用我们的工具时打这里，落到 Neon（记忆/回访/对账）。

我们的差异化全在这层：Vapi 只管电话+STT+TTS+打断，大脑(OpenRouter)和工具(这里)是我们的。
工具逻辑与媒体层解耦：换任何媒体层都可原样复用（自建 LiveKit 方案已评估后退役，见 docs/HANDOFF.md）。

启动：uvicorn vapi.tools_server:app --port 8200
Vapi 需公网可达 → 本地用隧道：cloudflared tunnel --url http://localhost:8200
把隧道 URL 填进 vapi/assistant.json 的 server.url，再跑 create_assistant.py。

⚠️ Vapi webhook 字段名随版本微调（toolCallList / toolCalls、arguments 为 str/obj），本文件已做兼容，
   首次联调时对照 https://docs.vapi.ai 校准。
"""
import json
import logging
import time

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from app import memory, trace
from app.config import settings
from app.slots import VisitSlots, normalize_phone, normalize_plate
from app.wecom import notify_guard as wecom_notify

log = logging.getLogger("vapi.tools")
app = FastAPI(title="AgentGuard Vapi Tools")

# 单次通话的工作记忆（call_id → slots）。单实例 demo 用内存即可；多实例可挪到 Redis/PG。
_SLOTS: dict[str, VisitSlots] = {}
_LOOKED_UP: set[str] = set()  # 本通是否已自动查过回访（拿到车牌/手机时后端自动查一次）
_CALL_START: dict[str, float] = {}  # call_id → 首次交互时刻（monotonic），算 25s 送达耗时


def _slots(call_id: str) -> VisitSlots:
    return _SLOTS.setdefault(call_id, VisitSlots())


# ---------- 工具实现（复用 app/ 的记忆与校验）----------
async def do_update_slots(call_id: str, args: dict) -> str:
    """记录 STT 原始输出（绝不硬拒，靠复述确认）+ 拿到车牌/手机时【后端自动查回访】。

    回访不再是模型要记得调的独立工具，而是记录时的自动行为 → 消除"先记还是先查"的顺序 bug。
    """
    s = _slots(call_id)
    notes = []
    got_id = False
    if args.get("plate"):
        p = normalize_plate(args["plate"])
        s.plate = p
        got_id = True
        if not VisitSlots.valid_plate(p):
            notes.append(f"车牌暂记「{p}」，请一字一字向司机复述确认，对方纠正就改")
    if args.get("phone"):
        ph = normalize_phone(args["phone"])
        s.phone = ph
        got_id = True
        if not VisitSlots.valid_phone(ph):
            notes.append(f"手机号暂记「{ph}」(非11位)，请向司机确认")
    for k in ("company", "purpose", "visitor_name"):
        if args.get(k):
            setattr(s, k, str(args[k]).strip())
    result = s.brief() + (" | " + "；".join(notes) if notes else "")

    # 自动回访：本通首次拿到车牌/手机 → 查历史，命中则预填并提示确认
    if got_id and call_id not in _LOOKED_UP:
        _LOOKED_UP.add(call_id)
        prof = await memory.lookup_returning_visitor(plate=s.plate or "", phone=s.phone or "")
        if prof:
            who = prof.get("visitor_name") or "老客"
            s.visitor_name = s.visitor_name or prof.get("visitor_name")
            s.phone = s.phone or prof.get("phone")
            s.company = s.company or prof.get("usual_company")
            s.purpose = s.purpose or prof.get("usual_purpose")
            # 靠手机命中但车牌听花了 → 用历史车牌，避免同一人裂成多条画像
            if prof.get("plate") and not VisitSlots.valid_plate(s.plate or ""):
                s.plate = prof["plate"]
            result += (f"\n【回访命中·已预填历史】{who}，常来{prof['usual_company']}{prof['usual_purpose']}"
                       f"，手机{prof.get('phone')}，累计{prof['visit_count']}次。"
                       f"请用称呼一句确认（如『{who}，还是来{prof['usual_company']}{prof['usual_purpose']}吧？』），"
                       f"确认就直接 finish_registration，【不要重复问已知项】。")
    return result


async def do_lookup(call_id: str, args: dict) -> str:
    prof = await memory.lookup_returning_visitor(
        plate=normalize_plate(args.get("plate", "")), phone=normalize_phone(args.get("phone", "")))
    if not prof:
        return "无历史记录，按新访客采集。"
    s = _slots(call_id)
    # 预填历史值 → 确认后可直接提交，真正做到"不重复问"（含手机号）
    s.visitor_name = prof.get("visitor_name") or s.visitor_name
    s.plate = prof.get("plate") or s.plate
    s.phone = prof.get("phone") or s.phone
    s.company = prof.get("usual_company") or s.company
    s.purpose = prof.get("usual_purpose") or s.purpose
    who = prof.get("visitor_name") or "老客"
    return (f"回访命中：{who}，车牌{prof['plate']}，手机{prof.get('phone')}，常来{prof['usual_company']}"
            f"{prof['usual_purpose']}，累计{prof['visit_count']}次。历史信息已预填好。"
            f"请用称呼一句话确认（如『{who}，还是来{prof['usual_company']}{prof['usual_purpose']}吧？』），"
            f"对方确认就直接 finish_registration，【不要重复问手机号等已知项】。")


async def do_finish(call_id: str, args: dict) -> str:
    """原子完成：登记入库 + 通知门卫 + 返回要念的结束语（一步，防幻觉收尾/少一次往返）。"""
    s = _slots(call_id)
    if not s.complete():
        return f"还不能提交，缺：{'、'.join(s.missing())}。请先补齐再调本工具。"
    elapsed = time.monotonic() - _CALL_START[call_id] if call_id in _CALL_START else None
    vid = await memory.save_visit(call_id, s, elapsed_s=elapsed)
    try:
        await wecom_notify(s, elapsed_s=elapsed)  # WECOM_WEBHOOK_URL 未配置时抛错 → demo 降级为记录
    except Exception:
        log.info("推送通道未配置，demo 记录：%s", s.brief())
    who = (s.visitor_name or "").strip()
    line = f"好的{who}！{s.plate}，{s.company}{s.purpose}，已通知门卫，请稍等放行。"
    return f"登记成功(单号{vid})。请一字不差把这句念给司机作为结束：{line}"


HANDLERS = {
    "update_slots": do_update_slots,
    "lookup_returning_visitor": do_lookup,
    "finish_registration": do_finish,
}


def _check(secret: str) -> None:
    """URL 内嵌密钥校验：保护公网暴露的 /vapi 端点（含用我方 key 的代理）。"""
    if settings.vapi_server_secret and secret != settings.vapi_server_secret:
        raise HTTPException(status_code=403, detail="forbidden")


@app.post("/vapi/{secret}/tools")
async def vapi_tools(secret: str, req: Request) -> dict:
    _check(secret)
    body = await req.json()
    msg = body.get("message", body)
    call_id = (msg.get("call") or {}).get("id") or msg.get("callId") or "vapi-unknown"
    _CALL_START.setdefault(call_id, time.monotonic())  # 首次交互 = 25s 计时起点
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


@app.post("/vapi/{secret}/events")
async def vapi_events(secret: str, req: Request) -> dict:
    """通话开始/结束事件：起始可做主叫号回访预热，结束清理工作记忆。"""
    _check(secret)
    body = await req.json()
    msg = body.get("message", body)
    call_id = (msg.get("call") or {}).get("id") or "vapi-unknown"
    if msg.get("type") in ("end-of-call-report", "hang", "call.ended"):
        _SLOTS.pop(call_id, None)
        _LOOKED_UP.discard(call_id)
        _CALL_START.pop(call_id, None)
    return {"ok": True}


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "active_calls": len(_SLOTS)}


# ---------- custom-LLM 透明代理：Vapi 的 LLM 打这里，我们注入 OpenRouter key ----------
# 好处：Vapi 无需持有 OpenRouter 凭证；所有 key 与 token 对账都留在我们后端。
# Vapi assistant 的 model.url 设为 <VAPI_TOOLS_URL>/vapi/<secret> → Vapi 调 {url}/chat/completions。
_OR = "https://openrouter.ai/api/v1/chat/completions"


@app.post("/vapi/{secret}/chat/completions")
async def proxy_llm(secret: str, req: Request):
    _check(secret)
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
