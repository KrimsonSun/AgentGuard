"""模型对比：门卫工具调用可靠率 + 首字延迟 + 回话自然度（离线，多次跑测可靠性）。

用真 prompt/工具/后端(写 Neon，测后清理)。自适应司机：模型问确认就答"对"，否则给下一条信息。
注意：离线是非流式，与 Vapi 流式路径可能有差异，仅作模型间相对比较。
用法：.venv/bin/python -m experiments.model_eval
"""
import asyncio, json, os, time
import asyncpg
from openai import AsyncOpenAI
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from vapi.tools_server import HANDLERS, _SLOTS

MODELS = ["google/gemini-3.1-flash-lite", "openai/gpt-4o-mini"]
RUNS = 3
acfg = json.load(open(os.path.join(os.path.dirname(__file__), "..", "vapi", "assistant.json")))
SYS = acfg["model"]["messages"][0]["content"]
TOOLS = [{"type": "function", "function": t["function"]} for t in acfg["model"]["tools"]]
client = AsyncOpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url="https://openrouter.ai/api/v1")

SCEN = {
    "新访客(全给)": {"lines": ["我姓王，沪B22345，来云图智能面试", "13800001111"],
                   "need": {"update_slots", "finish_registration"}},
    "回访(鄂AVK696)": {"lines": ["鄂AVK696"],
                     "need": {"lookup_returning_visitor", "finish_registration"}},
}
CONFIRM = ("对吗", "对吧", "是吗", "确认", "吧？", "吧?")


async def one_run(model, scen, cid):
    for t in _SLOTS: pass
    _SLOTS.pop(cid, None)
    lines = SCEN[scen]["lines"]; idx = 0; called = []; ft = None
    msgs = [{"role": "system", "content": SYS}, {"role": "assistant", "content": acfg["firstMessage"]}]
    msgs.append({"role": "user", "content": lines[idx]}); idx += 1
    for _ in range(10):
        t0 = time.monotonic()
        try:
            r = await client.chat.completions.create(model=model, messages=msgs, tools=TOOLS, temperature=0.3)
        except Exception as e:
            return {"ok": False, "err": str(e)[:60], "called": called, "ft": ft}
        if ft is None: ft = time.monotonic() - t0
        m = r.choices[0].message; msgs.append(m.model_dump(exclude_none=True))
        if m.tool_calls:
            for tc in m.tool_calls:
                called.append(tc.function.name)
                res = await HANDLERS[tc.function.name](cid, json.loads(tc.function.arguments or "{}"))
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": res})
                if tc.function.name == "finish_registration": return {"ok": True, "called": called, "ft": ft}
            continue
        txt = m.content or ""
        if any(k in txt for k in CONFIRM): nxt = "对"
        elif idx < len(lines): nxt = lines[idx]; idx += 1
        else: nxt = "对，谢谢"
        msgs.append({"role": "user", "content": nxt})
    return {"ok": False, "called": called, "ft": ft}


async def main():
    c = await asyncpg.connect(os.environ["DATABASE_URL"])
    print(f"{'模型':<30}{'场景':<16}{'工具可靠':>10}{'均首字':>9}")
    for model in MODELS:
        for scen, spec in SCEN.items():
            succ = 0; fts = []
            for run in range(RUNS):
                cid = f"eval-{run}"
                res = await one_run(model, scen, cid)
                got = set(res["called"])
                if res["ok"] and spec["need"].issubset(got): succ += 1
                if res["ft"]: fts.append(res["ft"])
                for t in ("call_traces", "usage_ledger", "visits"): await c.execute(f"DELETE FROM {t} WHERE call_id=$1", cid)
            await c.execute("DELETE FROM visitor_profiles WHERE plate IN ('沪B22345')")
            avg = f"{sum(fts)/len(fts):.2f}s" if fts else "-"
            print(f"{model:<30}{scen:<16}{f'{succ}/{RUNS}':>10}{avg:>9}")
    await c.close()


if __name__ == "__main__":
    asyncio.run(main())
