"""企业微信群机器人推送（docs/HANDOFF.md §决策4）。

webhook 地址敏感需保密；官方限流 20 条/分钟，本场景远用不满。
"""
from datetime import datetime

import httpx

from .config import settings
from .slots import VisitSlots


async def notify_guard(s: VisitSlots, elapsed_s: float | None = None) -> bool:
    """推送结构化访客卡片；返回是否成功。elapsed_s 用于 25s 指标展示。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "**🚗 访客登记 · 待放行**",
        f"> 车牌：<font color=\"info\">{s.plate}</font>",
        f"> 单位：{s.company}",
        f"> 事由：{s.purpose}",
        f"> 手机：{s.phone}",
        f"> 入场：{now}",
    ]
    if s.visitor_name:
        lines.insert(2, f"> 访客：{s.visitor_name}")
    if elapsed_s is not None:
        lines.append(f"> ⏱ 接通→送达 {elapsed_s:.1f}s")
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.post(
            settings.wecom_webhook_url,
            json={"msgtype": "markdown", "markdown": {"content": "\n".join(lines)}},
        )
        r.raise_for_status()
        return r.json().get("errcode") == 0
