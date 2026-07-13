"""跑一通真实通话并全程 trace，验证完整日志系统（Neon call_traces + JSONL）。

镜像真实 agent 流程：固定开场白 → 逐句司机话 → LLM 推理/工具循环。
跑完从 Neon 回读 trace 打印时间线。用法：.venv/bin/python -m experiments.trace_demo
"""
import asyncio
import json
import time

from openai import AsyncOpenAI

from app import ledger, memory, trace
from app.config import settings
from app.prompts import GREETING, SYSTEM_PROMPT
from app.slots import VisitSlots
from experiments.brain_test import TOOLS, apply_tool

CALL_ID = "tracedemo-1"
DRIVER_LINES = ["喂，沪A66668，来蓝色鲸鱼面试的", "我叫小林，手机13800008888"]

client = AsyncOpenAI(api_key=settings.openrouter_api_key, base_url=settings.openrouter_base_url)


async def main():
    model = "google/gemini-2.5-flash-lite"
    tr = trace.Tracer(CALL_ID)
    slots = VisitSlots()
    # 清掉上次同 call_id 的 trace/visit，保证可重复
    pool = await memory.pool()
    await pool.execute("DELETE FROM call_traces WHERE call_id=$1", CALL_ID)
    await pool.execute("DELETE FROM usage_ledger WHERE call_id=$1", CALL_ID)
    await pool.execute("DELETE FROM visits WHERE call_id=$1", CALL_ID)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    await tr.event("greeting", role="assistant", content=GREETING, model=model)  # 固定开场白，无 LLM

    turn = 0
    for line in DRIVER_LINES:
        messages.append({"role": "user", "content": line})
        await tr.event("user_utterance", role="user", content=line, turn_index=turn)
        for _ in range(6):
            t0 = time.monotonic()
            resp = await client.chat.completions.create(
                model=model, messages=messages, tools=TOOLS, temperature=0.3,
            )
            dt_ms = int((time.monotonic() - t0) * 1000)
            turn += 1
            msg = resp.choices[0].message
            if resp.usage:
                await ledger.record_llm(CALL_ID, turn, model,
                                        resp.usage.prompt_tokens or 0, resp.usage.completion_tokens or 0)
            await tr.event("llm_message", role="assistant",
                           content=msg.content or "(仅工具调用)", turn_index=turn,
                           latency_ms=dt_ms, model=model)
            messages.append(msg.model_dump(exclude_none=True))
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments or "{}")
                    await tr.event("tool_call", role="assistant", tool_name=tc.function.name,
                                   content=json.dumps(args, ensure_ascii=False), turn_index=turn)
                    result = apply_tool(slots, tc.function.name, args)
                    await tr.event("tool_result", role="tool", tool_name=tc.function.name,
                                   content=result, turn_index=turn)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                continue
            break  # 说完一句，等下一句司机话
    if slots.complete():
        vid = await memory.save_visit(CALL_ID, slots)
        await tr.event("hangup", content=f"登记成功 visit_id={vid}，槽位={slots.brief()}")

    # 回读 trace 打印时间线
    print(f"\n=== 通话 {CALL_ID} 完整 trace（从 Neon 回读）===")
    rows = await trace.get_trace(CALL_ID)
    for r in rows:
        lat = f" {r['latency_ms']}ms" if r["latency_ms"] else ""
        tool = f" [{r['tool_name']}]" if r["tool_name"] else ""
        content = (r["content"] or "").replace("\n", " ")[:70]
        print(f"  t{r['turn_index'] if r['turn_index'] is not None else '-'} {r['event_type']:<14}{tool}{lat}  {content}")
    print(f"\n共 {len(rows)} 条 trace 事件；JSONL: logs/traces/{CALL_ID}.jsonl")
    s = await ledger.call_summary(CALL_ID)
    if s:
        print(f"对账：读{s['read_tokens']} 写{s['write_tokens']} token")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
