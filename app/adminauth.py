"""门卫台鉴权：无密码 TOTP 2FA + 服务端会话 + 限速。

- 无密码：单因子（TOTP 6 位码），靠限速堵暴力枚举（5 分钟内 5 次错误即锁）。
- 服务端会话：登录建 admin_sessions 行 + httpOnly cookie；登出/根管理员踢人 = 删行（可即时吊销）。
- 限速用进程内内存（Fly 单实例 → 够用；多实例需挪 Redis）。
"""
import base64
import secrets as _secrets
import time

import pyotp
import segno

from . import memory

_ISSUER = "AgentGuard 门卫台"
_SESSION_HOURS = 12
_RL_WINDOW = 300          # 限速窗口：5 分钟
_RL_MAX = 5               # 窗口内最多 5 次失败
_login_fails: dict[str, list[float]] = {}


def _rate_ok(username: str) -> bool:
    now = time.monotonic()
    fails = [t for t in _login_fails.get(username, []) if now - t < _RL_WINDOW]
    _login_fails[username] = fails
    return len(fails) < _RL_MAX


def _qr_data_uri(uri: str) -> str:
    return segno.make(uri, error="m").png_data_uri(scale=6, border=2)


async def root_exists() -> bool:
    return bool(await (await memory.pool()).fetchval("SELECT 1 FROM admin_users WHERE role='root' LIMIT 1"))


async def username_taken(username: str) -> bool:
    return bool(await (await memory.pool()).fetchval("SELECT 1 FROM admin_users WHERE username=$1", username))


async def create_admin(username: str, role: str = "admin") -> dict:
    """建号 + 生成 TOTP 密钥，返回 provisioning uri + 二维码 data uri（供本人扫码入验证器）。"""
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=_ISSUER)
    await (await memory.pool()).execute(
        "INSERT INTO admin_users (username, totp_secret, role) VALUES ($1,$2,$3)", username, secret, role)
    return {"username": username, "role": role, "provisioning_uri": uri, "qr": _qr_data_uri(uri)}


async def verify_and_session(username: str, code: str) -> str | None:
    """验 TOTP（含限速）。成功→建会话返回 token；失败→None；锁定→抛 PermissionError。"""
    if not _rate_ok(username):
        raise PermissionError("尝试过多，请 5 分钟后再试")
    row = await (await memory.pool()).fetchrow(
        "SELECT totp_secret FROM admin_users WHERE username=$1 AND active", username)
    ok = bool(row) and pyotp.TOTP(row["totp_secret"]).verify(code, valid_window=1)  # ±30s 容差
    if not ok:
        _login_fails.setdefault(username, []).append(time.monotonic())
        return None
    _login_fails.pop(username, None)
    token = _secrets.token_urlsafe(32)
    await (await memory.pool()).execute(
        f"INSERT INTO admin_sessions (token, username, expires_at) VALUES ($1,$2, now() + interval '{_SESSION_HOURS} hours')",
        token, username)
    return token


async def session_user(token: str | None) -> dict | None:
    if not token:
        return None
    row = await (await memory.pool()).fetchrow(
        """SELECT u.username, u.role FROM admin_sessions s JOIN admin_users u ON u.username = s.username
           WHERE s.token = $1 AND s.expires_at > now() AND u.active""", token)
    return dict(row) if row else None


async def delete_session(token: str | None) -> None:
    if token:
        await (await memory.pool()).execute("DELETE FROM admin_sessions WHERE token=$1", token)


async def list_admins() -> list[dict]:
    rows = await (await memory.pool()).fetch(
        "SELECT username, role, active, created_at FROM admin_users ORDER BY created_at")
    return [dict(r) for r in rows]


async def set_active(username: str, active: bool) -> None:
    await (await memory.pool()).execute("UPDATE admin_users SET active=$2 WHERE username=$1", username, active)


async def list_sessions() -> list[dict]:
    rows = await (await memory.pool()).fetch(
        "SELECT token, username, created_at, expires_at FROM admin_sessions WHERE expires_at > now() ORDER BY created_at DESC")
    return [{"token": r["token"], "token_head": r["token"][:10], "username": r["username"],
             "created_at": r["created_at"], "expires_at": r["expires_at"]} for r in rows]


async def revoke_session(token: str) -> None:
    await (await memory.pool()).execute("DELETE FROM admin_sessions WHERE token=$1", token)
