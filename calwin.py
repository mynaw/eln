# -*- coding: utf-8 -*-
"""日历视图：按月看这段时间做了哪些实验，点条目直接打开记录。

数据来自 samples.created / reactions.created（建记录那一刻的时间戳），
事件按日期聚合；一个月超过 200 条时只显示 200 条，够翻历史了。
"""
from __future__ import annotations

import calendar
import datetime

import tkinter as tk
from tkinter import ttk

BG = "#f4f6f9"
CARD = "#ffffff"
LINE = "#dde3ea"
INK = "#16202c"
DIM = "#6b7684"
ACCENT = "#1f6feb"
GREEN = "#1a7f4b"
TAG = "#8a6d3b"
RED = "#c0392b"
UI = "Microsoft YaHei UI"

WD = ["一", "二", "三", "四", "五", "六", "日"]


class CalendarWindow:
    """月历窗口。open_record(owner_type, oid) 由主界面传入。"""

    def __init__(self, parent, store, open_record, coll_id=None):
        self.store = store
        self.open_record = open_record
        self.coll_id = coll_id
        self.today = datetime.date.today()
        self.ym = (self.today.year, self.today.month)

        self.win = tk.Toplevel(parent)
        self.win.title("ELN · 日历")
        self.win.configure(bg=BG)
        self.win.transient(parent)
        self.win.geometry("900x640")

        top = tk.Frame(self.win, bg=BG)
        top.pack(fill="x", padx=14, pady=(12, 6))
        tk.Button(top, text="◀", command=lambda: self._step(-1), relief="flat",
                  bd=0, bg=CARD, fg=INK, font=(UI, 11), width=3,
                  cursor="hand2").pack(side="left")
        self.lbl_month = tk.Label(top, text="", bg=BG, fg=INK,
                                  font=(UI, 13, "bold"), width=16)
        self.lbl_month.pack(side="left", padx=8)
        tk.Button(top, text="▶", command=lambda: self._step(1), relief="flat",
                  bd=0, bg=CARD, fg=INK, font=(UI, 11), width=3,
                  cursor="hand2").pack(side="left")
        tk.Button(top, text="今天", command=self._go_today, relief="flat", bd=0,
                  bg="#eef1f5", fg=INK, font=(UI, 9), padx=10,
                  cursor="hand2").pack(side="left", padx=10)
        tk.Label(top, text="点条目打开记录", bg=BG, fg=DIM,
                 font=(UI, 8)).pack(side="right")

        self.grid = tk.Frame(self.win, bg=BG)
        self.grid.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self._build_grid()
        self._refresh()

    # ------------------------------------------------------------ 导航
    def _step(self, d):
        y, m = self.ym
        m += d
        if m == 0:
            y, m = y - 1, 12
        elif m == 13:
            y, m = y + 1, 1
        self.ym = (y, m)
        self._refresh()

    def _go_today(self):
        self.ym = (self.today.year, self.today.month)
        self._refresh()

    # ------------------------------------------------------------ 数据
    def _events(self):
        """这个月的 {(年,月,日): [(owner_type, oid, 标题, 时间字符串)]}。"""
        y, m = self.ym
        first = f"{y:04d}-{m:02d}-"
        ev: dict = {}
        n = 0
        rows = [("sample", r) for r in self.store.q(
            "SELECT id, name, created FROM samples WHERE created LIKE ? "
            "ORDER BY created", (first + "%",))]
        rows += [("reaction", r) for r in self.store.q(
            "SELECT id, title, created FROM reactions WHERE created LIKE ? "
            "ORDER BY created", (first + "%",))]
        for kind, r in rows:
            if n >= 200:
                break
            try:
                d = datetime.date.fromisoformat(r["created"][:10])
            except ValueError:
                continue
            key = (d.year, d.month, d.day)
            title = (r["name"] if kind == "sample" else r["title"]) or "（未命名）"
            tm = r["created"][11:16] if len(r["created"]) >= 16 else ""
            ev.setdefault(key, []).append((kind, r["id"], title, tm))
            n += 1
        return ev

    # ------------------------------------------------------------ 界面
    def _build_grid(self):
        for w in self.grid.winfo_children():
            w.destroy()
        for i, name in enumerate(WD):
            tk.Label(self.grid, text=f"周{name}", bg=BG, fg=DIM,
                     font=(UI, 9, "bold")).grid(row=0, column=i, sticky="nsew")
        self.grid.columnconfigure(tuple(range(7)), weight=1, uniform="d")
        for r in range(1, 7):
            self.grid.rowconfigure(r, weight=1)

    def _refresh(self):
        y, m = self.ym
        self.lbl_month.configure(text=f"{y} 年 {m} 月")
        ev = self._events()
        self._build_grid()
        cal = calendar.Calendar(firstweekday=0).monthdatescalendar(y, m)
        for ri, week in enumerate(cal, start=1):
            for ci, day in enumerate(week):
                in_month = day.month == m
                is_today = day == self.today
                bg = CARD if in_month else "#eef1f5"
                fg = INK if in_month else "#b8c0cc"
                cell = tk.Frame(self.grid, bg=bg, highlightthickness=1,
                                highlightbackground=LINE)
                cell.grid(row=ri, column=ci, sticky="nsew", padx=1, pady=1)
                head = tk.Frame(cell, bg=bg)
                head.pack(fill="x")
                tk.Label(head, text=str(day.day),
                         bg=RED if is_today else bg,
                         fg="#ffffff" if is_today else fg,
                         font=(UI, 9, "bold"), padx=4).pack(side="left")
                items = ev.get((day.year, day.month, day.day), [])
                tk.Label(head, text=f"{len(items)} 条" if items else "",
                         bg=bg, fg=DIM, font=(UI, 8)).pack(side="right", padx=4)
                for kind, oid, title, tm in items[:4]:
                    fg_i = GREEN if kind == "sample" else ACCENT
                    txt = f"{'◆' if kind == 'sample' else '▶'} {title}"
                    if tm:
                        txt = f"{tm} {txt}"
                    b = tk.Label(cell, text=txt[:22], bg=bg, fg=fg_i,
                                 font=(UI, 8), cursor="hand2", anchor="w")
                    b.pack(fill="x", padx=(6, 2))
                    b.bind("<Button-1>", lambda e, k=kind, o=oid: self._open(k, o))
                if len(items) > 4:
                    tk.Label(cell, text=f"… 还有 {len(items) - 4} 条", bg=bg,
                             fg=DIM, font=(UI, 8)).pack(anchor="w", padx=6)

    def _open(self, kind, oid):
        try:
            self.open_record(kind, oid)
        except Exception:
            pass
