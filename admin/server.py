"""AgentGuard Admin Console — 运行时配置（模型切换等）。

启动（仓库根目录）：uvicorn admin.server:app --port 8100  →  http://localhost:8100
安全边界：OPENROUTER_API_KEY 只在服务端使用，前端永远看不到；本服务只应跑在本机/内网。
"""
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import runtime_config          # 注意：包名 app 在下方被 FastAPI 实例遮蔽，导入须在此之前
from app.config import settings

app = FastAPI(title="AgentGuard Admin")
STATIC = Path(__file__).parent / "static"

# /models 结果 5 分钟缓存：345+ 个模型的列表没必要每次刷新都打 OpenRouter
_models_cache: tuple[float, list[dict]] | None = None


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/models")
async def list_models() -> dict:
    global _models_cache
    if _models_cache and time.monotonic() - _models_cache[0] < 300:
        return {"data": _models_cache[1]}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"{settings.openrouter_base_url}/models",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
        )
        r.raise_for_status()
        raw = r.json()["data"]
    slim = []
    for m in raw:
        prompt_p = float(m.get("pricing", {}).get("prompt") or 0)
        completion_p = float(m.get("pricing", {}).get("completion") or 0)
        if prompt_p < 0 or completion_p < 0:
            continue  # openrouter/* 动态路由伪模型价格为 -1，无固定单价没法对账，直接排除
        slim.append({
            "id": m["id"],
            "name": m.get("name") or m["id"],
            "context": m.get("context_length") or 0,
            "prompt_1m": round(prompt_p * 1e6, 4),
            "completion_1m": round(completion_p * 1e6, 4),
        })
    _models_cache = (time.monotonic(), slim)
    return {"data": slim}


class ModelSelection(BaseModel):
    model: str


@app.get("/api/config")
async def get_config() -> dict:
    return {
        "model": await runtime_config.get_model() or "(未选择)",
        "env_fallback": settings.openrouter_model or "(未设置)",
    }


@app.put("/api/config")
async def put_config(sel: ModelSelection) -> dict:
    try:
        await runtime_config.set("openrouter_model", sel.model)
    except Exception as exc:  # DATABASE_URL 未配置 / schema 未初始化
        raise HTTPException(503, f"写入失败（检查 DATABASE_URL 与 db/schema.sql 是否已执行）：{exc}")
    return {"ok": True, "model": sel.model}
