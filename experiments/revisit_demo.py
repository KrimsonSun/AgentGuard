"""回访真实感验证 —— 用 Neon 里真实的张师傅画像(沪B88888)跑三个场景。

复用真实代码：memory.lookup_returning_visitor + prompts.returning_* + 同一套工具。
用法：.venv/bin/python -m experiments.revisit_demo
"""
import asyncio
import json
import time
from datetime import datetime

from openai import AsyncOpenAI

from app import memory
from app.config import settings
from app.prompts import (SYSTEM_PROMPT, human_last_visit, returning_context,
                         returning_greeting)
from app.slots import VisitSlots
from experiments.brain_test import TOOLS, apply_tool

client = AsyncOpenAI(api_key=settings.openrouter_api_key, base_url=settings.openrouter_base_url)
MODEL = "google/gemini-2.5-flash-lite"
NOW = datetime(2026, 7, 13, 9, 30)

SCENARIOS = {
    "A · 完整确认": ["对对对，老地方"],
    "B · 中途改目的地": ["对，不过今天是去启明科技拜访"],
    "C · 含糊(防幻觉)": ["嗯……啥？", "哦对，还是老样子"],
}


async def run(name: str, profile: dict, driver_lines: list[str]) -> None:
    phrase = human_last_visit(profile["last_visit_at"], NOW)
    greeting = returning_greeting(profile)
    ctx = returning_context(profile, phrase)
    slots = VisitSlots()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": ctx},
        {"role": "assistant", "content": greeting},  # personalized 开场（不走 LLM）
    ]
    saved_turn, turn = None, 0
    lines_out = [f"门卫→ {greeting}"]
    for di, line in enumerate(driver_lines):
        messages.append({"role": "user", "content": line})
        lines_out.append(f"司机→ {line}")
        for _ in range(5):
            r = await client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS, temperature=0.2)
            turn += 1
            msg = r.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments or "{}")
                    if tc.function.name == "save_visit" and saved_turn is None:
                        saved_turn = di  # 记录在第几句司机话后提交
                    res = apply_tool(slots, tc.function.name, args)
                    lines_out.append(f"   ⚙ {tc.function.name}({', '.join(f'{k}={v}' for k,v in args.items()) or ''}) → {res[:50]}")
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": res})
                continue
            if msg.content:
                lines_out.append(f"门卫→ {msg.content}")
            break

    print(f"\n━━ {name} ━━")
    for l in lines_out:
        print("  " + l)
    ok_confirm = saved_turn is not None and saved_turn >= (len(driver_lines) - 1)
    print(f"  ▸ 结果：收齐={slots.complete()} 提交时机={'首句确认后' if saved_turn==0 else ('确认后' if saved_turn is not None else '未提交')} "
          f"车牌={slots.plate} 单位={slots.company} 事由={slots.purpose}")


async def main():
    profile = await memory.lookup_returning_visitor(phone="13812340001")  # 张师傅（真实种子）
    if not profile:
        print("!! 未找到张师傅画像，请先 python -m experiments.seed_demo_data"); return
    print(f"命中画像：{profile['visitor_name']} {profile['plate']} 常来{profile['usual_company']}{profile['usual_purpose']} "
          f"累计{profile['visit_count']}次，上次={human_last_visit(profile['last_visit_at'], NOW)}")
    for name, lines in SCENARIOS.items():
        await run(name, profile, lines)
    await (await memory.pool()).close()


if __name__ == "__main__":
    asyncio.run(main())
