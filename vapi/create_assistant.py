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
# 浏览器 UA：绕过 Vapi 前置 Cloudflare 对 python UA 的 1010 拦截
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"


def build_config() -> dict:
    raw = (pathlib.Path(__file__).parent / "assistant.json").read_text()
    raw = raw.replace("<VAPI_TOOLS_URL>", TOOLS_URL)
    raw = raw.replace("<VAPI_SECRET>", os.getenv("VAPI_SERVER_SECRET", ""))
    cfg = json.loads(raw)
    cfg.pop("_comment", None)
    # 无需在 Vapi 存 OpenRouter 凭证：model.url 指向我们后端的 /vapi 透明代理，
    # 代理注入 OpenRouter key（见 tools_server.py /vapi/chat/completions）。
    return cfg


def main() -> None:
    assert API_KEY, "缺 VAPI_API_KEY（去 vapi.ai 拿，送 $10）"
    assert TOOLS_URL, "缺 VAPI_TOOLS_URL（cloudflared/ngrok 隧道到 tools_server 的公网 URL）"
    cfg = build_config()
    r = httpx.post("https://api.vapi.ai/assistant",
                   headers={"Authorization": f"Bearer {API_KEY}", "User-Agent": UA}, json=cfg, timeout=30)
    if r.status_code >= 300:
        print("❌ 创建失败：", r.status_code, r.text[:500]); return
    a = r.json()
    print("✅ 助手已创建：", a.get("id"))
    print("   下一步：Vapi 控制台 → Phone Numbers → 绑定此助手到一个号 → 拨打测试")


if __name__ == "__main__":
    main()
