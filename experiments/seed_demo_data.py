"""播种真实感示例访客数据（供 console 搜索/统计/门卫查询 演示与测试）。

全部标记 call_id 前缀 'seed-'，可用 reset_demo_data.py 清除。
覆盖：多访客、跨一周、含回访者（张师傅多次来蓝色鲸鱼送货）、峰值时段。
用法：.venv/bin/python -m experiments.seed_demo_data
"""
import asyncio
import os
from datetime import datetime, timedelta

import asyncpg
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# (天前, 时:分, 车牌, 单位, 手机, 事由, 称呼)
BASE = datetime(2026, 7, 13, 9, 0)
ROWS = [
    (6, "09:12", "沪B88888", "蓝色鲸鱼科技", "13812340001", "送货", "张师傅"),
    (5, "14:30", "沪A12345", "蓝色鲸鱼科技", "13812340002", "面试", None),
    (5, "10:05", "沪B88888", "蓝色鲸鱼科技", "13812340001", "送货", "张师傅"),
    (4, "09:40", "沪C66666", "云图智能", "13812340003", "拜访", "李经理"),
    (4, "16:20", "沪D22221", "蓝色鲸鱼科技", "13812340004", "送货", None),
    (3, "09:18", "沪B88888", "蓝色鲸鱼科技", "13812340001", "送货", "张师傅"),
    (3, "11:50", "沪E33334", "云图智能", "13812340005", "面试", None),
    (3, "14:10", "沪F44445", "启明科技", "13812340006", "拜访", "王总"),
    (2, "09:30", "沪B88888", "蓝色鲸鱼科技", "13812340001", "送货", "张师傅"),
    (2, "10:15", "沪G55556", "启明科技", "13812340007", "送货", None),
    (2, "17:05", "沪A12345", "蓝色鲸鱼科技", "13812340002", "拜访", None),
    (1, "08:55", "沪H77778", "云图智能", "13812340008", "送货", "赵师傅"),
    (1, "09:22", "沪B88888", "蓝色鲸鱼科技", "13812340001", "送货", "张师傅"),
    (1, "13:40", "沪J99990", "启明科技", "13812340009", "面试", None),
    (0, "09:05", "沪K11112", "蓝色鲸鱼科技", "13812340010", "拜访", "陈女士"),
    (0, "09:35", "沪B88888", "蓝色鲸鱼科技", "13812340001", "送货", "张师傅"),
]


async def main():
    c = await asyncpg.connect(os.environ["DATABASE_URL"])
    await c.execute("DELETE FROM visits WHERE call_id LIKE 'seed-%'")
    for i, (days_ago, hm, plate, comp, phone, purpose, name) in enumerate(ROWS):
        h, m = map(int, hm.split(":"))
        ts = (BASE - timedelta(days=days_ago)).replace(hour=h, minute=m)
        await c.execute(
            """INSERT INTO visits (call_id, plate, company, phone, purpose, visitor_name, entered_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7)""",
            f"seed-{i}", plate, comp, phone, purpose, name, ts,
        )
    # 从 visits 重建 visitor_profiles（真实聚合）
    await c.execute("DELETE FROM visitor_profiles WHERE plate IN (SELECT plate FROM visits WHERE call_id LIKE 'seed-%')")
    await c.execute("""
        INSERT INTO visitor_profiles (plate, phone, visitor_name, usual_company, usual_purpose, visit_count, last_visit_at, summary)
        SELECT plate,
               (array_agg(phone ORDER BY entered_at DESC))[1],
               (array_agg(visitor_name ORDER BY entered_at DESC) FILTER (WHERE visitor_name IS NOT NULL))[1],
               mode() WITHIN GROUP (ORDER BY company),
               mode() WITHIN GROUP (ORDER BY purpose),
               count(*), max(entered_at),
               coalesce((array_agg(visitor_name ORDER BY entered_at DESC) FILTER (WHERE visitor_name IS NOT NULL))[1], '访客')
                 || '，常来' || mode() WITHIN GROUP (ORDER BY company) || mode() WITHIN GROUP (ORDER BY purpose)
        FROM visits WHERE call_id LIKE 'seed-%'
        GROUP BY plate
        ON CONFLICT (plate) DO UPDATE SET
          visit_count=EXCLUDED.visit_count, last_visit_at=EXCLUDED.last_visit_at,
          usual_company=EXCLUDED.usual_company, usual_purpose=EXCLUDED.usual_purpose, summary=EXCLUDED.summary
    """)
    nv = await c.fetchval("SELECT count(*) FROM visits WHERE call_id LIKE 'seed-%'")
    npf = await c.fetchval("SELECT count(*) FROM visitor_profiles")
    top = await c.fetchrow("SELECT visitor_name, plate, visit_count FROM visitor_profiles ORDER BY visit_count DESC LIMIT 1")
    print(f"✅ 播种 {nv} 条访问、{npf} 个画像；回访之王：{top['visitor_name']}（{top['plate']}）来了 {top['visit_count']} 次")
    await c.close()


if __name__ == "__main__":
    asyncio.run(main())
