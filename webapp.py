# -*- coding: utf-8 -*-
"""ELN 浏览器访问 —— 本地 Web 服务（仅标准库，零新依赖）。

⚠️ 2026-11-10 按用户要求**暂时停用**：桌面端入口已隐藏（gui.py 顶部 WEB_ENABLED = False）。
   代码与接口全部保留，未删任何实现；要恢复只需把 WEB_ENABLED 改回 True，
   或像下面这样手动跑一次。

用法：
    python webapp.py                 # 127.0.0.1:8765，自动开浏览器
    python webapp.py --port 9000     # 指定端口
    python webapp.py --host 0.0.0.0  # 局域网访问（手机/平板），会打印本机地址
    python webapp.py --token 1234    # 局域网时要求 ?t=1234

接口：
    GET    /                 单页界面
    GET    /api/list         ?kind=reaction|sample&q=关键词&limit=100
    GET    /api/record       ?kind=&id=
    GET    /api/form         ?kind=&id=（id=0 取空白表单）
    GET    /api/export       ?kind=&id=&fmt=pdf
    GET    /api/file         ?aid=附件id
    POST   /api/save         {kind,id,fields,comps}
    DELETE /api/delete       ?kind=&id=
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import auth
import chem
import caslookup
import paths
import recexport
import store as store_mod
from store import Store

APP = "ELN 浏览器版"
DEFAULT_PORT = 8765

# 服务器模式的会话表：sid -> {"user": 账户名, "dir": 数据子目录, "exp": 过期时间戳}
SESSIONS: dict[str, dict] = {}
SESSION_TTL = 12 * 3600
LOGIN_FAILS: dict[str, int] = {}   # 同一 IP 连续失败次数（简单防爆破）

from webui import LOGIN_PAGE, PAGE  # noqa: E402  单页界面放在 webui.py


def _meta(kind: str, row) -> str:
    if kind == "reaction":
        bits = [row["code"], row["conditions"]]
        if row["yield_pct"] is not None:
            bits.append(f"收率 {row['yield_pct']:.0f}%")
    else:
        bits = [row["code"], row["cas"], row["formula"]]
    return " · ".join(str(b) for b in bits if b)


# 网页端可编辑字段（与桌面端表结构一致，白名单方式防注入）
FIELD_DEFS = {
    "reaction": [
        {"key": "title", "label": "标题", "type": "text"},
        {"key": "code", "label": "编号", "type": "text"},
        {"key": "conditions", "label": "条件", "type": "text"},
        {"key": "yield_pct", "label": "收率 %", "type": "number"},
        {"key": "procedure", "label": "操作", "multiline": True},
        {"key": "note", "label": "备注", "multiline": True},
    ],
    "sample": [
        {"key": "name", "label": "名称", "type": "text"},
        {"key": "code", "label": "编号", "type": "text"},
        {"key": "cas", "label": "CAS 号", "type": "text"},
        {"key": "formula", "label": "分子式", "type": "text"},
        {"key": "mw", "label": "分子量", "type": "number"},
        {"key": "smiles", "label": "SMILES", "multiline": True},
        {"key": "amount", "label": "数量", "type": "number"},
        {"key": "unit", "label": "单位", "type": "text"},
        {"key": "purity", "label": "纯度", "type": "number"},
        {"key": "state", "label": "状态", "type": "text"},
        {"key": "location", "label": "存放位置", "type": "text"},
        {"key": "note", "label": "备注", "multiline": True},
    ],
}
NUM_FIELDS = {"yield_pct", "mw", "amount", "purity"}


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "ELNWeb/1.0"
    db_path: str | None = None
    token: str = ""
    require_auth: bool = False

    # ---------------- 工具 ----------------
    def _session(self) -> dict | None:
        """从 Cookie 取会话；过期或不存在返回 None。"""
        if not self.require_auth:
            return None
        raw = self.headers.get("Cookie", "") or ""
        m = re.search(r"eln_sid=([A-Za-z0-9_\-]+)", raw)
        if not m:
            return None
        sess = SESSIONS.get(m.group(1))
        if not sess:
            return None
        if sess["exp"] < time.time():
            SESSIONS.pop(m.group(1), None)
            return None
        return sess

    def _user_dir(self, sess: dict) -> str:
        rel = sess.get("dir") or ""
        return os.path.join(paths.app_dir(), rel) if rel else paths.app_dir()

    def _store(self) -> Store:
        sess = self._session()
        if sess:
            base = self._user_dir(sess)
            return Store(os.path.join(base, "eln.db"), os.path.join(base, "attachments"))
        return Store(self.db_path)

    def _redirect(self, where: str) -> None:
        rid = (parse_qs(urlparse(self.path).query).get("t") or [""])[0]
        if rid:
            where += ("&" if "?" in where else "?") + "t=" + quote(rid)
        self.send_response(302)
        self.send_header("Location", where)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _ok(self, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj) -> None:
        self._ok(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                 "application/json; charset=utf-8")

    def _err(self, code: int, msg: str) -> None:
        body = json.dumps({"error": msg}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # 安静点，只留错误
        pass

    def _authed(self, q: dict) -> bool:
        if not self.token:
            return True
        given = (q.get("t") or [""])[0] or self.headers.get("X-ELN-Token", "")
        return given == self.token

    # ---------------- 路由 ----------------
    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = u.path
        if path == "/login":
            if not self.require_auth:
                self._redirect("/")
                return
            self._ok(LOGIN_PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/logout":
            raw = self.headers.get("Cookie", "") or ""
            m = re.search(r"eln_sid=([A-Za-z0-9_\-]+)", raw)
            if m:
                SESSIONS.pop(m.group(1), None)
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", "eln_sid=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/":
            if self.token and (q.get("t") or [""])[0] != self.token:
                self._err(403, "需要令牌：在地址后加 ?t=你的令牌")
                return
            sess = self._session()
            if self.require_auth and sess is None:
                self._redirect("/login")
                return
            page = PAGE.replace("{{USER}}", (sess or {}).get("user", ""))
            self._ok(page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if not self._authed(q):
            self._err(403, "令牌无效")
            return
        if self.require_auth and path.startswith("/api/") and self._session() is None:
            self._err(401, "请先登录")
            return
        try:
            if path == "/api/list":
                self._list(q)
            elif path == "/api/record":
                self._record(q)
            elif path == "/api/export":
                self._export(q)
            elif path == "/api/file":
                self._file(q)
            elif path == "/api/form":
                self._form(q)
            elif path == "/api/me":
                self._me(q)
            elif path == "/api/users":
                self._users(q)
            else:
                self._err(404, "未知路径")
        except Exception as exc:  # noqa: BLE001
            self._err(500, f"{type(exc).__name__}: {exc}")

    # ---------------- 处理器 ----------------
    def do_POST(self):  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._authed(q):
            self._err(403, "令牌无效")
            return
        try:
            if u.path == "/api/login":
                self._login()
            elif self.require_auth and self._session() is None:
                self._err(401, "请先登录")
            elif u.path == "/api/save":
                self._save()
            elif u.path == "/api/user/create":
                self._user_create()
            else:
                self._err(404, "未知路径")
        except Exception as exc:  # noqa: BLE001
            self._err(500, f"{type(exc).__name__}: {exc}")

    def do_DELETE(self):  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._authed(q):
            self._err(403, "令牌无效")
            return
        if self.require_auth and self._session() is None:
            self._err(401, "请先登录")
            return
        try:
            if u.path == "/api/delete":
                self._delete(q)
            else:
                self._err(404, "未知路径")
        except Exception as exc:  # noqa: BLE001
            self._err(500, f"{type(exc).__name__}: {exc}")

    def _kind(self, q: dict) -> str:
        kind = (q.get("kind") or ["reaction"])[0]
        return "sample" if kind == "sample" else "reaction"

    def _list(self, q: dict) -> None:
        kind = self._kind(q)
        keyword = (q.get("q") or [""])[0].strip()
        limit = min(int((q.get("limit") or ["200"])[0] or 200), 500)
        st = self._store()
        try:
            rows = (st.reactions(keyword=keyword) if kind == "reaction"
                    else st.samples(keyword=keyword))
            items = []
            for row in rows[:limit]:
                title = row["title"] if kind == "reaction" else row["name"]
                items.append({"id": row["id"], "title": title or "(未命名)",
                              "meta": _meta(kind, row)})
        finally:
            st.close()
        self._json({"kind": kind, "count": len(items), "items": items})

    def _record(self, q: dict) -> None:
        kind = self._kind(q)
        oid = int((q.get("id") or ["0"])[0])
        st = self._store()
        try:
            c = recexport.gather(st, kind, oid)
            if c is None:
                self._err(404, "记录不存在")
                return
            atts = [{"id": a["id"], "title": a["title"], "path": a["path"]}
                    for a in st.attachments(kind, oid)]
            locked = st.is_locked(kind, oid)
        finally:
            st.close()
        self._json({
            "id": oid, "kind": c["kind"], "title": c["title"],
            "created": dict(c["fields"]).get("创建时间", ""),
            "fields": [[k, v] for k, v in c["fields"]],
            "image_svg": c["image_svg"] or "",
            "comps": c["comps"], "summary": c["summary"],
            "procedure": c["procedure"], "note": c["note"],
            "attachments": atts, "locked": locked,
        })

    def _export(self, q: dict) -> None:
        kind = self._kind(q)
        oid = int((q.get("id") or ["0"])[0])
        st = self._store()
        try:
            c = recexport.gather(st, kind, oid)
            if c is None:
                self._err(404, "记录不存在")
                return
            buf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_web_export.pdf")
            recexport.build_pdf(c, buf)
            with open(buf, "rb") as f:
                data = f.read()
            try:
                os.remove(buf)
            except OSError:
                pass
        finally:
            st.close()
        name = f"ELN-{kind}-{oid}.pdf"
        disp = f"attachment; filename*=UTF-8''{quote(name)}"
        self._ok(data, "application/pdf", {"Content-Disposition": disp})

    def _file(self, q: dict) -> None:
        aid = int((q.get("aid") or ["0"])[0])
        st = self._store()
        try:
            row = st.one("SELECT * FROM attachments WHERE id=?", (aid,))
        finally:
            st.close()
        if row is None:
            self._err(404, "附件不存在")
            return
        p = row["path"]
        if not p or not os.path.exists(p):
            self._err(404, "文件已移动或删除")
            return
        with open(p, "rb") as f:
            data = f.read()
        name = os.path.basename(p)
        ctype = "application/octet-stream"
        if name.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
            ctype = "image/" + name.rsplit(".", 1)[1].lower().replace("jpg", "jpeg")
        elif name.lower().endswith(".pdf"):
            ctype = "application/pdf"
        self._ok(data, ctype,
                 {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

    # ---------------- 写入 ----------------
    def _me(self, q: dict) -> None:
        sess = self._session()
        self._json({"user": (sess or {}).get("user", ""),
                    "role": (sess or {}).get("role", "user"),
                    "auth": self.require_auth})

    def _users(self, q: dict) -> None:
        sess = self._session()
        if not self.require_auth or (sess or {}).get("role") != "admin":
            self._err(403, "只有管理员能查看账户")
            return
        rows = [{"name": u.get("name"), "role": u.get("role") or "user",
                 "created": u.get("created", ""),
                 "data_dir": u.get("data_dir") or ""}
                for u in auth._load()["users"]]
        self._json({"ok": True, "users": rows})

    def _user_create(self) -> None:
        sess = self._session()
        if not self.require_auth or (sess or {}).get("role") != "admin":
            self._err(403, "只有管理员能创建账户")
            return
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 8 * 1024:
            self._err(413, "请求体为空或过大")
            return
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:  # noqa: BLE001
            self._err(400, "JSON 格式错误")
            return
        try:
            user = auth.create_user((data.get("name") or "").strip(),
                                    data.get("password") or "",
                                    "admin" if data.get("role") == "admin" else "user")
        except auth.AuthError as exc:
            self._err(400, str(exc))
            return
        self._json({"ok": True, "name": user["name"],
                    "role": user.get("role", "user")})

    def _login(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 8 * 1024:
            self._err(413, "请求体为空或过大")
            return
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:  # noqa: BLE001
            self._err(400, "JSON 格式错误")
            return
        name = (data.get("user") or "").strip()
        pwd = data.get("password") or ""
        ip = self.client_address[0]
        fails = LOGIN_FAILS.get(ip, 0)
        if fails >= 5:                     # 连续失败就拖慢一点，挡暴力猜
            time.sleep(2.0)
        user = auth.verify(name, pwd) if name else None
        if user is None:
            LOGIN_FAILS[ip] = fails + 1
            time.sleep(0.2)
            self._err(403, "账户名或密码不正确")
            return
        LOGIN_FAILS.pop(ip, None)
        sid = secrets.token_urlsafe(24)
        SESSIONS[sid] = {"user": name, "dir": user.get("data_dir") or "",
                         "role": user.get("role") or "user",
                         "exp": time.time() + SESSION_TTL}
        body = json.dumps({"ok": True, "user": name}, ensure_ascii=False).encode("utf-8")
        self._ok(body, "application/json; charset=utf-8",
                 {"Set-Cookie": f"eln_sid={sid}; Path=/; Max-Age={SESSION_TTL}; "
                                "HttpOnly; SameSite=Lax"})

    def _form(self, q: dict) -> None:
        """返回某条记录的可编辑字段、组成行与药剂下拉选项。"""
        kind = self._kind(q)
        oid = int((q.get("id") or ["0"])[0])
        st = self._store()
        try:
            row = None
            if oid:
                row = st.reaction(oid) if kind == "reaction" else st.sample(oid)
            samples = ([{"id": s["id"], "name": s["name"] or f"#{s['id']}"}
                        for s in st.samples()] if kind == "reaction" else [])
            comps = []
            if row is not None and kind == "reaction":
                for c in st.components(oid):
                    comps.append({"role": c["role"], "sample_id": c["sample_id"],
                                  "equivalents": c["equivalents"], "amount": c["amount"],
                                  "unit": c["unit"], "actual": c["actual"]})
        finally:
            st.close()
        if oid and row is None:
            self._err(404, "记录不存在")
            return
        fields = []
        for fd in FIELD_DEFS[kind]:
            val = None if row is None else row[fd["key"]]
            fields.append({**fd, "value": "" if val is None else val})
        self._json({"kind": kind, "id": oid, "fields": fields,
                    "comps": comps, "samples": samples})

    def _save(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 2 * 1024 * 1024:
            self._err(413, "请求体为空或过大")
            return
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:  # noqa: BLE001
            self._err(400, "JSON 格式错误")
            return
        kind = "sample" if data.get("kind") == "sample" else "reaction"
        oid = int(data.get("id") or 0)
        raw = data.get("fields") or {}

        vals = {}
        for fd in FIELD_DEFS[kind]:
            k = fd["key"]
            if k not in raw:
                continue
            v = raw[k]
            vals[k] = _num(v) if k in NUM_FIELDS else ((v or "").strip() or None)

        if kind == "reaction":
            if not vals.get("title"):
                self._err(400, "标题不能为空")
                return
        else:
            if not vals.get("name"):
                self._err(400, "名称不能为空")
                return

        st = self._store()
        try:
            if oid and st.is_locked(kind, oid):
                self._err(423, "该记录已定稿，网页端不能修改")
                return
            if kind == "sample":
                old = st.sample(oid) if oid else None
                old_smi = (old["smiles"] or "") if old else ""
                smi = (vals.get("smiles") or "").strip()
                # 只填了 CAS、没填 SMILES 时，先联网解析成 SMILES 再走结构通道
                cas = (vals.get("cas") or "").strip()
                if not smi and cas and caslookup.is_cas(cas):
                    try:
                        rsmi, _note = caslookup.resolve(cas, use_network=True)
                        if rsmi:
                            smi = rsmi
                            vals["smiles"] = rsmi
                    except Exception:
                        pass
                if smi and smi != old_smi:
                    info = chem.analyze(smi)
                    if "error" in info:
                        self._err(400, f"SMILES 解析失败：{info['error']}")
                        return
                    vals.update(smiles=info["smiles"], molfile=info["molfile"],
                                formula=info["formula"], mw=info["mw"])
                elif not smi and old_smi:
                    vals.update(smiles=None, molfile=None)
                if oid:
                    st.update_sample(oid, **vals)
                else:
                    oid = st.add_sample(**vals)
            else:
                if oid:
                    st.update_reaction(oid, **vals)
                else:
                    oid = st.add_reaction(**vals)
                rows = data.get("comps") or []
                st.run("DELETE FROM reaction_components WHERE reaction_id=?", (oid,))
                for c in rows:
                    role = (c.get("role") or "").strip()
                    sid = c.get("sample_id")
                    if not role and not sid:
                        continue
                    st.add_component(
                        oid, sample_id=int(sid) if sid else None,
                        role=role or "反应物",
                        equivalents=_num(c.get("equivalents")),
                        amount=_num(c.get("amount")),
                        unit=(c.get("unit") or "").strip() or None,
                        actual=_num(c.get("actual")))
        finally:
            st.close()
        self._json({"ok": True, "kind": kind, "id": oid})

    def _delete(self, q: dict) -> None:
        kind = self._kind(q)
        oid = int((q.get("id") or ["0"])[0])
        st = self._store()
        try:
            row = (st.reaction(oid) if kind == "reaction" else st.sample(oid)) if oid else None
            if row is None:
                self._err(404, "记录不存在")
                return
            if st.is_locked(kind, oid):
                self._err(423, "该记录已定稿，不能删除")
                return
            if kind == "reaction":
                st.delete_reaction(oid)
            else:
                st.delete_sample(oid)
        finally:
            st.close()
        self._json({"ok": True, "id": oid})


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


def make_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                token: str = "", db: str | None = None,
                require_auth: bool = False) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {
        "db_path": db or store_mod.db_path(), "token": token,
        "require_auth": require_auth})
    for p in range(port, port + 20):
        try:
            return ThreadingHTTPServer((host, p), handler)
        except OSError:
            continue
    raise OSError(f"{port}-{port + 19} 端口都被占用")


def new_token(n: int = 8) -> str:
    """生成一个短口令（局域网访问用）。"""
    return secrets.token_urlsafe(n)[:n].replace("-", "x").replace("_", "y")


def start(host: str = "127.0.0.1", port: int = DEFAULT_PORT,
          token: str = "", db: str | None = None, open_browser: bool = True,
          require_auth: bool = False) -> str:
    """后台起服务，返回可访问 URL（GUI 里调用）。"""
    srv = make_server(host, port, token, db, require_auth)
    real_port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host_part = lan_ip() if host == "0.0.0.0" else host
    url = f"http://{host_part}:{real_port}/"
    if token:
        url += f"?t={token}"
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    return url


def main() -> None:
    # pythonw.exe 里 sys.stdout / stderr 是 None，print 会直接抛异常
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    ap = argparse.ArgumentParser(description="ELN 浏览器访问 / 小型服务器")
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 可局域网/服务器部署")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--token", default="", help="局域网访问口令")
    ap.add_argument("--db", default=None, help="指定数据库文件（非账户模式）")
    ap.add_argument("--auth", action="store_true",
                    help="账户模式：网页登录，每个账户一套数据")
    ap.add_argument("--create-admin", metavar="账户名",
                    help="创建管理员账户后退出")
    ap.add_argument("--make-admin", metavar="账户名",
                    help="把已有账户提升为管理员后退出")
    ap.add_argument("--reset-password", metavar="账户名",
                    help="重设某个账户的密码（本机输入，不回显）")
    ap.add_argument("--delete-user", metavar="账户名",
                    help="删除账户条目（不动其数据目录）")
    ap.add_argument("--password", default="", help="配合 --create-admin 指定密码")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if args.make_admin:
        try:
            user = auth.set_role(args.make_admin, "admin")
        except auth.AuthError as exc:
            print(f"失败：{exc}")
            raise SystemExit(1) from exc
        print(f"已把账户「{user['name']}」提升为管理员")
        return

    if args.reset_password:
        import getpass
        pwd = getpass.getpass("新密码（至少 6 位，输入时不显示）：")
        try:
            user = auth.set_password(args.reset_password, pwd)
        except auth.AuthError as exc:
            print(f"失败：{exc}")
            raise SystemExit(1) from exc
        print(f"已重设账户「{user['name']}」的密码")
        return

    if args.delete_user:
        try:
            user = auth.delete_user(args.delete_user)
        except auth.AuthError as exc:
            print(f"失败：{exc}")
            raise SystemExit(1) from exc
        print(f"已删除账户「{user['name']}」（数据目录保留：{user.get('data_dir') or '根目录'}）")
        return

    if args.create_admin:
        import getpass
        pwd = args.password or getpass.getpass("设置管理员密码（至少 6 位）：")
        try:
            user = auth.create_user(args.create_admin, pwd, role="admin")
        except auth.AuthError as exc:
            print(f"创建失败：{exc}")
            raise SystemExit(1) from exc
        print(f"已创建管理员：{user['name']}（数据目录 {user['data_dir'] or '项目根目录'}）")
        return

    if args.auth and not auth.has_users():
        print("还没有任何账户。先创建一个管理员：")
        print("  python webapp.py --create-admin 你的名字")
        raise SystemExit(1)

    url = start(args.host, args.port, args.token, args.db,
                open_browser=not args.no_browser, require_auth=args.auth)
    print(f"{APP} 已启动：{url}")
    if args.auth:
        print("账户模式：网页会要求登录，各账户数据互不可见")
    if args.host == "0.0.0.0":
        print(f"其他设备访问：http://{lan_ip()}:{url.rsplit(':', 1)[1]}")
        if not args.token:
            print("提示：开放到局域网/公网建议再加 --token 口令，或只在可信内网使用")
    print("Ctrl+C 停止服务")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
