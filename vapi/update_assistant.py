"""把 assistant.json 的最新配置 PATCH 到【已存在】的 Vapi 助手（不新建、不动电话绑定）。

用法：.venv/bin/python -m vapi.update_assistant
需 .env 的 VAPI_API_KEY + VAPI_TOOLS_URL(线上 Fly URL) + VAPI_SERVER_SECRET。
与 create_assistant.py 的区别：那个是首次 POST 新建，这个是就地 PATCH 更新提示词/工具。
"""
import json
import os
import pathlib

import httpx
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env")

API_KEY = os.getenv("VAPI_API_KEY", "")
TOOLS_URL = os.getenv("VAPI_TOOLS_URL", "").rstrip("/")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"
NAME = "AgentGuard 语音门卫"


def build_config() -> dict:
    raw = (pathlib.Path(__file__).parent / "assistant.json").read_text()
    raw = raw.replace("<VAPI_TOOLS_URL>", TOOLS_URL).replace("<VAPI_SECRET>", os.getenv("VAPI_SERVER_SECRET", ""))
    cfg = json.loads(raw)
    cfg.pop("_comment", None)
    return cfg


def main() -> None:
    assert API_KEY, "缺 VAPI_API_KEY"
    assert TOOLS_URL, "缺 VAPI_TOOLS_URL"
    h = {"Authorization": f"Bearer {API_KEY}", "User-Agent": UA}
    lst = httpx.get("https://api.vapi.ai/assistant", headers=h, timeout=30).json()
    aid = next((a["id"] for a in lst if a.get("name") == NAME), None)
    assert aid, f"没找到助手「{NAME}」"
    cfg = build_config()
    body = {"model": cfg["model"], "firstMessage": cfg["firstMessage"]}
    r = httpx.patch(f"https://api.vapi.ai/assistant/{aid}", headers=h, json=body, timeout=30)
    if r.status_code >= 300:
        print("❌ PATCH 失败:", r.status_code, r.text[:400])
        return
    print(f"✅ 已更新助手 {aid}：提示词 + 工具描述已生效，下一通电话即用新逻辑。")


if __name__ == "__main__":
    main()
