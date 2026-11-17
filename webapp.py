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
    GET    /api/record       ?kind=&id=（含 blocks 实验笔记块 / 操作步骤）
    GET    /api/form         ?kind=&id=（id=0 取空白表单）
    GET    /api/export       ?kind=&id=&fmt=pdf
    GET    /api/file         ?aid=附件id
    GET    /ketcher/         网页 Ketcher 画板（?kind=&id= 注入初始结构）
    POST   /api/save         {kind,id,fields,comps} 表单；{smiles,mol,rxn,cdxml} 画板回传
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
import packexport
import store as store_mod
from store import Store

APP = "ELN 浏览器版"
DEFAULT_PORT = 8765

# --------------------------------------------------------------- 本机固定口令
# 局域网访问口令（--token）默认不固定：命令行不传就不校验。
# 若想在**本机**固定一个口令（例如手机每次都要重输 ?t= 很烦），按下面的优先级取：
#   1) 环境变量 ELN_WEB_TOKEN
#   2) 程序目录下的 _local.json：{"web_token": "你的口令"}
# _local.json 已被 .gitignore 的 `_local.*` 排除，不会进版本库；
# 因此提交到 GitHub 的永远是「不固定口令」的版本，本机行为由这个文件决定。
LOCAL_CFG = os.path.join(paths.app_dir(), "_local.json")

# 口令记住机制：第一次带 ?t= 打开后落一个 Cookie，之后同浏览器的请求
# （包括登录 POST、手机书签、刷新）都不用再带参数，避免「登录页能开、一点登录就 403」。
TOKEN_COOKIE = "eln_tok"
TOKEN_COOKIE_TTL = 30 * 24 * 3600


def local_token() -> str:
    """读本机固定口令；没设置就返回空串（= 不校验）。"""
    tok = (os.environ.get("ELN_WEB_TOKEN") or "").strip()
    if tok:
        return tok
    try:
        with open(LOCAL_CFG, encoding="utf-8") as f:
            return str((json.load(f) or {}).get("web_token") or "").strip()
    except Exception:                                        # noqa: BLE001
        return ""


# 服务器模式的会话表：sid -> {"user": 账户名, "dir": 数据子目录, "exp": 过期时间戳}
SESSIONS: dict[str, dict] = {}
SESSION_TTL = 12 * 3600
LOGIN_FAILS: dict[str, int] = {}   # 同一 IP 连续失败次数（简单防爆破）

# Ketcher 编辑上下文：谁的哪条记录正在网页画板里编辑。
# 键 = 会话 sid（无账户模式用 "anon"），值 = {"kind":…, "id":…}。
# 打开 /ketcher/ 时写入，画板回传 /api/save 时读出。
KCTX: dict[str, dict] = {}


# ---------------------------------------------------------------- Web API 注册表
# 给网页加新功能的标准姿势（不用再碰 do_GET / do_POST 的路由 if/else）：
#
#   @api.get("/api/xxx")          # GET，参数从 self.q（parse_qs 后的 dict）拿
#   def api_xxx(self, q):
#       st = self._store()
#       try:
#           ...
#       finally:
#           st.close()
#       self._json({...})
#
#   @api.post("/api/yyy")         # POST，JSON 体用 data = self._json_body() 读
#   def api_yyy(self, q): ...
#
#   @api.delete("/api/zzz")       # DELETE
#
# 约定：返回用 self._json()，报错用 self._err(code, msg)（msg 会显示在网页弹窗里）；
# 涉及写库的接口一律先 st.is_locked() 检查定稿；会话/数据目录由 _store() 自动处理。
API_GET: dict[str, str] = {}
API_POST: dict[str, str] = {}
API_DELETE: dict[str, str] = {}


def _reg(table: dict, path: str, fn):
    table[path] = fn.__name__
    return fn


def api_get(path: str):
    return lambda fn: _reg(API_GET, path, fn)


def api_post(path: str):
    return lambda fn: _reg(API_POST, path, fn)


def api_delete(path: str):
    return lambda fn: _reg(API_DELETE, path, fn)


class _Api:
    """注册器实例：@api.get("/api/xxx") / @api.post(...) / @api.delete(...)"""
    get = staticmethod(api_get)
    post = staticmethod(api_post)
    delete = staticmethod(api_delete)


