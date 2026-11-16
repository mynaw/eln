# -*- coding: utf-8 -*-
"""本地账户：登录校验、机器绑定的可解密密文、30 天免登录会话。

安全模型（用之前请先看懂）
--------------------------
* **登录校验**用 PBKDF2-HMAC-SHA256 + 每账户随机盐，不可逆。
  即使有人拿到 ``accounts.json``，也不能直接算出密码。
* **找回密文**是同一份密码经 Windows DPAPI（机器级）加密的可解密副本。
  只有**创建账户的那台 Windows 机器**能解开，所以登录页点「找回」可以
  直接明文显示；换机器 / 换系统后解密失败，什么都不会显示。
  DPAPI 不可用时退回 Fernet，密钥由本机 MachineGuid 派生，语义相同。
* **会话**同样是机器绑定密文，只含用户名和到期时间，**不含密码**；
  默认 30 天。自动登录不会续期，只有手动登录成功才重新计时。
* 这是**使用层面的隔离**，不是加密数据库：每个账户一套
  ``eln.db`` + ``attachments/``，但拿到 Windows 文件访问权限的人
  仍能直接读这些文件。因此账户密码**不要复用其它系统的密码**。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime

from paths import app_dir

AUTH_FILE = os.path.join(app_dir(), "accounts.json")
SESSION_FILE = os.path.join(app_dir(), ".session")
SESSION_DAYS = 30
PBKDF2_ITER = 200_000
MIN_PASSWORD = 6
DPAPI_MACHINE = 0x04          # CRYPTPROTECT_LOCAL_MACHINE：同一台机器可解
SALT = b"eln-local-auth-v1"


class AuthError(Exception):
    """账户操作失败，消息可直接给用户看。"""


# ---------------------------------------------------------------- 机器绑定密文
def _machine_guid() -> bytes:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography") as k:
            value, _ = winreg.QueryValueEx(k, "MachineGuid")
            return str(value).encode("utf-8")
    except Exception:
        import getpass
        import platform
        return (platform.node() + "|" + getpass.getuser()).encode("utf-8")


def _fernet_key() -> bytes:
    raw = hashlib.pbkdf2_hmac("sha256", _machine_guid(), SALT, 100_000, 32)
    return base64.urlsafe_b64encode(raw)


def protect(data: bytes) -> str:
    """把机密绑到这台机器，返回带格式前缀的密文字符串。"""
    try:
        import win32crypt
        blob = win32crypt.CryptProtectData(data, None, None, None, None,
                                           DPAPI_MACHINE)
        return "dpapi:" + base64.b64encode(blob).decode("ascii")
    except Exception:
        from cryptography.fernet import Fernet
        return "fernet:" + Fernet(_fernet_key()).encrypt(data).decode("ascii")


def unprotect(text: str) -> bytes:
    """解开本机密文；不是同一台机器 / 系统时抛 AuthError。"""
    try:
        if text.startswith("dpapi:"):
            import win32crypt
            blob = base64.b64decode(text[6:])
            return win32crypt.CryptUnprotectData(
                blob, None, None, None, DPAPI_MACHINE)[1]
        if text.startswith("fernet:"):
            from cryptography.fernet import Fernet, InvalidToken
            try:
                return Fernet(_fernet_key()).decrypt(text[7:].encode("ascii"))
            except InvalidToken as exc:
                raise AuthError("这台机器不是创建该账户的机器。") from exc
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError("密文在这台机器上解不开（换过机器或重装过系统？）。") from exc
    raise AuthError("未知的密文格式。")


# ---------------------------------------------------------------- 账户文件
def _load() -> dict:
    if not os.path.isfile(AUTH_FILE):
        return {"version": 1, "users": []}
    try:
        with open(AUTH_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data.get("users"), list):
            return {"version": 1, "users": []}
        return data
    except Exception as exc:
        raise AuthError(f"账户文件读不了：{exc}") from exc


def _save(data: dict):
    os.makedirs(os.path.dirname(AUTH_FILE) or ".", exist_ok=True)
    tmp = AUTH_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, AUTH_FILE)


def has_users() -> bool:
    return bool(_load()["users"])


def list_users() -> list[str]:
    return [u["name"] for u in _load()["users"]]


def get_user(name: str) -> dict | None:
    key = (name or "").strip().casefold()
    for u in _load()["users"]:
        if u["name"].casefold() == key:
            return u
    return None


def _hash(password: str, salt: bytes, iterations: int = PBKDF2_ITER) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                               salt, iterations).hex()


def create_user(name: str, password: str, role: str = "user") -> dict:
    """建账户。第一个账户沿用项目根目录里已有的 eln.db / attachments，
    之后每个账户各用 users/<id>/ 下的一套，互不干扰。

    role: "user" | "admin"（管理员可在网页端创建账户、查看账户列表）
    """
    name = (name or "").strip()
    if not name:
        raise AuthError("账户名不能为空。")
    if any(c in name for c in '\\/:*?"<>|'):
        raise AuthError("账户名不能包含 \\ / : * ? \" < > | 这些字符。")
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"密码至少 {MIN_PASSWORD} 位。")
    data = _load()
    if any(u["name"].casefold() == name.casefold() for u in data["users"]):
        raise AuthError("这个账户名已经存在。")

    uid = "u_" + secrets.token_hex(6)
    is_first = not data["users"]
    rel_dir = "" if is_first else os.path.join("users", uid)
    salt = secrets.token_bytes(16)
    user = {
        "id": uid,
        "name": name,
        "salt": salt.hex(),
        "hash": _hash(password, salt),
        "iter": PBKDF2_ITER,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        # 可解密副本：仅供「在同一台机器上明文找回」使用
        "recover": protect(password.encode("utf-8")),
        "data_dir": rel_dir,
        "role": "admin" if role == "admin" else "user",
    }
    if rel_dir:
        os.makedirs(user_data_dir(user), exist_ok=True)
    data["users"].append(user)
    _save(data)
    return user


def is_admin(user: dict | None) -> bool:
    """老账户没有 role 字段，一律按普通用户算。"""
    return bool(user and user.get("role") == "admin")


def set_password(name: str, password: str) -> dict:
    """重设密码（本机执行）。同步更新可解密副本。"""
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"密码至少 {MIN_PASSWORD} 位。")
    data = _load()
    for u in data["users"]:
        if u.get("name", "").casefold() == (name or "").strip().casefold():
            salt = secrets.token_bytes(16)
            u["salt"] = salt.hex()
            u["hash"] = _hash(password, salt)
            u["iter"] = PBKDF2_ITER
            u["recover"] = protect(password.encode("utf-8"))
            _save(data)
            return u
    raise AuthError("没有这个账户。")


def delete_user(name: str) -> dict:
    """删除账户条目（不动它的数据目录，避免误删数据）。"""
    data = _load()
    for u in data["users"]:
        if u.get("name", "").casefold() == (name or "").strip().casefold():
            data["users"].remove(u)
            _save(data)
            return u
    raise AuthError("没有这个账户。")


def set_role(name: str, role: str = "admin") -> dict:
    """把已有账户升/降级。老账户没有 role 字段，先补上再改。"""
    data = _load()
    for u in data["users"]:
        if u.get("name", "").casefold() == (name or "").strip().casefold():
            u["role"] = "admin" if role == "admin" else "user"
            _save(data)
            return u
    raise AuthError("没有这个账户。")


def verify(name: str, password: str) -> dict | None:
    """登录校验：只比对不可逆哈希，不碰找回密文。"""
    user = get_user(name)
    if user is None:
        return None
    try:
        salt = bytes.fromhex(user["salt"])
        iterations = int(user.get("iter") or PBKDF2_ITER)
        calc = _hash(password or "", salt, iterations)
    except Exception:
        return None
    return user if hmac.compare_digest(calc, user.get("hash", "")) else None


def recover(name: str | None = None) -> dict[str, str]:
    """明文找回。只在本机能解；换机器抛 AuthError，不泄露任何东西。

    给 name 就只找这一个账户；不给就返回所有能解开的账户。
    """
    users = _load()["users"]
    if not users:
        raise AuthError("还没有创建账户。")
    if name:
        u = get_user(name)
        if u is None:
            raise AuthError(f"没有叫「{name}」的账户。")
        users = [u]
    out: dict[str, str] = {}
    for u in users:
        try:
            out[u["name"]] = unprotect(u.get("recover", "")).decode("utf-8")
        except AuthError:
            continue
    if not out:
        raise AuthError("这台机器上解不开找回密文。\n"
                        "账户文件可能来自另一台电脑、或系统重装过；"
                        "密码不会以明文跨机器保存。")
    return out


# ---------------------------------------------------------------- 会话（30 天）
def save_session(name: str, remember: bool = True):
    """手动登录成功后调用。remember=False 会清掉旧会话。"""
    if not remember:
        clear_session()
        return
    payload = {
        "user": name,
        "exp": time.time() + SESSION_DAYS * 86400,
        "nonce": secrets.token_hex(8),
    }
    blob = protect(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    with open(SESSION_FILE, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(blob)


def load_session() -> dict | None:
    """返回免登录的账户；过期 / 换机器 / 账户已删都返回 None。"""
    if not os.path.isfile(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE, encoding="utf-8") as fh:
            payload = json.loads(unprotect(fh.read().strip()).decode("utf-8"))
        if float(payload["exp"]) <= time.time():
            return None
        user = get_user(payload.get("user", ""))
        if user is None:
            return None
        return user
    except Exception:
        return None


def session_days_left() -> float:
    try:
        with open(SESSION_FILE, encoding="utf-8") as fh:
            payload = json.loads(unprotect(fh.read().strip()).decode("utf-8"))
        return max(0.0, (float(payload["exp"]) - time.time()) / 86400)
    except Exception:
        return 0.0


def clear_session():
    try:
        os.remove(SESSION_FILE)
    except OSError:
        pass


# ---------------------------------------------------------------- 数据目录
def user_data_dir(user: dict) -> str:
    """该账户的绝对数据目录。"""
    rel = user.get("data_dir") or ""
    return os.path.join(app_dir(), rel) if rel else app_dir()


def apply_user(user: dict):
    """切到这个账户的数据目录（在打开 Store 之前调用）。"""
    import store
    store.set_data_dir(user.get("data_dir") or "")
    return user_data_dir(user)
