# -*- coding: utf-8 -*-
"""「极性变化」卡片窗口。

上半张卡片列 Δ 描述符，下半张卡片给成因与实验后果解析（polarity.py）。
反应记录会自动带入反应物 / 产物；样品可手填对照结构。
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

import polarity
from paths import res_path

BG = "#f4f6f9"
CARD = "#ffffff"
LINE = "#dde3ea"
INK = "#16202c"
DIM = "#6b7684"
ACCENT = "#1f6feb"
GREEN = "#1a7f4b"
PURPLE = "#6a4fa3"
UI = "Microsoft YaHei UI"
MONO = UI   # 字体统一：等宽位也用同一族


def _btn(parent, text, cmd, bg="#e8eef7", fg=INK):
    return tk.Button(parent, text=text, command=cmd, relief="flat", bd=0,
                     bg=bg, fg=fg, font=(UI, 9), padx=10, pady=5,
                     cursor="hand2", activebackground="#d6e2f5")


class PolarityWindow:
    def __init__(self, root, app, before: str = "", after: str = ""):
        self.root = root
        self.app = app
        self.result = None

        self.win = tk.Toplevel(root)
        self.win.title("极性变化 · ELN")
        self.win.geometry("940x700")
        self.win.minsize(820, 560)
        self.win.configure(bg=BG)
        self.win.bind("<Escape>", lambda e: self.close())
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        ico = res_path("assets", "app.ico")
        if os.path.exists(ico):
            try:
                self.win.iconbitmap(ico)
            except Exception:
                pass

        self.status = tk.Label(self.win, text="", bg=BG, fg=DIM,
                               font=(UI, 8), anchor="w")
        self.status.pack(side="bottom", fill="x", padx=14, pady=(0, 8))

        self._build()
        self.a_var.set(before)
        self.b_var.set(after)
        if before and after:
            self.win.after(60, self.on_compare)
        else:
            self._show_text(
                "用法：\n"
                "  · 两个框分别填起始物 / 产物（或想比较的两个结构）的 SMILES，点「比较」。\n"
                "  · 在 ELN 里打开反应记录再进这个窗口，会自动带入反应物与产物。\n"
                "  · 「当前记录」重新取当前药剂 / 反应的结构；「交换」把 A、B 对调。\n\n"
                "口径：logP 是中性分子的 Crippen 估算，TPSA 是 2D 拓扑极性表面积，\n"
                "      HBD/HBA 为氢键供体 / 受体数。检测结果会附带成因与色谱后果解析。")
            self._status("等待输入两个结构")

    # ------------------------------------------------------------ 布局
    def _build(self):
        top = tk.Frame(self.win, bg=BG)
        top.pack(fill="x", padx=12, pady=(10, 4))

        row1 = tk.Frame(top, bg=BG)
        row1.pack(fill="x")
        tk.Label(row1, text="极性变化", bg=BG, fg=INK,
                 font=(UI, 14, "bold")).pack(side="left")
        tk.Label(row1, text="描述符差值 + 成因 / 实验后果解析", bg=BG, fg=DIM,
                 font=(UI, 9)).pack(side="left", padx=(8, 10))
        self.verdict = tk.Label(row1, text="", bg=BG, fg=PURPLE,
                                font=(UI, 10, "bold"))
        self.verdict.pack(side="right")

        row2 = tk.Frame(top, bg=BG)
        row2.pack(fill="x", pady=(8, 2))
        self.a_var = tk.StringVar()
        self.b_var = tk.StringVar()
        tk.Label(row2, text="A 起始物", bg=BG, fg=DIM,
                 font=(UI, 9)).pack(side="left")
        ea = tk.Entry(row2, textvariable=self.a_var, width=30, font=(MONO, 10),
                      bd=1, relief="solid", bg=CARD, fg=INK)
        ea.pack(side="left", padx=(4, 12), ipady=3)
        ea.bind("<Return>", lambda e: self.on_compare())
        tk.Label(row2, text="B 产物", bg=BG, fg=DIM,
                 font=(UI, 9)).pack(side="left")
        eb = tk.Entry(row2, textvariable=self.b_var, width=30, font=(MONO, 10),
                      bd=1, relief="solid", bg=CARD, fg=INK)
        eb.pack(side="left", padx=(4, 12), ipady=3)
        eb.bind("<Return>", lambda e: self.on_compare())

        row3 = tk.Frame(top, bg=BG)
        row3.pack(fill="x", pady=(6, 0))
        _btn(row3, "比较", self.on_compare, ACCENT, "#ffffff").pack(side="left", padx=(0, 6))
        _btn(row3, "交换 A/B", self.on_swap).pack(side="left", padx=(0, 6))
        _btn(row3, "当前记录", self.on_current, "#e8f4ec", GREEN).pack(side="left", padx=(0, 6))
        _btn(row3, "复制解析", self.on_copy).pack(side="left", padx=(0, 6))
        _btn(row3, "关闭", self.close, "#f2f4f7", DIM).pack(side="left", padx=(0, 6))
        tk.Label(row3, text="回车比较 · Esc 关闭", bg=BG, fg=DIM,
                 font=(UI, 8)).pack(side="right")

        body = tk.Frame(self.win, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=(6, 2))

        # 卡片 1：Δ 描述符
        c1 = tk.Frame(body, bg=CARD, highlightthickness=1,
                      highlightbackground=LINE)
        c1.pack(fill="x", pady=(0, 8))
        tk.Label(c1, text="描述符变化", bg=CARD, fg=INK,
                 font=(UI, 11, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        self.tree = ttk.Treeview(c1, columns=("key", "a", "b", "d"),
                                 show="headings", height=5)
        for col, title, w in (("key", "指标", 210), ("a", "A 起始物", 140),
                              ("b", "B 产物", 140), ("d", "Δ = B − A", 140)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="x", padx=12, pady=(0, 10))

        # 卡片 2：解析
        c2 = tk.Frame(body, bg=CARD, highlightthickness=1,
                      highlightbackground=LINE)
        c2.pack(fill="both", expand=True)
        tk.Label(c2, text="成因与后果解析", bg=CARD, fg=INK,
                 font=(UI, 11, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        wrap = tk.Frame(c2, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.txt = tk.Text(wrap, wrap="word", font=(UI, 10), fg=INK,
                           bg="#fcfdfe", bd=1, relief="solid",
                           padx=10, pady=8, spacing1=1, spacing3=2)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)

    # ------------------------------------------------------------ 动作
    def on_compare(self):
        a = self.a_var.get().strip()
        b = self.b_var.get().strip()
        if not a or not b:
            messagebox.showinfo("还差一个结构",
                                "A 和 B 都要填 SMILES 才能比较；\n"
                                "也可以在 ELN 里选中反应后点「当前记录」自动带入。",
                                parent=self.win)
            return
        res = polarity.compare(a, b)
        if "error" in res:
            self.result = None
            self.verdict.configure(text="")
            self._show_text("无法比较：" + res["error"])
            self._status("输入有误")
            return
        self.result = res
        self.verdict.configure(text=res["verdict"])
        for row in self.tree.get_children():
            self.tree.delete(row)
        for k, label in (("logp", "logP (Crippen)"), ("tpsa", "TPSA (Å²)"),
                         ("hbd", "HBD 氢键供体"), ("hba", "HBA 氢键受体")):
            dv = res["delta"][k]
            self.tree.insert("", "end", values=(
                label, res["a"][k], res["b"][k], f"{dv:+.2f}" if k in ("logp", "tpsa")
                else f"{int(dv):+d}"))
        self._show_text(polarity.format_report(res))
        self._status(f"{res['a']['formula']} → {res['b']['formula']} · {res['verdict']}")

    def on_swap(self):
        a, b = self.a_var.get(), self.b_var.get()
        self.a_var.set(b)
        self.b_var.set(a)
        if a and b:
            self.on_compare()

    def on_current(self):
        ctx = getattr(self.app, "polarity_context", None)
        if not callable(ctx):
            messagebox.showinfo("没有当前记录", "先到主界面选一条药剂或反应。",
                                parent=self.win)
            return
        a, b = ctx()
        self.a_var.set(a)
        self.b_var.set(b)
        if a and b:
            self.on_compare()
        else:
            self._status("当前记录只有一个结构，请在 B 里填对照")
            self._show_text("已从当前记录带入 A。\n\n"
                            "药剂只有一个结构，B 需要你自己填一个对照 SMILES；\n"
                            "如果是反应记录，A/B 会自动取反应物与产物。")

    def on_copy(self):
        text = self.txt.get("1.0", "end").rstrip()
        if not text:
            return
        self.win.clipboard_clear()
        self.win.clipboard_append(text)
        self._status("解析已复制到剪贴板")

    def _show_text(self, text: str):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", text)
        self.txt.configure(state="disabled")

    def _status(self, msg: str):
        self.status.configure(text=msg + "        ·        引擎 内置 (RDKit)")

    def close(self):
        try:
            self.win.destroy()
        finally:
            if getattr(self.app, "_polarity_win", None) is self:
                self.app._polarity_win = None


def open_polarity(root, app, before: str = "", after: str = ""):
    """同一时刻只开一张卡片；重复调用会复用并带入新结构。"""
    old = getattr(app, "_polarity_win", None)
    try:
        if old is not None and old.win.winfo_exists():
            old.win.lift()
            old.win.focus_set()
            if before:
                old.a_var.set(before)
            if after:
                old.b_var.set(after)
            if before and after:
                old.on_compare()
            return old
    except Exception:
        pass
    win = PolarityWindow(root, app, before, after)
    app._polarity_win = win
    return win
