"""完整通话 trace —— 可回放的推理/行为日志。

双写：Neon `call_traces`（可查询/统计）+ 本地 JSONL（`logs/traces/{call_id}.jsonl`，可 grep/回放）。
与 `usage_ledger`（计费）分离：trace 关注"它想了什么、调了什么、每步多久"。
"""
import json
import pathlib
import time
from datetime import datetime, timezone

from . import memory

LOGDIR = pathlib.Path(__file__).resolve().parent.parent / "logs" / "traces"


class Tracer:
    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        LOGDIR.mkdir(parents=True, exist_ok=True)
        self._file = LOGDIR / f"{call_id}.jsonl"

    async def event(
        self,
        event_type: str,
        *,
        role: str | None = None,
        content: str | None = None,
        tool_name: str | None = None,
        turn_index: int | None = None,
        latency_ms: int | None = None,
        model: str | None = None,
    ) -> None:
        content = content if content is None else str(content)[:4000]
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "call_id": self.call_id,
            "turn": turn_index,
            "event": event_type,
            "role": role,
            "content": content,
            "tool": tool_name,
            "latency_ms": latency_ms,
            "model": model,
        }
        # 本地 JSONL（永不因 DB 抖动丢日志）
        try:
            with self._file.open("a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass
        # Neon（可查询）
        try:
            await (await memory.pool()).execute(
                """INSERT INTO call_traces
                     (call_id, turn_index, event_type, role, content, tool_name, latency_ms, model)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                self.call_id, turn_index, event_type, role, content, tool_name, latency_ms, model,
            )
        except Exception:
            pass  # trace 不应阻断通话

    @staticmethod
    def timer() -> float:
        return time.monotonic()


async def get_trace(call_id: str) -> list[dict]:
    rows = await (await memory.pool()).fetch(
        """SELECT turn_index, event_type, role, content, tool_name, latency_ms, model, created_at
           FROM call_traces WHERE call_id=$1 ORDER BY id""",
        call_id,
    )
    return [dict(r) for r in rows]
