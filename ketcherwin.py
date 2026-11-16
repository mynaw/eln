# -*- coding: utf-8 -*-
"""Ketcher 编辑器：本地起一个静态服务，用 Edge 应用窗口打开，改完回写画板。

为什么是这个形态
----------------
Tk 里没有能跑 React 的浏览器控件（``tkinterweb`` 是 TkHtml，跑不了现代 JS；
``pywebview`` 要额外装 pythonnet）。本机有 Edge 与 WebView2 运行时，用
``msedge --app=URL`` 开一个**无地址栏**的窗口，外观与独立对话框一致，
不引入任何新依赖，也不需要联网。

数据流
------
::

    画板 --(cdxml / mol / rxn)--> window.__ELN_KETCHER__.initial --> Ketcher
    Ketcher --POST /api/save {smiles,mol,rxn,cdxml}--> 主进程 --> 回调 --> 画板

回写优先用 CDXML（箭头和试剂文字都在），没有就退回 RXN / MOL / SMILES。

安全：只监听 ``127.0.0.1`` 的随机端口，且每次只接受一次回写；
服务在拿到结果（或超时）后就关掉。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from paths import app_dir

#: 一次编辑最长等多久（秒）。用户开着窗口不动就超时放弃。
TIMEOUT = 30 * 60

_CTYPE = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".wasm": "application/wasm",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".map": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}

_EDGE = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def dist_dir() -> str:
    return os.path.join(app_dir(), "vendor", "ketcher-app", "dist")


def is_built() -> bool:
    return os.path.isfile(os.path.join(dist_dir(), "index.html"))


def _boot_script(payload: dict) -> str:
    js = json.dumps(payload, ensure_ascii=False)
    # 防止内容里出现 </script> 把标签提前闭合
    js = js.replace("</", "<\\/")
    return ('<script>window.__ELN_KETCHER__ = %s;</script>\n' % js)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, addr, handler, boot: dict):
        super().__init__(addr, handler)
        self.boot = boot
        self.done = threading.Event()
        self.result: dict | None = None
        self.lock = threading.Lock()

    def deliver(self, payload: dict) -> None:
        with self.lock:
            if self.done.is_set():
                return                  # 只认第一次
            self.result = payload
            self.done.set()


class _Handler(BaseHTTPRequestHandler):
    server_version = "ELN-Ketcher/1.0"
    protocol_version = "HTTP/1.1"

    # ---- 小工具
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def log_message(self, fmt, *args):        # 静音，别往控制台刷
        pass

    # ---- GET
    def do_GET(self):                          # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/init":
            self._json({"structure": self.server.boot.get("initial") or ""})
            return
        if path in ("/", "/index.html"):
            html_path = os.path.join(dist_dir(), "index.html")
            try:
                with open(html_path, encoding="utf-8") as fh:
                    html = fh.read()
            except OSError:
                self._send(500, "Ketcher 还没构建：先跑 tools/build_ketcher.bat"
                           .encode("utf-8"), "text/plain; charset=utf-8")
                return
            # 在 <head> 后注入启动数据
            boot = _boot_script(self.server.boot)
            if "<head>" in html:
                html = html.replace("<head>", "<head>\n" + boot, 1)
            else:
                html = boot + html
            self._send(200, html.encode("utf-8"), _CTYPE[".html"])
            return
        self._static(path)

    def _static(self, path: str) -> None:
        rel = path.lstrip("/").replace("\\", "/")
        if ".." in rel.split("/"):
            self._send(403, b"forbidden", "text/plain")
            return
        full = os.path.normpath(os.path.join(dist_dir(), rel))
        if not os.path.abspath(full).startswith(os.path.abspath(dist_dir())):
            self._send(403, b"forbidden", "text/plain")
            return
        if not os.path.isfile(full):
            self._send(404, b"not found", "text/plain")
            return
        ext = os.path.splitext(full)[1].lower()
        try:
            with open(full, "rb") as fh:
                body = fh.read()
        except OSError:
            self._send(500, b"read error", "text/plain")
            return
        self._send(200, body, _CTYPE.get(ext, "application/octet-stream"))

    # ---- POST
    def do_POST(self):                         # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if path == "/api/save":
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                self._json({"ok": False, "error": "bad json"}, 400)
                return
            self.server.deliver({"saved": True, "data": data})
            self._json({"ok": True})
            return
        if path == "/api/cancel":
            self.server.deliver({"saved": False})
            self._json({"ok": True})
            return
        self._json({"ok": False}, 404)


def _launch(url: str) -> bool:
    """用 Edge 的应用模式打开；失败退回默认浏览器。"""
    for exe in _EDGE:
        if os.path.isfile(exe):
            # 用独立 profile：否则 Edge 会把 URL 丢给已在运行的实例，
            # 变成一个普通标签页而不是独立应用窗口
            profile = os.path.join(tempfile.gettempdir(),
                                   "eln-ketcher-profile")
            try:
                os.makedirs(profile, exist_ok=True)
            except OSError:
                profile = None
            args = [exe, "--app=%s" % url, "--window-size=1280,880"]
            if profile:
                args.append("--user-data-dir=%s" % profile)
            try:
                subprocess.Popen(args)
                return True
            except Exception:                  # noqa: BLE001
                pass
    try:
        webbrowser.open(url)
        return True
    except Exception:                          # noqa: BLE001
        return False


def open_editor(parent, initial: str | None, on_done, timeout: int = TIMEOUT) -> bool:
    """打开 Ketcher；``on_done(payload)`` 在拿到结果后于 Tk 主线程里调用。

    payload 形如 ``{"saved": True, "data": {"smiles":…, "mol":…, "rxn":…,
    "cdxml":…}}``，取消 / 超时则是 ``{"saved": False}``。
    返回 False 表示没能打开（例如还没构建）。
    """
    if not is_built():
        return False

    boot = {"initial": initial or ""}
    server = _Server(("127.0.0.1", 0), _Handler, boot)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    url = "http://127.0.0.1:%d/" % port
    if not _launch(url):
        server.shutdown()
        return False

    box: "queue.Queue[dict]" = queue.Queue()

    def _wait():
        # 只做网络侧的事，不碰 Tk：Tk 不是线程安全的，
        # 在别的线程里调 widget.after() 会抛
        # "main thread is not in main loop"，回调就永远到不了。
        got = server.done.wait(timeout)
        box.put(server.result if got else {"saved": False, "timeout": not got})
        for fn in (server.shutdown, server.server_close):
            try:
                fn()
            except Exception:                  # noqa: BLE001
                pass

    threading.Thread(target=_wait, daemon=True).start()

    def _poll():
        try:
            payload = box.get_nowait()
        except queue.Empty:
            try:
                parent.after(250, _poll)
            except Exception:                  # noqa: BLE001  窗口已关
                pass
            return
        try:
            on_done(payload)
        except Exception:                      # noqa: BLE001
            pass

    parent.after(250, _poll)                   # 在主线程里起轮询
    return True
