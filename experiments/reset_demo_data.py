"""清除所有演示/测试数据（seed-* / tracedemo-* / braintest-*），还原干净库。

用法：.venv/bin/python -m experiments.reset_demo_data
"""
import asyncio
import os

import asyncpg
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
PREFIXES = ("seed-%", "tracedemo-%", "braintest-%")


async def main():
    c = await asyncpg.connect(os.environ["DATABASE_URL"])
    for tbl in ("call_traces", "usage_ledger", "visits"):
        for pfx in PREFIXES:
            await c.execute(f"DELETE FROM {tbl} WHERE call_id LIKE $1", pfx)
    # 画像按是否还有对应 visits 判断（简单起见：清掉不再有 visits 的画像）
    await c.execute("DELETE FROM visitor_profiles p WHERE NOT EXISTS (SELECT 1 FROM visits v WHERE v.plate=p.plate)")
    for tbl in ("visits", "visitor_profiles", "usage_ledger", "call_traces"):
        n = await c.fetchval(f"SELECT count(*) FROM {tbl}")
        print(f"  {tbl}: {n} 行")
    await c.close()
    print("✅ 演示数据已清除")


if __name__ == "__main__":
    asyncio.run(main())
