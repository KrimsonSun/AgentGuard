"""门卫大脑离线验证 + 候选快模型对比（Day1 spike 的 LLM 半场）。

只需 OpenRouter + Neon（都已就位），不依赖语音/微信。验证：
  1) 槽位抽取是否正确、是否只追问缺失项、是否 3 轮内收齐；
  2) 真实调用 app/ 的 prompts/slots/memory/ledger（写真行到 Neon）；
  3) 各模型的 TTFT / 总延迟 / 读写 token 对比。

用法：.venv/bin/python -m experiments.brain_test
"""
import asyncio
import json
import time

from openai import AsyncOpenAI

from app import ledger, memory
from app.config import settings
from app.prompts import SYSTEM_PROMPT
from app.slots import VisitSlots

client = AsyncOpenAI(api_key=settings.openrouter_api_key, base_url=settings.openrouter_base_url)

CANDIDATES = [
    "qwen/qwen3.5-flash-02-23",
    "deepseek/deepseek-v4-flash",
    "google/gemini-2.5-flash-lite",
    "z-ai/glm-4.7-flash",
]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "update_slots",
            "description": "记录司机这句话给出的登记信息，给了几项传几项",
            "parameters": {
                "type": "object",
                "properties": {
                    "plate": {"type": "string", "description": "车牌号，如 沪A12345"},
                    "company": {"type": "string", "description": "来访单位"},
                    "phone": {"type": "string", "description": "手机号，11位"},
                    "purpose": {"type": "string", "description": "来访事由"},
                    "visitor_name": {"type": "string", "description": "对方自称，如 张师傅"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_visit",
            "description": "四项信息（车牌/单位/手机号/事由）收齐后调用，登记入库",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify_guard",
            "description": "登记入库后调用，推送访客信息给保安",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

# 模拟司机剧本：第一句给 3 项（对齐题目正例），随后补手机号
DRIVER_LINES = [
    "沪A12345，来蓝色鲸鱼送货的",
    "138 2233 4455",
]


def apply_tool(slots: VisitSlots, name: str, args: dict) -> str:
    """本地执行工具，镜像 app/agent.py 的逻辑，返回给模型的 tool 结果。"""
    if name == "update_slots":
        if args.get("plate"):
            slots.plate = args["plate"].upper().replace(" ", "")
        if args.get("phone"):
            ph = "".join(c for c in args["phone"] if c.isdigit())
            slots.phone = ph if VisitSlots.valid_phone(ph) else slots.phone
        for k in ("company", "purpose", "visitor_name"):
            if args.get(k):
                setattr(slots, k, args[k].strip())
        return slots.brief()
    if name == "save_visit":
        return "已登记，现在调 notify_guard。" if slots.complete() else f"缺：{slots.missing()}"
    if name == "notify_guard":
        return "已通知门卫（测试桩，未真发微信）。"
    return "unknown tool"


async def run_model(model: str, call_id: str) -> dict:
    slots = VisitSlots()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    turns, tool_calls_total, first_latency = 0, 0, None
    prompt_tok = compl_tok = 0
    driver_idx = 0
    assistant_texts = []

    # 先塞第一句司机话
    messages.append({"role": "user", "content": DRIVER_LINES[driver_idx]}); driver_idx += 1

    for _ in range(8):  # 安全上限
        t0 = time.monotonic()
        try:
            resp = await client.chat.completions.create(
                model=model, messages=messages, tools=TOOLS, temperature=0.3,
                extra_body={"usage": {"include": True}},  # 让 OpenRouter 回传 cost（Day2 对账用）
            )
        except Exception as exc:
            return {"model": model, "error": str(exc)[:160]}
        dt = time.monotonic() - t0
        if first_latency is None:
            first_latency = dt
        turns += 1
        if resp.usage:
            prompt_tok += resp.usage.prompt_tokens or 0
            compl_tok += resp.usage.completion_tokens or 0
            await ledger.record_llm(call_id, turns, model,
                                    resp.usage.prompt_tokens or 0, resp.usage.completion_tokens or 0)
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls_total += 1
                args = json.loads(tc.function.arguments or "{}")
                result = apply_tool(slots, tc.function.name, args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            continue  # 工具后继续让模型说话

        if msg.content:
            assistant_texts.append(msg.content.strip())
        # 模型说完话：若还缺项且有下一句司机话，喂进去；否则结束
        if not slots.complete() and driver_idx < len(DRIVER_LINES):
            messages.append({"role": "user", "content": DRIVER_LINES[driver_idx]}); driver_idx += 1
        else:
            break

    # 收齐则写真访问记录到 Neon（完整数据路径验证）
    saved_id = None
    if slots.complete():
        try:
            saved_id = await memory.save_visit(call_id, slots)
        except Exception as exc:
            saved_id = f"save失败:{exc}"[:80]

    return {
        "model": model,
        "首字延迟s": round(first_latency, 2) if first_latency else None,
        "LLM轮次": turns,
        "工具调用": tool_calls_total,
        "读token": prompt_tok,
        "写token": compl_tok,
        "收齐": slots.complete(),
        "槽位": {"车牌": slots.plate, "单位": slots.company, "手机": slots.phone, "事由": slots.purpose},
        "末句": assistant_texts[-1] if assistant_texts else "",
        "save_id": saved_id,
    }


async def main():
    print(f"OpenRouter base={settings.openrouter_base_url}\n候选模型 {len(CANDIDATES)} 个，剧本 {len(DRIVER_LINES)} 句司机话\n")
    results = []
    for i, m in enumerate(CANDIDATES):
        cid = f"braintest-{i}"
        print(f"▶ 测试 {m} ...", flush=True)
        r = await run_model(m, cid)
        results.append(r)
        if "error" in r:
            print(f"  ❌ {r['error']}\n")
        else:
            print(f"  首字{r['首字延迟s']}s 轮次{r['LLM轮次']} 工具{r['工具调用']} "
                  f"读{r['读token']}/写{r['写token']} 收齐={r['收齐']}")
            print(f"  槽位={r['槽位']}")
            print(f"  末句「{r['末句']}」  save_id={r['save_id']}\n")

    # 对账验证：从 Neon 视图读回每个 call 的读/写 token 汇总
    print("=== Neon usage_ledger 对账回读 ===")
    for i, m in enumerate(CANDIDATES):
        s = await ledger.call_summary(f"braintest-{i}")
        if s:
            print(f"  {m}: 读{s['read_tokens']} 写{s['write_tokens']} 成本${s['total_cost']}")

    # 存档
    import pathlib
    out = pathlib.Path(__file__).parent / "brain_test_result.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n结果已存 {out}")
    await (await memory.pool()).close()


if __name__ == "__main__":
    asyncio.run(main())
