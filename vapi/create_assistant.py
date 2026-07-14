"""把 assistant.json 推到 Vapi，创建门卫助手。需 VAPI_API_KEY + VAPI_TOOLS_URL(隧道)。

用法：
  1) uvicorn vapi.tools_server:app --port 8200
  2) cloudflared tunnel --url http://localhost:8200   # 拿公网 URL，填 .env 的 VAPI_TOOLS_URL
  3) .venv/bin/python -m vapi.create_assistant
  4) 到 Vapi 控制台把助手绑定一个电话号(免费测试号即可)，拨打即 demo
"""
import json
import os
import pathlib

import httpx
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env")

API_KEY = os.getenv("VAPI_API_KEY", "")
TOOLS_URL = os.getenv("VAPI_TOOLS_URL", "").rstrip("/")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")


def build_config() -> dict:
    raw = (pathlib.Path(__file__).parent / "assistant.json").read_text()
    raw = raw.replace("<VAPI_TOOLS_URL>", TOOLS_URL)
    cfg = json.loads(raw)
    cfg.pop("_comment", None)
    # custom-llm 用 OpenRouter，需带鉴权（Vapi 通过 credential/header 传给 url）
    cfg["model"]["credentialId"] = None
    cfg["model"]["apiKey"] = OPENROUTER_KEY  # 部分版本字段名不同，联调时按 Vapi 文档校准
    return cfg


def main() -> None:
    assert API_KEY, "缺 VAPI_API_KEY（去 vapi.ai 拿，送 $10）"
    assert TOOLS_URL, "缺 VAPI_TOOLS_URL（cloudflared/ngrok 隧道到 tools_server 的公网 URL）"
    cfg = build_config()
    r = httpx.post("https://api.vapi.ai/assistant",
                   headers={"Authorization": f"Bearer {API_KEY}"}, json=cfg, timeout=30)
    if r.status_code >= 300:
        print("❌ 创建失败：", r.status_code, r.text[:500]); return
    a = r.json()
    print("✅ 助手已创建：", a.get("id"))
    print("   下一步：Vapi 控制台 → Phone Numbers → 绑定此助手到一个号 → 拨打测试")


if __name__ == "__main__":
    main()