api = _Api()

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
        {"key": "purity", "label": "纯度", "type": "number"},
        # 单位 / 状态与桌面端一致：点选下拉，也允许输入自定义值（纯度与单位已互换）
        {"key": "unit", "label": "单位", "type": "text",
         "choices": ["g", "mg", "μg", "mL", "μL", "mmol", "mol"]},
        {"key": "state", "label": "状态", "type": "text",
         "choices": ["固体", "液体", "油状", "溶液"]},
        # 存放位置横跨两栏（右缘与右列输入框对齐，高度不变）
        {"key": "location", "label": "存放位置", "type": "text", "full": True},
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

    def _sid_key(self) -> str:
        """Ketcher 上下文的键：账户模式按会话隔离，匿名模式共用一个。"""
        raw = self.headers.get("Cookie", "") or ""
        m = re.search(r"eln_sid=([A-Za-z0-9_\-]+)", raw)
        return "sid:" + m.group(1) if m else "anon"

    def _store(self) -> Store:
        sess = self._session()
        if sess:
            base = self._user_dir(sess)
            return Store(os.path.join(base, "eln.db"), os.path.join(base, "attachments"))
        return Store(self.db_path)

    def _quota_guard(self) -> bool:
        """子账号硬盘配额：已满就回 507 并返回 False（管理员 / 不限额直接过）。"""
        if not self.require_auth:
            return True
        sess = self._session()
        if not sess:
            return True
        try:
            st = auth.quota_state(sess.get("user") or "")
        except Exception:                              # noqa: BLE001
            return True
        if st["over"]:
            self._err(507, f"子账号硬盘配额已用完（{st['used']:.1f} / "
                           f"{st['quota']} MB）。请联系管理员调整配额或清理记录。")
            return False
        return True

    def _redirect(self, where: str) -> None:
        rid = (parse_qs(urlparse(self.path).query).get("t") or [""])[0]
        if rid:
            where += ("&" if "?" in where else "?") + "t=" + quote(rid)
        self.send_response(302)
        self.send_header("Location", where)
        self.send_header("Content-Length", "0")
        if getattr(self, "_tok_cookie", False) and self.token:
            self.send_header("Set-Cookie",
                             f"{TOKEN_COOKIE}={self.token}; Path=/; "
                             f"Max-Age={TOKEN_COOKIE_TTL}; HttpOnly; SameSite=Lax")
        self.end_headers()

    def _ok(self, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if getattr(self, "_tok_cookie", False) and self.token:
            self.send_header("Set-Cookie",
                             f"{TOKEN_COOKIE}={self.token}; Path=/; "
                             f"Max-Age={TOKEN_COOKIE_TTL}; HttpOnly; SameSite=Lax")
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
        return self._token_ok(q)

    # ---------------- 访问口令 ----------------
    def _cookie_token(self) -> str:
        raw = self.headers.get("Cookie", "") or ""
        m = re.search(TOKEN_COOKIE + r"=([A-Za-z0-9_\-]+)", raw)
        return m.group(1) if m else ""

    def _token_ok(self, q: dict) -> bool:
        """口令校验：地址参数 → 请求头 → Cookie。第一次带对就落 Cookie。"""
        if not self.token:
            return True
        given = ((q.get("t") or [""])[0] or self.headers.get("X-ELN-Token", "")
                 or "").strip()
        if given and given == self.token:
            self._tok_cookie = True          # 交给 _ok/_redirect 顺手写 Cookie
            return True
        return self._cookie_token() == self.token

    # ---------------- 路由 ----------------
    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = u.path
        # 口令先行：配了口令后，登录页也要带令牌（只放行图标，避免浏览器刷 403）
        if path != "/favicon.ico" and not self._token_ok(q):
            self._err(403, "需要令牌：在地址后加 ?t=你的令牌（首次打开后浏览器会记住）")
            return
        if path == "/login":
            if not self.require_auth:
                self._redirect("/")
                return
            self._ok(LOGIN_PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path in ("/help", "/manual"):
            # 网页版帮助：直接渲染 MANUAL.md（与桌面 F1 帮助窗口同一份内容）
            manual_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "MANUAL.md")
            page = None
            try:
                import helpwin
                page = helpwin._HTML_HEAD + helpwin.build_html(helpwin.parse_manual())
            except Exception:                       # 无 tkinter 等环境退回纯文本
                try:
                    with open(manual_path, encoding="utf-8") as fh:
                        page = ("<meta charset='utf-8'><pre style='white-space:pre-wrap'>"
                                + fh.read().replace("<", "&lt;") + "</pre>")
                except Exception:
                    page = "<meta charset='utf-8'><p>手册文件缺失。</p>"
            self._ok(page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/logout":
            # stop=1：确认退出后停服务、（独立进程时）结束进程、页面自动关闭；
            # 不带 stop：账户模式顶栏普通退出（清会话回登录页），保持原行为。
            want_stop = (q.get("stop") or ["0"])[0] in ("1", "true")
            if self.require_auth and want_stop and self._session() is None:
                self._err(403, "需要登录会话才能停止服务")
                return
            raw = self.headers.get("Cookie", "") or ""
            m = re.search(r"eln_sid=([A-Za-z0-9_\-]+)", raw)
            if m:
                SESSIONS.pop(m.group(1), None)
            if want_stop:
                self._ok(_BYE_PAGE.encode("utf-8"), "text/html; charset=utf-8")
                threading.Timer(0.8, _quit_web).start()   # 先把页面发出去再停
                return
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", "eln_sid=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/":
            if not self._token_ok(q):
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
        if path == "/ketcher" or path.startswith("/ketcher/"):
            self._ketcher(q)
            return
        if not self._authed(q):
            self._err(403, "令牌无效")
            return
        if self.require_auth and (path.startswith("/api/") or path.startswith("/ketcher")) \
                and self._session() is None:
            self._err(401, "请先登录")
            return
        try:
            fn = API_GET.get(path)
            if fn:
                getattr(self, fn)(q)
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
            if u.path == "/api/login":          # 登录不需要会话，放最前
                self._login()
            elif self.require_auth and self._session() is None:
                self._err(401, "请先登录")
            else:
                fn = API_POST.get(u.path)
                if fn:
                    getattr(self, fn)(q)
                else:
                    self._err(404, "未知路径")
        except Exception as exc:  # noqa: BLE001
            self._err(500, f"{type(exc).__name__}: {exc}")

    @api.post("/api/save")
    def _dispatch_save(self, q: dict = None) -> None:
        """/api/save 有两种客户端：网页表单（fields）与 Ketcher 画板
        （smiles/mol/rxn/cdxml）。按载荷形状分发。"""
        try:
            data = self._json_body()
        except ValueError as exc:
            self._err(400, str(exc))
            return
        if isinstance(data, dict) and "fields" in data:
            self._save(data)
        else:
            self._ketcher_save(data if isinstance(data, dict) else {})

    @api.post("/api/cancel")
    def _cancel(self, q: dict = None) -> None:
        """Ketcher 画板「放弃」的 beacon，网页模式下无状态，直接应答。"""
        self._json({"ok": True})

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
            fn = API_DELETE.get(u.path)
            if fn:
                getattr(self, fn)(q)
            else:
                self._err(404, "未知路径")
        except Exception as exc:  # noqa: BLE001
            self._err(500, f"{type(exc).__name__}: {exc}")

    def _kind(self, q: dict) -> str:
        kind = (q.get("kind") or ["reaction"])[0]
        return "sample" if kind == "sample" else "reaction"

    @api.get("/api/list")
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

    @api.get("/api/record")
    def _record(self, q: dict) -> None:
        kind = self._kind(q)
        oid = int((q.get("id") or ["0"])[0])
        st = self._store()
        try:
            c = recexport.gather(st, kind, oid)
            if c is None:
                self._err(404, "记录不存在")
                return
            atts = [{"id": a["id"], "title": a["title"], "path": a["path"],
                     "kind": a["kind"] or "文件"}
                    for a in st.attachments(kind, oid)]
            locked = st.is_locked(kind, oid)
            blocks = self._block_view(st, kind, oid)
        finally:
            st.close()
        self._json({
            "id": oid, "kind": c["kind"], "title": c["title"],
            "created": dict(c["fields"]).get("创建时间", ""),
            "fields": [[k, v] for k, v in c["fields"]],
            "image_svg": c["image_svg"] or "",
            "comps": c["comps"], "summary": c["summary"],
            "procedure": c["procedure"], "note": c["note"],
            "blocks": blocks,
            "attachments": atts, "locked": locked,
        })

    @api.get("/api/export")
    def _export(self, q: dict) -> None:
        """网页版导出（对齐桌面「导出…」子菜单）。

        fmt: pdf | docx | md | eln | csv | sdf
        scope: record（默认，需 id）| all（md/eln 打整库包；csv/sdf 导全部药剂）
        """
        kind = self._kind(q)
        oid = int((q.get("id") or ["0"])[0])
        fmt = (q.get("fmt") or ["pdf"])[0].lower()
        scope = (q.get("scope") or ["record"])[0].lower()
        import tempfile
        fd, buf = tempfile.mkstemp(suffix=".tmp")
        os.close(fd)
        try:
            st = self._store()
            try:
                if fmt in ("pdf", "docx"):
                    # att=1：附件区「导出」开关打开 → 文末打印附件路径与文件名
                    att = (q.get("att") or ["0"])[0].lower() in ("1", "true")
                    c = recexport.gather(st, kind, oid, att_paths=att)
                    if c is None:
                        self._err(404, "记录不存在")
                        return
                    (recexport.build_pdf if fmt == "pdf"
                     else recexport.build_docx)(c, buf)
                    name = f"ELN-{kind}-{oid}.{fmt}"
                elif fmt in ("md", "eln"):
                    fn = (packexport.export_md_zip if fmt == "md"
                          else packexport.export_eln_zip)
                    n = 0
                    if scope == "record":
                        if not oid:
                            self._err(400, "先选中一条记录再导出")
                            return
                        row = st.sample(oid) if kind == "sample" else st.reaction(oid)
                        if row is None:
                            self._err(404, "记录不存在")
                            return
                        title = (row["name"] if kind == "sample"
                                 else row["title"]) or f"{kind}{oid}"
                        n = (fn(st, buf, owner_type=kind, oid=oid)
                             if fmt == "md" else
                             fn(st, buf, owner_type=kind, oid=oid, root_name=title))
                    else:
                        n = fn(st, buf)
                    if not n:
                        self._err(404, "这个范围里还没有记录")
                        return
                    name = f"ELN-{scope}-{time.strftime('%Y%m%d')}.zip"
                elif fmt == "csv":
                    rows = st.samples(None, "")
                    if not rows:
                        self._err(404, "还没有药剂记录")
                        return
                    cols = ["id", "code", "name", "cas", "formula", "mw",
                            "amount", "unit", "purity", "state", "location", "note"]
                    import csv as _csv
                    import io as _io
                    sio = _io.StringIO()
                    w = _csv.writer(sio)
                    w.writerow(["ID", "编号", "名称", "CAS", "分子式", "分子量",
                                "数量", "单位", "纯度", "状态", "位置", "备注"])
                    for r in rows:
                        w.writerow([("" if r[c] is None else r[c]) for c in cols])
                    with open(buf, "w", newline="", encoding="utf-8-sig") as fh:
                        fh.write(sio.getvalue())
                    name = "ELN-药剂表.csv"
                elif fmt == "sdf":
                    rows = [r for r in st.samples(None, "") if r["molfile"]]
                    if not rows:
                        self._err(404, "当前没有带结构的药剂")
                        return
                    with open(buf, "w", encoding="utf-8") as fh:
                        for r in rows:
                            fh.write(r["molfile"].rstrip("\n") + "\n")
                            fh.write(f">  <ID>\n{r['id']}\n\n$$$$\n")
                    name = "ELN-药剂结构.sdf"
                else:
                    self._err(400, f"不支持的导出格式：{fmt}")
                    return
            finally:
                st.close()
            with open(buf, "rb") as f:
                data = f.read()
        finally:
            try:
                os.remove(buf)
            except OSError:
                pass
        ctype = ("application/pdf" if fmt == "pdf" else
                 "application/vnd.openxmlformats-officedocument"
                 ".wordprocessingml.document" if fmt == "docx" else
                 "application/zip" if fmt in ("md", "eln") else
                 "text/csv; charset=utf-8" if fmt == "csv" else
                 "chemical/x-mdl-sdf")
        disp = f"attachment; filename*=UTF-8''{quote(name)}"
        self._ok(data, ctype, {"Content-Disposition": disp})

    @api.post("/api/import")
    def _import(self, q: dict = None) -> None:
        """网页导入 SDF / MOL：文件以 base64 放 JSON 里（{name, b64}）。

        与桌面「导入：SDF / MOL…」一致：解析出结构后逐条建药剂。
        """
        if not self._quota_guard():
            return
        try:
            data = self._json_body(24 * 1024 * 1024)
        except ValueError as exc:
            self._err(400, str(exc))
            return
        import base64 as _b64
        fname = (data.get("name") or "import.sdf").strip()
        try:
            raw = _b64.b64decode(data.get("b64") or "")
        except Exception:                              # noqa: BLE001
            self._err(400, "base64 解码失败")
            return
        if not raw:
            self._err(400, "文件内容为空")
            return
        import tempfile
        suffix = ".mol" if fname.lower().endswith(".mol") else ".sdf"
        fd, tmp = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(raw)
            rows = chem.read_sdf(tmp)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if not rows:
            self._err(400, "这个文件里没有可解析的结构")
            return
        st = self._store()
        try:
            for r in rows:
                st.add_sample(**r)
        finally:
            st.close()
        self._json({"ok": True, "count": len(rows)})

    @api.get("/api/file")
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

    @api.post("/api/attach_add")
    def _attach_add(self, q: dict = None) -> None:
        """网页上传附件：文件以 base64 放 JSON（{owner_type, owner_id, name, b64}）。

        与桌面「+ 添加」一致：文件复制进该账户的 attachments/，数据库只记路径。
        """
        if not self._quota_guard():
            return
        try:
            data = self._json_body(64 * 1024 * 1024)
        except ValueError as exc:
            self._err(400, str(exc))
            return
        owner = "sample" if data.get("owner_type") == "sample" else "reaction"
        oid = int(data.get("owner_id") or 0)
        if not oid:
            self._err(400, "缺少目标记录")
            return
        fname = os.path.basename((data.get("name") or "附件").strip()) or "附件"
        import base64 as _b64
        try:
            raw = _b64.b64decode(data.get("b64") or "")
        except Exception:                              # noqa: BLE001
            self._err(400, "base64 解码失败")
            return
        ext = os.path.splitext(fname)[1].lower().lstrip(".")
        tag = {"pdf": "PDF", "png": "图片", "jpg": "图片", "jpeg": "图片",
               "xlsx": "表格", "csv": "表格", "docx": "文档"}.get(ext, ext.upper() or "文件")
        if any(k in fname.lower() for k in ("nmr", "fid", "1h", "13c")):
            tag = "NMR"
        st = self._store()
        try:
            if st.is_locked(owner, oid):
                self._err(423, "该记录已定稿，网页端不能修改")
                return
            import tempfile
            tmpdir = tempfile.mkdtemp()
            try:
                src = os.path.join(tmpdir, fname)
                with open(src, "wb") as f:
                    f.write(raw)
                aid = st.import_attachment(owner, oid, src, tag, title=fname)
            finally:
                import shutil as _sh
                _sh.rmtree(tmpdir, ignore_errors=True)
        finally:
            st.close()
        self._json({"ok": True, "id": aid, "title": fname, "kind": tag})

    @api.delete("/api/attach_remove")
    def _attach_remove(self, q: dict) -> None:
        """移除附件登记（与桌面「移除」一致：只删记录，不动磁盘文件）。"""
        aid = int((q.get("aid") or ["0"])[0])
        st = self._store()
        try:
            row = st.one("SELECT * FROM attachments WHERE id=?", (aid,))
            if row is None:
                self._err(404, "附件不存在")
                return
            if st.is_locked(row["owner_type"], row["owner_id"]):
                self._err(423, "该记录已定稿，网页端不能修改")
                return
            st.delete_attachment(aid)
        finally:
            st.close()
        self._json({"ok": True})

    @api.post("/api/lock")
    def _lock(self, q: dict = None) -> None:
        """定稿 / 解锁（与桌面「定稿」「已定稿 · 解锁」一致）。

        载荷 {kind, id, password?}：定稿不需密码并生成一份定稿快照；
        解锁需输入当前登录账户的密码（账户模式）；非账户模式本机自用，免密。
        """
        try:
            data = self._json_body(4 * 1024)
        except ValueError as exc:
            self._err(400, str(exc))
            return
        kind = "sample" if data.get("kind") == "sample" else "reaction"
        oid = int(data.get("id") or 0)
        if not oid:
            self._err(400, "缺少目标记录")
            return
        who = (self._session() or {}).get("user", "")
        pwd = data.get("password") or ""
        st = self._store()
        try:
            if st.is_locked(kind, oid):
                if self.require_auth:
                    if not pwd:
                        self._err(400, "请输入登录密码解锁")
                        return
                    if auth.verify(who, pwd) is None:
                        self._err(401, "密码不正确，解锁失败")
                        return
                st.set_locked(kind, oid, False)
                locked_now = False
            else:
                st.set_locked(kind, oid, True)
                st.save_snapshot(kind, oid, "finalize")
                locked_now = True
        finally:
            st.close()
        self._json({"ok": True, "locked": locked_now})

    # ---------------- 写入 ----------------
    @api.get("/api/me")
    def _me(self, q: dict) -> None:
        sess = self._session()
        self._json({"user": (sess or {}).get("user", ""),
                    "role": (sess or {}).get("role", "user"),
                    "auth": self.require_auth})

    @api.get("/api/users")
    def _users(self, q: dict) -> None:
        sess = self._session()
        if not self.require_auth or (sess or {}).get("role") != "admin":
            self._err(403, "只有管理员能查看账户")
            return
        rows = []
        for u in auth._load()["users"]:
            root = not (u.get("data_dir") or "")
            st = ({"used": "", "quota": ""} if root
                  else auth.quota_state(u.get("name") or ""))
            rows.append({"name": u.get("name"), "role": u.get("role") or "user",
                         "created": u.get("created", ""),
                         "data_dir": u.get("data_dir") or "",
                         "root": root,
                         "used": st.get("used", ""),
                         "quota": st.get("quota", "")})
        self._json({"ok": True, "users": rows})

    def _require_admin(self) -> dict | None:
        sess = self._session()
        if not self.require_auth or (sess or {}).get("role") != "admin":
            self._err(403, "只有管理员能做这个操作")
            return None
        return sess

    @api.post("/api/user/create")
    def _user_create(self, q: dict = None) -> None:
        if self._require_admin() is None:
            return
        try:
            data = self._json_body(8 * 1024)
        except ValueError as exc:
            self._err(400, str(exc))
            return
        try:
            user = auth.create_sub((data.get("name") or "").strip(),
                                   data.get("password") or "",
                                   quota_mb=int(data.get("quota_mb") or 0))
        except auth.AuthError as exc:
            self._err(400, str(exc))
            return
        self._json({"ok": True, "name": user["name"],
                    "role": user.get("role", "user")})

    @api.post("/api/user/reset")
    def _user_reset(self, q: dict = None) -> None:
        """重置子账号的名称与密码（管理员账户名不可改）。"""
        if self._require_admin() is None:
            return
        try:
            data = self._json_body(8 * 1024)
        except ValueError as exc:
            self._err(400, str(exc))
            return
        name = (data.get("name") or "").strip()
        try:
            if (data.get("new_name") or "").strip() and \
                    data["new_name"].strip() != name:
                auth.rename_user(name, data["new_name"].strip())
                name = data["new_name"].strip()
            if data.get("password"):
                auth.set_password(name, data["password"])
        except auth.AuthError as exc:
            self._err(400, str(exc))
            return
        self._json({"ok": True, "name": name})

    @api.post("/api/user/quota")
    def _user_quota(self, q: dict = None) -> None:
        """给子账号分配可用硬盘空间（MB，0=不限）。"""
        if self._require_admin() is None:
            return
        try:
            data = self._json_body(8 * 1024)
        except ValueError as exc:
            self._err(400, str(exc))
            return
        name = (data.get("name") or "").strip()
        target = auth.get_user(name)
        if target is None:
            self._err(404, "没有这个账户")
            return
        if auth.is_root(target):
            self._err(400, "管理员账户不限额，也不需要配额")
            return
        try:
            auth.set_quota(name, int(data.get("quota_mb") or 0))
        except auth.AuthError as exc:
            self._err(400, str(exc))
            return
        st = auth.quota_state(name)
        self._json({"ok": True, "name": name, "used": st["used"],
                    "quota": st["quota"]})

    @api.post("/api/user/delete")
    def _user_delete(self, q: dict = None) -> None:
        """删除子账号（不动它的数据目录；管理员账户不可删）。"""
        if self._require_admin() is None:
            return
        try:
            data = self._json_body(8 * 1024)
        except ValueError as exc:
            self._err(400, str(exc))
            return
        try:
            auth.delete_user((data.get("name") or "").strip())
        except auth.AuthError as exc:
            self._err(400, str(exc))
            return
        self._json({"ok": True})

    @api.post("/api/snapshot")
    def _snapshot(self, q: dict = None) -> None:
        """给当前记录存一份「保存」快照（与桌面端状态栏「保存」一致）。

        载荷 {"kind": reaction|sample, "id": 记录id}。已定稿记录拒绝；
        id 缺省时只应答成功（前端在未选记录时仅刷新界面）。
        """
        try:
            data = self._json_body(8 * 1024)
        except ValueError as exc:
            self._err(400, str(exc))
            return
        kind = "sample" if data.get("kind") == "sample" else "reaction"
        oid = int(data.get("id") or 0)
        if not oid:
            self._json({"ok": True})
            return
        st = self._store()
        try:
            row = st.sample(oid) if kind == "sample" else st.reaction(oid)
            if not row:
                self._err(404, "记录不存在")
                return
            if st.is_locked(kind, oid):
                self._err(423, "这条记录已定稿，不能再改。\n"
                               "要修改请先在桌面端点「已定稿 · 解锁」输入密码。")
                return
            st.save_snapshot(kind, oid, "save")
        finally:
            st.close()
        self._json({"ok": True, "time": time.strftime("%H:%M")})

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

    @api.get("/api/form")
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

    def _save(self, data: dict) -> None:
        if not self._quota_guard():
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

    # ---------------- 实验笔记块（操作步骤） ----------------
    def _block_view(self, st: Store, kind: str, oid: int) -> list[dict]:
        """把笔记本块整理成网页能直接渲染 / 编辑的列表（按 position 排序）。

        每块返回 {"id", "kind", "text"（展示用纯文本）, "content"（编辑用原始字段）}；
        table 块另有 "cols" / "rows"。空文字块也返回，网页端才能补写。
        """
        out: list[dict] = []
        n_step = 0
        for b in st.blocks(kind, oid):
            try:
                c = json.loads(b["content"] or "{}")
            except (ValueError, TypeError):
                c = {}
            if not isinstance(c, dict):
                c = {}
            k = b["kind"] or "text"
            item: dict = {"id": b["id"], "kind": k, "content": c}
            if k == "step":
                n_step += 1
                head = f"步骤 {n_step} · {c.get('title') or '未命名'}"
                if c.get("done"):
                    head += "（已完成）"
                bits = [head]
                if c.get("time"):
                    bits.append(f"用时：{c['time']}")
                body = (c.get("body") or "").strip()
                if body:
                    bits.append(body)
                item["text"] = "\n".join(bits)
            elif k == "chem":
                item["text"] = " · ".join(x for x in (c.get("caption"),
                                            c.get("smiles")) if x).strip()
            elif k == "table":
                cols = [str(x) for x in (c.get("cols") or [])]
                rows = [[str(x) for x in r] for r in (c.get("rows") or [])]
                item["text"] = ""
                item["cols"] = cols
                item["rows"] = [r + [""] * (len(cols) - len(r)) for r in rows]
            elif k == "calc":
                bits = []
                if c.get("expr"):
                    bits.append(c["expr"])
                if c.get("result"):
                    bits.append(f"→ {c['result']}")
                if c.get("note"):
                    bits.append(c["note"])
                item["text"] = "\n".join(bits).strip()
            else:
                item["text"] = (c.get("md") or "").strip()
            out.append(item)
        return out

    @api.get("/api/blocks")
    def _blocks(self, q: dict) -> None:
        """笔记本块列表（网页笔记本窗口用）。"""
        kind = self._kind(q)
        oid = int((q.get("id") or ["0"])[0])
        st = self._store()
        try:
            blocks = self._block_view(st, kind, oid)
            locked = st.is_locked(kind, oid) if oid else False
        finally:
            st.close()
        self._json({"kind": kind, "id": oid, "locked": locked,
                    "blocks": blocks})

    def _json_body(self, limit: int = 2 * 1024 * 1024) -> dict:
        """读 POST JSON 体；失败抛 ValueError。"""
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > limit:
            raise ValueError("请求体为空或过大")
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("JSON 格式错误") from None

    # ---------------- 网页笔记本（与桌面版同权限面） ----------------
    _BLOCK_KINDS = {"text", "step", "chem", "table", "calc"}

    @classmethod
    def _clean_content(cls, kind: str, c) -> dict:
        """按块类型清洗内容字段，防止脏 JSON 进库（桌面端读不回来）。"""
        c = c if isinstance(c, dict) else {}

        def s(key: str, default: str = "") -> str:
            v = c.get(key)
            return default if v is None else str(v)

        if kind == "text":
            return {"md": s("md")}
        if kind == "step":
            return {"title": s("title"), "time": s("time"),
                    "body": s("body"), "done": bool(c.get("done"))}
        if kind == "chem":
            return {"smiles": s("smiles"), "caption": s("caption")}
        if kind == "table":
            cols = [str(x) for x in (c.get("cols") or []) if str(x).strip()]
            rows = [[str(x) for x in r] for r in (c.get("rows") or [])]
            return {"cols": cols, "rows": rows}
        if kind == "calc":
            return {"expr": s("expr"), "note": s("note"), "result": s("result")}
        return {}

    @api.post("/api/block/add")
    def _block_add(self, q: dict = None) -> None:
        if not self._quota_guard():
            return
        try:
            data = self._json_body(256 * 1024)
        except ValueError as exc:
            self._err(400, str(exc))
            return
        kind = "sample" if data.get("owner_type") == "sample" else "reaction"
        oid = int(data.get("owner_id") or 0)
        bkind = data.get("kind") if data.get("kind") in self._BLOCK_KINDS else "text"
        content = self._clean_content(bkind, data.get("content"))
        if not oid:
            self._err(400, "缺少目标记录")
            return
        st = self._store()
        try:
            if st.is_locked(kind, oid):
                self._err(423, "该记录已定稿，网页端不能修改")
                return
            bid = st.add_block(kind, oid, kind=bkind,
                               content=json.dumps(content, ensure_ascii=False))
        finally:
            st.close()
        self._json({"ok": True, "id": bid})

    @api.post("/api/block/save")
    def _block_save(self, q: dict = None) -> None:
        if not self._quota_guard():
            return
        try:
            data = self._json_body(256 * 1024)
        except ValueError as exc:
            self._err(400, str(exc))
            return
        bid = int(data.get("id") or 0)
        st = self._store()
        try:
            b = st.block(bid)
            if b is None:
                self._err(404, "笔记块不存在")
                return
            if st.is_locked(b["owner_type"], b["owner_id"]):
                self._err(423, "该记录已定稿，网页端不能修改")
                return
            new_kind = data.get("kind") if data.get("kind") in self._BLOCK_KINDS else None
            content = self._clean_content(new_kind or (b["kind"] or "text"),
                                          data.get("content"))
            st.update_block(bid, content=json.dumps(content, ensure_ascii=False),
                            kind=new_kind)
        finally:
            st.close()
        self._json({"ok": True, "id": bid})

    @api.post("/api/block/move")
    def _block_move(self, q: dict = None) -> None:
        if not self._quota_guard():
            return
        try:
            data = self._json_body(4 * 1024)
        except ValueError as exc:
            self._err(400, str(exc))
            return
        bid = int(data.get("id") or 0)
        delta = -1 if int(data.get("delta") or 0) < 0 else 1
        st = self._store()
        try:
            b = st.block(bid)
            if b is None:
                self._err(404, "笔记块不存在")
                return
            if st.is_locked(b["owner_type"], b["owner_id"]):
                self._err(423, "该记录已定稿，网页端不能修改")
                return
            st.move_block(bid, delta)
        finally:
            st.close()
        self._json({"ok": True})

    @api.post("/api/block/dup")
    def _block_dup(self, q: dict = None) -> None:
        if not self._quota_guard():
            return
        try:
            data = self._json_body(4 * 1024)
        except ValueError as exc:
            self._err(400, str(exc))
            return
        bid = int(data.get("id") or 0)
        st = self._store()
        try:
            b = st.block(bid)
            if b is None:
                self._err(404, "笔记块不存在")
                return
            if st.is_locked(b["owner_type"], b["owner_id"]):
                self._err(423, "该记录已定稿，网页端不能修改")
                return
            nid = st.duplicate_block(bid)
        finally:
            st.close()
        self._json({"ok": True, "id": nid})

    @api.delete("/api/block/delete")
    def _block_delete(self, q: dict) -> None:
        bid = int((q.get("id") or ["0"])[0])
        st = self._store()
        try:
            b = st.block(bid)
            if b is None:
                self._err(404, "笔记块不存在")
                return
            if st.is_locked(b["owner_type"], b["owner_id"]):
                self._err(423, "该记录已定稿，网页端不能修改")
                return
            st.delete_block(bid)
        finally:
            st.close()
        self._json({"ok": True, "id": bid})

    # ---------------- 网页 Ketcher 画板 ----------------
    def _ketcher(self, q: dict) -> None:
        """服务 Ketcher 静态页；index 注入启动数据并登记编辑目标。"""
        import ketcherwin
        if not ketcherwin.is_built():
            self._ok("Ketcher 还没构建：在程序目录双击 tools\\build_ketcher.bat"
                     " 构建一次即可".encode("utf-8"), "text/plain; charset=utf-8")
            return
        rel = urlparse(self.path).path[len("/ketcher"):].lstrip("/") or "index.html"
        root = os.path.abspath(ketcherwin.dist_dir())
        full = os.path.normpath(os.path.join(root, rel.replace("\\", "/")))
        if not full.startswith(root) or not os.path.isfile(full):
            self._err(404, "not found")
            return
        if rel != "index.html":
            ext = os.path.splitext(full)[1].lower()
            with open(full, "rb") as fh:
                self._ok(fh.read(), ketcherwin._CTYPE.get(ext,
                          "application/octet-stream"))
            return
        kind = self._kind(q)
        oid = int((q.get("id") or ["0"])[0])
        st = self._store()
        try:
            initial = self._initial_structure(st, kind, oid)
        finally:
            st.close()
        KCTX[self._sid_key()] = {"kind": kind, "id": oid}
        with open(full, encoding="utf-8") as fh:
            html = fh.read()
        boot = ketcherwin._boot_script({"initial": initial or ""})
        if "<head>" in html:
            html = html.replace("<head>", "<head>\n" + boot, 1)
        else:
            html = boot + html
        self._ok(html.encode("utf-8"), "text/html; charset=utf-8")

    def _initial_structure(self, st: Store, kind: str, oid: int) -> str:
        """给 Ketcher 的初始结构：优先最新绘制，药剂退回自身 SMILES。"""
        drawings = st.drawings(kind, oid) if oid else []
        for d in drawings:
            smi = (d["smiles"] or "").strip()
            if not smi:
                continue
            if ">>" in smi:
                rxn = self._rxn_block_from_smiles(smi)
                if rxn:
                    return rxn
            info = chem.analyze(smi)
            if "error" not in info and info.get("molfile"):
                return info["molfile"]
            return smi                      # setMolecule 也认 SMILES
        for d in drawings[:1]:              # 没有 smiles 就试桌面画板的 JSON
            try:
                from drawpad import Sketch
                sk = Sketch.from_json(d["data"] or "")
                text, _err = sk.molfile()
                if text:
                    return text
            except Exception:  # noqa: BLE001
                pass
        if kind == "sample" and oid:
            row = st.sample(oid)
            smi = (row["smiles"] or "").strip() if row else ""
            if smi:
                info = chem.analyze(smi)
                if "error" not in info and info.get("molfile"):
                    return info["molfile"]
                return smi
        return ""

    @staticmethod
    def _rxn_block_from_smiles(smi: str) -> str | None:
        """反应 SMILES → RXN 文本（给 Ketcher 预填整个反应式）。"""
        try:
            from rdkit.Chem import rdChemReactions
            r = rdChemReactions.ReactionFromSmarts(smi)
            if r is None or not (list(r.GetReactants()) or list(r.GetProducts())):
                return None
            return rdChemReactions.ReactionToRxnBlock(r)
        except Exception:  # noqa: BLE001
            return None

    def _ketcher_save(self, data: dict) -> None:
        if not self._quota_guard():
            return
        """Ketcher 画板回传 {smiles,mol,rxn,cdxml}：转成桌面画板同款
        JSON 存进 drawings（桌面端可继续编辑），药剂顺带更新结构字段。"""
        ctx = KCTX.get(self._sid_key())
        if not ctx:
            self._err(400, "没有找到编辑目标：请从记录页点「绘制」进入")
            return
        kind = ctx["kind"]
        oid = int(ctx.get("id") or 0)
        cdxml = (data.get("cdxml") or "").strip()
        rxn_t = (data.get("rxn") or "").strip()
        mol_t = (data.get("mol") or "").strip()
        smi_in = (data.get("smiles") or "").strip()
        try:
            from drawpad import Sketch
            sk = Sketch()
            if cdxml:
                from structure import parse_cdxml_full
                pd = parse_cdxml_full(text=cdxml)
                if pd.get("error"):
                    raise ValueError(pd["error"])
                if not (pd["atoms"] or pd["arrows"] or pd["labels"]):
                    raise ValueError("回传的内容是空的")
                if not sk.from_cdxml(pd, width=900, height=620):
                    raise ValueError("文件里没有可定位的对象")
                sk.mode = "scheme" if sk.arrows else "structure"
            elif rxn_t:
                from rdkit.Chem import rdChemReactions
                r = rdChemReactions.ReactionFromRxnBlock(rxn_t)
                if r is None:
                    raise ValueError("RXN 解析不了")
                sk.from_rxn(r)
            elif mol_t:
                from rdkit import Chem
                m = Chem.MolFromMolBlock(mol_t, removeHs=False, sanitize=True)
                if m is None:
                    raise ValueError("MOL 解析不了")
                sk.from_mol(m, 220, 240)
            elif smi_in and ">>" in smi_in:
                # 反应 SMILES 单独走反应通道，MolFromSmiles 吃不下
                from rdkit.Chem import rdChemReactions
                r = rdChemReactions.ReactionFromSmarts(smi_in)
                if r is None:
                    raise ValueError("反应 SMILES 解析不了")
                sk.from_rxn(r)
            elif smi_in:
                if not sk.from_smiles(smi_in, 220, 240):
                    raise ValueError("SMILES 解析不了")
            else:
                raise ValueError("Ketcher 没有回传任何结构")
        except Exception as exc:  # noqa: BLE001
            self._err(400, f"结构读不回来：{exc}")
            return
        try:
            final_smi, _err = sk.smiles()
        except Exception:  # noqa: BLE001
            final_smi = ""
        final_smi = (final_smi or smi_in or "").strip()
        title = time.strftime("网页绘制 %Y-%m-%d %H:%M")
        st = self._store()
        try:
            if not oid:
                # 顶栏「Ketcher」入口画的是全新记录：建一条兜底，绘图有地方挂
                stamp = time.strftime("%Y-%m-%d %H:%M")
                if kind == "reaction":
                    oid = st.add_reaction(title=f"网页绘制（反应）{stamp}")
                else:
                    oid = st.add_sample(name=f"网页绘制（药剂）{stamp}")
                KCTX[self._sid_key()]["id"] = oid
            if st.is_locked(kind, oid):
                self._err(423, "该记录已定稿，不能修改")
                return
            did = st.add_drawing(kind, oid, title=title, kind=sk.mode,
                                 data=sk.to_json(), smiles=final_smi)
            # 药剂：把画好的结构写回药剂本身，详情页 / 导出立刻能用
            if kind == "sample" and final_smi:
                info = chem.analyze(final_smi)
                if "error" not in info:
                    st.update_sample(oid, smiles=info["smiles"],
                                     molfile=info["molfile"],
                                     formula=info["formula"], mw=info["mw"])
        finally:
            st.close()
        self._json({"ok": True, "kind": kind, "id": oid, "drawing": did})

    @api.delete("/api/delete")
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
    if require_auth:
        try:
            auth.ensure_admin_role()   # 老库根账户补 role=admin
        except Exception:              # noqa: BLE001
            pass
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


# ---------------------------------------------------------------- 进程内开关
# 让同一个程序里多处（主窗口、帮助窗口）共用同一个服务实例，并能关掉。
_SERVER = None
_URL = ""
_STANDALONE = False          # python webapp.py 独立进程 = True，桌面内嵌 = False

_BYE_PAGE = (
    '<!doctype html><html lang="zh"><meta charset="utf-8">'
    '<title>已退出</title>'
    '<body style="font-family:system-ui,\'Microsoft YaHei\';text-align:center;'
    'padding-top:90px;color:#2a3342">'
    '<h2>已退出，网页服务已停止</h2>'
    '<p>本页可以关闭了。若没有自动关闭，请手动关掉这个标签页。</p>'
    '<script>window.close();</script>'
    '</body></html>'
)


def _quit_web() -> None:
    """退出网页：停掉服务；独立进程直接结束进程，桌面内嵌模式只停 Web 线程。"""
    global _SERVER, _URL
    stop()
    if _STANDALONE:
        os._exit(0)


def is_running() -> bool:
    return _SERVER is not None


def current_url() -> str:
    return _URL


def stop() -> bool:
    """关掉 start() 起的服务；返回是否真的关了一个。"""
    global _SERVER, _URL
    if _SERVER is None:
        return False
    try:
        _SERVER.shutdown()
        _SERVER.server_close()
    except Exception:                                        # noqa: BLE001
        pass
    finally:
        _SERVER = None
        _URL = ""
    return True


def start(host: str = "127.0.0.1", port: int = DEFAULT_PORT,
          token: str = "", db: str | None = None, open_browser: bool = True,
          require_auth: bool = False) -> str:
    """后台起服务，返回可访问 URL。已在运行则直接返回原 URL。"""
    global _SERVER, _URL
    if _SERVER is not None and _URL:
        return _URL
    srv = make_server(host, port, token, db, require_auth)
    real_port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host_part = lan_ip() if host == "0.0.0.0" else host
    url = f"http://{host_part}:{real_port}/"
    if token:
        url += f"?t={token}"
    _SERVER, _URL = srv, url
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    return url


def main() -> None:
    global _STANDALONE
    # pythonw.exe 里 sys.stdout / stderr 是 None，print 会直接抛异常
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    _STANDALONE = True
    ap = argparse.ArgumentParser(description="ELN 浏览器访问 / 小型服务器")
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 可局域网/服务器部署")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--token", default=None,
                    help="局域网访问口令；不传则读本机 _local.json 的 web_token（没有就不校验）")
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

    tok = args.token if args.token is not None else local_token()
    url = start(args.host, args.port, tok, args.db,
                open_browser=not args.no_browser, require_auth=args.auth)
    print(f"{APP} 已启动：{url}")
    if args.auth:
        print("账户模式：网页会要求登录，各账户数据互不可见")
    if args.host == "0.0.0.0":
        print(f"其他设备访问：http://{lan_ip()}:{url.rsplit(':', 1)[1]}")
        if not tok:
            print("提示：开放到局域网/公网建议再加 --token 口令，或只在可信内网使用")
    print("Ctrl+C 停止服务")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
