# -*- coding: utf-8 -*-
"""登录窗口：登录 / 创建账户 / 本机明文找回 / 30 天免登录。

由 gui.main() 在创建主界面之前模态弹出；会话有效时不会显示。
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox

import auth
from paths import res_path

BG = "#f4f6f9"
CARD = "#ffffff"
LINE = "#dde3ea"
INK = "#16202c"
DIM = "#6b7684"
ACCENT = "#1f6feb"
GREEN = "#1a7f4b"
RED = "#c0392b"
UI = "Microsoft YaHei UI"


def _btn(parent, text, cmd, bg="#e8eef7", fg=INK, width=None):
    return tk.Button(parent, text=text, command=cmd, relief="flat", bd=0,
                     bg=bg, fg=fg, font=(UI, 10), padx=14, pady=6,
                     width=width, cursor="hand2", activebackground="#d6e2f5")


class LoginWindow:
    def __init__(self, root: tk.Misc):
        self.result = None
        self.win = tk.Toplevel(root)
        self.win.title("ELN · 账户登录")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.win.bind("<Escape>", lambda e: self.on_cancel())
        try:
            ico = res_path("assets", "app.ico")
            if os.path.exists(ico):
                self.win.iconbitmap(ico)
        except Exception:
            pass

        self.name = tk.StringVar()
        self.pwd = tk.StringVar()
        self.remember = tk.BooleanVar(value=True)
        self.msg = tk.StringVar()

        card = tk.Frame(self.win, bg=CARD, highlightthickness=1,
                        highlightbackground=LINE)
        card.pack(padx=22, pady=18)

        tk.Label(card, text="ELN · 电子实验记录", bg=CARD, fg=INK,
                 font=(UI, 15, "bold")).pack(anchor="w", padx=22, pady=(18, 2))
        self.sub = tk.Label(card, text="登录后进入自己的实验数据", bg=CARD,
                            fg=DIM, font=(UI, 9), anchor="w")
        self.sub.pack(anchor="w", padx=22, pady=(0, 14))

        form = tk.Frame(card, bg=CARD)
        form.pack(fill="x", padx=22)
        tk.Label(form, text="账户名", bg=CARD, fg=INK, font=(UI, 10),
                 width=7, anchor="w").grid(row=0, column=0, pady=5)
        e1 = tk.Entry(form, textvariable=self.name, width=26, font=(UI, 11),
                      bd=1, relief="solid", bg="#fbfcfd")
        e1.grid(row=0, column=1, ipady=4, pady=5)
        tk.Label(form, text="密码", bg=CARD, fg=INK, font=(UI, 10),
                 width=7, anchor="w").grid(row=1, column=0, pady=5)
        e2 = tk.Entry(form, textvariable=self.pwd, show="●", width=26,
                      font=(UI, 11), bd=1, relief="solid", bg="#fbfcfd")
        e2.grid(row=1, column=1, ipady=4, pady=5)
        e1.bind("<Return>", lambda e: e2.focus_set())
        e2.bind("<Return>", lambda e: self.on_login())

        self.msg_lbl = tk.Label(card, textvariable=self.msg, bg=CARD, fg=RED,
                                font=(UI, 9), anchor="w", wraplength=330,
                                justify="left")
        self.msg_lbl.pack(fill="x", padx=22, pady=(8, 0))

        chk = tk.Checkbutton(card, text="在这台电脑上保持登录 30 天",
                             variable=self.remember, bg=CARD, fg=DIM,
                             font=(UI, 9), activebackground=CARD,
                             selectcolor=CARD, anchor="w")
        chk.pack(fill="x", padx=20, pady=(6, 12))

        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", padx=22, pady=(0, 6))
        _btn(row, "登录", self.on_login, ACCENT, "#ffffff", width=12).pack(side="left")
        _btn(row, "创建账户", self.on_create, "#e8f4ec", GREEN,
             width=10).pack(side="right")

        foot = tk.Frame(card, bg=CARD)
        foot.pack(fill="x", padx=22, pady=(4, 16))
        link = tk.Button(foot, text="找回密码", command=self.on_recover,
                         relief="flat", bd=0, bg=CARD, fg=ACCENT,
                         font=(UI, 9), cursor="hand2", padx=0)
        link.pack(side="left")
        tk.Label(foot, text="仅本机可明文查看 · 密码勿复用", bg=CARD,
                 fg=DIM, font=(UI, 8)).pack(side="right")

        if not auth.has_users():
            self.sub.configure(text="首次使用：先点「创建账户」，现有数据归第一个账户")
            self.msg.set("还没有账户。点右下角「创建账户」开始。")
            self.msg_lbl.configure(fg=DIM)
        else:
            names = auth.list_users()
            if names:
                self.name.set(names[0])
        self.win.after(100, e1.focus_set)
        self._center(root)

    def _center(self, root):
        self.win.update_idletasks()
        w, h = self.win.winfo_width(), self.win.winfo_height()
        x = (self.win.winfo_screenwidth() - w) // 2
        y = (self.win.winfo_screenheight() - h) // 3
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")
        # 主窗口在登录前是 withdraw 的；此时若把登录窗 transient 到它，
        # Windows 会把登录窗一起藏掉（实测 mapped=0）。只在主窗口可见时才挂 transient。
        if root.winfo_viewable():
            self.win.transient(root)
        self.win.lift()
        self.win.grab_set()

    def _error(self, text):
        self.msg_lbl.configure(fg=RED)
        self.msg.set(text)

    # ------------------------------------------------------------ 动作
    def on_login(self):
        name = self.name.get().strip()
        pwd = self.pwd.get()
        if not name or not pwd:
            self._error("账户名和密码都要填。")
            return
        if not auth.has_users():
            self._error("还没有账户，先点「创建账户」。")
            return
        try:
            user = auth.verify(name, pwd)
        except Exception as e:
            self._error(f"登录失败：{e}")
            return
        if user is None:
            self._error("账户名或密码不对；忘了就点下面「找回密码」。")
            return
        self._finish(user)

    def on_create(self):
        CreateDialog(self.win, self)

    def created(self, user: dict):
        self.name.set(user["name"])
        self._finish(user)

    def _finish(self, user: dict):
        auth.save_session(user["name"], bool(self.remember.get()))
        self.result = user
        self.win.grab_release()
        self.win.destroy()

    def on_recover(self):
        name = self.name.get().strip() or None
        try:
            found = auth.recover(name)
        except auth.AuthError as e:
            messagebox.showinfo("找不回", str(e), parent=self.win)
            return
        except Exception as e:
            messagebox.showerror("出错了", str(e), parent=self.win)
            return
        RecoverDialog(self.win, found)

    def on_cancel(self):
        self.result = None
        self.win.grab_release()
        self.win.destroy()

    def show(self):
        self.win.wait_window()
        return self.result


class CreateDialog:
    """建账户：用户名 + 两次密码。建成后直接以该账户登录。"""

    def __init__(self, parent, login: LoginWindow):
        self.login = login
        self.win = tk.Toplevel(parent)
        self.win.title("创建账户")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.bind("<Escape>", lambda e: self.win.destroy())

        self.n = tk.StringVar()
        self.p1 = tk.StringVar()
        self.p2 = tk.StringVar()
        card = tk.Frame(self.win, bg=CARD, highlightthickness=1,
                        highlightbackground=LINE)
        card.pack(padx=20, pady=16)
        tk.Label(card, text="创建账户", bg=CARD, fg=INK,
                 font=(UI, 13, "bold")).pack(anchor="w", padx=20, pady=(14, 2))
        tk.Label(card, text="每个账户有独立的一套实验数据", bg=CARD, fg=DIM,
                 font=(UI, 9)).pack(anchor="w", padx=20, pady=(0, 10))
        form = tk.Frame(card, bg=CARD)
        form.pack(padx=20)
        for i, (label, var, show) in enumerate((
                ("账户名", self.n, ""),
                ("密码", self.p1, "●"),
                ("再输一次", self.p2, "●"))):
            tk.Label(form, text=label, bg=CARD, fg=INK, font=(UI, 10),
                     width=9, anchor="w").grid(row=i, column=0, pady=5)
            tk.Entry(form, textvariable=var, show=show, width=24,
                     font=(UI, 11), bd=1, relief="solid",
                     bg="#fbfcfd").grid(row=i, column=1, ipady=4, pady=5)
        self.tip = tk.Label(card, text=f"密码至少 {auth.MIN_PASSWORD} 位",
                            bg=CARD, fg=DIM, font=(UI, 9), anchor="w")
        self.tip.pack(fill="x", padx=20, pady=(8, 0))
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", padx=20, pady=(10, 16))
        _btn(row, "创建并登录", self.on_ok, ACCENT, "#ffffff").pack(side="left")
        _btn(row, "取消", self.win.destroy, "#f2f4f7", DIM).pack(side="right")
        self.win.update_idletasks()
        x = (self.win.winfo_screenwidth() - self.win.winfo_width()) // 2
        y = (self.win.winfo_screenheight() - self.win.winfo_height()) // 3
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

    def on_ok(self):
        if self.p1.get() != self.p2.get():
            self.tip.configure(text="两次输入的密码不一样。", fg=RED)
            return
        try:
            user = auth.create_user(self.n.get(), self.p1.get())
        except auth.AuthError as e:
            self.tip.configure(text=str(e), fg=RED)
            return
        except Exception as e:
            self.tip.configure(text=f"创建失败：{e}", fg=RED)
            return
        self.win.grab_release()
        self.win.destroy()
        self.login.created(user)


class RecoverDialog:
    """本机明文找回：点「找回密码」后直接显示，不做二次验证。"""

    def __init__(self, parent, found: dict[str, str]):
        self.win = tk.Toplevel(parent)
        self.win.title("找回密码 · 本机")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()
        card = tk.Frame(self.win, bg=CARD, highlightthickness=1,
                        highlightbackground=LINE)
        card.pack(padx=20, pady=16)
        tk.Label(card, text="本机保存的账户密码", bg=CARD, fg=INK,
                 font=(UI, 13, "bold")).pack(anchor="w", padx=20, pady=(14, 4))
        tk.Label(card,
                 text="下面显示的是明文，因为确认了这台机器就是创建账户的机器。\n"
                      "换电脑 / 重装系统后不会显示。请勿复用此密码。",
                 bg=CARD, fg=DIM, font=(UI, 9), justify="left",
                 anchor="w").pack(anchor="w", padx=20, pady=(0, 10))
        txt = tk.Text(card, width=36, height=max(3, min(10, len(found) + 2)),
                      font=(UI, 11), bg="#fbfcfd", fg=INK, bd=1,
                      relief="solid", padx=10, pady=8)
        txt.pack(padx=20, fill="x")
        for name, pwd in found.items():
            txt.insert("end", f"{name}    {pwd}\n")
        txt.configure(state="disabled")
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", padx=20, pady=(10, 16))
        _btn(row, "复制", lambda: self._copy("\n".join(
            f"{k}  {v}" for k, v in found.items())), "#e8eef7").pack(side="left")
        _btn(row, "关闭", self.win.destroy, "#f2f4f7", DIM).pack(side="right")
        self.win.update_idletasks()
        x = (self.win.winfo_screenwidth() - self.win.winfo_width()) // 2
        y = (self.win.winfo_screenheight() - self.win.winfo_height()) // 3
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _copy(self, text):
        self.win.clipboard_clear()
        self.win.clipboard_append(text)


def show_login(root: tk.Misc):
    """模态显示登录窗口，返回登录成功的账户 dict；取消返回 None。"""
    return LoginWindow(root).show()
