"""播种真实感示例数据（规范化模型：visitors 按手机 + vehicles 一人多车 + visits）。

含回访演示：张先生(手机9493372442) 多次来蓝色鲸鱼科技送货、车牌 鄂AVK696。
全部 call_id 前缀 'seed-'，可用 reset_demo_data.py 清除。
用法：.venv/bin/python -m experiments.seed_demo_data
"""
import asyncio
import os
from datetime import datetime, timedelta

import asyncpg
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

BASE = datetime(2026, 7, 13, 9, 0)
# (天前, 时:分, 车牌, 单位, 手机[身份], 事由, 称呼)
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
    (1, "08:55", "沪H77778", "云图智能", "13812340008", "送货", "赵师傅"),
    (1, "13:40", "沪J99990", "启明科技", "13812340009", "面试", None),
    (0, "09:05", "沪K11112", "蓝色鲸鱼科技", "13812340010", "拜访", "陈女士"),
    # 回访演示：张先生 手机9493372442（可能换车：鄂AVK696 / 苏B证）
    (7, "10:00", "鄂AVK696", "蓝色鲸鱼科技", "9493372442", "送货", "张先生"),
    (4, "10:30", "鄂AVK696", "蓝色鲸鱼科技", "9493372442", "送货", "张先生"),
    (1, "11:00", "苏BXY123", "蓝色鲸鱼科技", "9493372442", "送货", "张先生"),
]


async def main():
    c = await asyncpg.connect(os.environ["DATABASE_URL"])
    # 清旧种子（按 call_id 与手机；cascade 删车辆）
    await c.execute("DELETE FROM visits WHERE call_id LIKE 'seed-%'")
    phones = tuple({r[4] for r in ROWS})
    await c.execute("DELETE FROM visitors WHERE phone = ANY($1::text[])", list(phones))
    for i, (days, hm, plate, comp, phone, purpose, name) in enumerate(ROWS):
        h, m = map(int, hm.split(":"))
        ts = (BASE - timedelta(days=days)).replace(hour=h, minute=m)
        vid = await c.fetchval(
            "INSERT INTO visitors(phone) VALUES($1) ON CONFLICT(phone) DO UPDATE SET phone=EXCLUDED.phone RETURNING id", phone)
        await c.execute("""INSERT INTO vehicles(visitor_id,plate,first_seen,last_seen) VALUES($1,$2,$3,$3)
                           ON CONFLICT(visitor_id,plate) DO UPDATE SET last_seen=GREATEST(vehicles.last_seen,$3)""", vid, plate, ts)
        await c.execute("""INSERT INTO visits(call_id,visitor_id,plate,company,phone,purpose,visitor_name,entered_at)
                           VALUES($1,$2,$3,$4,$5,$6,$7,$8)""", f"seed-{i}", vid, plate, comp, phone, purpose, name, ts)
    # 从 visits 重算 visitors 统计（次数/最近/常访/称呼/摘要）
    await c.execute("""
        UPDATE visitors v SET
          visit_count   = s.cnt,
          last_visit_at = s.last,
          visitor_name  = s.name,
          usual_company = s.company,
          usual_purpose = s.purpose,
          summary       = coalesce(s.name,'访客')||'，常来'||s.company||s.purpose
        FROM (
          SELECT visitor_id,
                 count(*) cnt, max(entered_at) last,
                 (array_agg(visitor_name ORDER BY entered_at DESC) FILTER (WHERE visitor_name IS NOT NULL))[1] name,
                 mode() WITHIN GROUP (ORDER BY company) company,
                 mode() WITHIN GROUP (ORDER BY purpose) purpose
          FROM visits WHERE call_id LIKE 'seed-%' GROUP BY visitor_id
        ) s WHERE v.id = s.visitor_id""")
    nv = await c.fetchval("SELECT count(*) FROM visits WHERE call_id LIKE 'seed-%'")
    npf = await c.fetchval("SELECT count(*) FROM visitors")
    nveh = await c.fetchval("SELECT count(*) FROM vehicles")
    top = await c.fetchrow("SELECT visitor_name,phone,visit_count FROM visitors ORDER BY visit_count DESC LIMIT 1")
    zhang = await c.fetchrow("""SELECT v.visitor_name,v.visit_count,
        (SELECT count(*) FROM vehicles WHERE visitor_id=v.id) cars FROM visitors v WHERE v.phone='9493372442'""")
    print(f"✅ {nv} 访问 / {npf} 访客 / {nveh} 车辆")
    print(f"   回访之王：{top['visitor_name']}({top['phone']}) {top['visit_count']}次")
    print(f"   张先生：{zhang['visit_count']}次、名下 {zhang['cars']} 辆车（演示一人多车）")
    await c.close()


if __name__ == "__main__":
    asyncio.run(main())
