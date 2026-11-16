# -*- coding: utf-8 -*-
"""
ELN 主界面：左边集合，中间条目列表，右边详情。

三栏用 PanedWindow，宽度可以拖。数据全部走 store.Store，结构全部走 chem。
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import ImageTk

import chem
import drawpad
import effects
import effectswin
import polarity
import polaritywin
import recexport
import packexport
import calwin
import helpwin
import notebook
from notebook import insert_mixed, F_LATIN, F_CJK
import stoich
import auth
import loginwin
from paths import app_dir, res_path
from store import ORPHAN, ROLES, Store

CLR_BG = "#f4f6f9"
CLR_CARD = "#ffffff"

# ============================================================
# 网页 / 浏览器访问开关（2026-11-10 按用户要求暂时停用）
#   改成 True 即可恢复：工具栏出现「浏览器」按钮，功能代码都在
#   （webapp.py / webui.py 原样保留，未删除任何实现）
# ============================================================
WEB_ENABLED = False
CLR_LINE = "#dde3ea"
CLR_INK = "#16202c"
CLR_DIM = "#6b7684"
CLR_ACCENT = "#1f6feb"
CLR_GREEN = "#1a7f4b"
CLR_RED = "#c0392b"
CLR_TAG = "#8a6d3b"

UI = "Microsoft YaHei UI"
MONO = UI   # 字体统一：等宽位也用同一族
# 正文与界面统一用同一字体（原先西文 Times New Roman / 中文宋体，与界面不一致）。
F_LATIN = UI
F_CJK = UI
CONTENT_SIZE = 10  # 与组成表、笔记本正文一致

FIELDS_SAMPLE = [
    ("name", "名称"), ("code", "编号"), ("cas", "CAS 号"),
    ("formula", "分子式"), ("mw", "分子量"), ("smiles", "SMILES"),
    ("amount", "数量"), ("unit", "单位"), ("purity", "纯度"),
    ("state", "状态"), ("location", "存放位置"), ("note", "备注"),
]


def parse_amount(text: str) -> tuple:
    """把「2.5 g」「2.5g」「2.5」这类写法拆成 (数值, 单位)。

    只写数字时单位默认 g；拆不出数字时数值给 None，整串当单位留着。
    """
    t = norm_num((text or "").strip())
    if not t:
        return None, None
    for i, ch in enumerate(t):
        if not (ch.isdigit() or ch in ".-"):
            head, tail = t[:i], t[i:].strip()
            try:
                return float(head), (tail or "g")
            except ValueError:
                return None, t
    try:
        return float(t), "g"
    except ValueError:
        return None, t


def _num(v, spec: str = "g") -> str:
    """宽容的数字格式化：能转 float 就按 spec 输出，转不了原样返回。

    库里 REAL 列的落盘类型不一定可信（老数据、导入的数据常把数字存成
    「5.0 g」「≥98%」这类文本），直接 `{v:g}` 会抛 ValueError。
    """
    if v is None or v == "":
        return ""
    try:
        return format(float(v), spec)
    except (TypeError, ValueError):
        return str(v)


def _amt(v, unit) -> str:
    """数值 + 单位（数量 / 用量）；文本里已经带同样单位的就不再重复拼。"""
    s = _num(v)
    if not s:
        return ""
    u = (unit or "").strip()
    if u and not s.lower().endswith(u.lower()):
        return f"{s} {u}"
    return s


def _pct(v) -> str:
    """产率：数字补 %，文本原样（已经带 % 的不重复加）。"""
    s = _num(v)
    if not s:
        return ""
    return s if s.endswith("%") else s + "%"


def norm_num(s: str) -> str:
    """把全角/中文标点数字折成 ASCII。

    中文输入法在 Entry 里常打出全角句号「。」(U+3002)、全角点「．」(U+FF0E)
    或全角逗号「，」(U+FF0C) 代替小数点，导致 float() 报错或小数点被吞掉。
    这里在解析前统一折成 ASCII，让用户「输不进小数」的体感消失。
    """
    if not s:
        return s
    table = str.maketrans({
        "。": ".", "．": ".", "，": ".",   # 全角句号 / 全角点 / 全角逗号 → 小数点
        "－": "-", "−": "-", "—": "-", "–": "-",  # 各种横线 → 减号
        "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
        "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
        "·": ".",  # 中间点也当小数点（少数输入法）
        "　": " ",
    })
    return s.translate(table)


def _bind_num_norm(var: tk.StringVar) -> None:
    """给数字 StringVar 挂一个写入时自动折全角的钩子。"""
    def _cb(*_a):
        cur = var.get()
        nw = norm_num(cur)
        if nw != cur:
            var.set(nw)
    var.trace_add("write", _cb)


def _safe_zipname(s: str) -> str:
    """标题转安全的 zip 文件名片段。"""
    return "".join(ch for ch in (s or "记录")
                   if ch not in '\\/:*?"<>|').strip()[:40] or "记录"


def split_rxn_pair(smi: str) -> tuple:
    """把反应 SMILES 拆成 (反应物, 产物)，只取各自第一个片段。

    'A.B>>C.D' -> ('A', 'C')；普通结构式 -> ('结构', '')。
    """
    s = (smi or "").strip()
    if not s:
        return "", ""
    if ">>" in s:
        left, right = s.split(">>", 1)
        a = left.split(".")[0].strip() if left.strip() else ""
        b = right.split(".")[0].strip() if right.strip() else ""
        return a, b
    return s.split(".")[0].strip(), ""


# ---------------------------------------------------------------- 工具组件

class ScrollFrame(ttk.Frame):
    """纵向可滚动的容器，往 .body 里放东西。"""

    def __init__(self, master, bg=CLR_CARD, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.sb.pack(side="right", fill="y")

        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _on_body(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)

    def _wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def clear(self):
        for w in self.body.winfo_children():
            w.destroy()


def dpi_aware():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


def open_path(path: str):
    try:
        if sys.platform == "win32":
            os.startfile(path)                      # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        messagebox.showerror("打不开", str(e))


# ---------------------------------------------------------------- 主窗口

S_COLS = [("code", 75), ("name", 132), ("formula", 82),
          ("mw", 60), ("amount", 88), ("purity", 52)]
R_COLS = [("code", 75), ("title", 226), ("yield", 60), ("created", 132)]


class App:
    def __init__(self, root: tk.Tk, user: dict | None = None):
        self.root = root
        self.user = user or {}
        self.store = Store()
        # 保险：打开即把任何 collection_id=NULL 的孤儿记录归到默认集合，
        # 从根上杜绝「记录因漏归类/删集合而从列表消失」。已正常归类的不会受影响。
        try:
            ns, nr = self.store.reassign_orphans()
            if ns or nr:
                print(f"[ELN] 自动修复孤儿归类：药剂 {ns} 条、反应 {nr} 条")
        except Exception:
            pass
        self.cur_coll = None            # None = 全部
        self.cur_sample = None
        self.cur_reaction = None
        self._filter_ids = None         # 结构检索命中的样品 id
        self._reaction_ids = None       # 这些样品参与的反应 id
        self._imgs: list = []
        self._effects_win = None        # 电子效应分析窗口（同时只开一个）
        self._polarity_win = None       # 极性变化卡片窗口（同时只开一个）

        root.title("ELN · 电子实验记录")
        root.geometry("1280x800")
        root.minsize(1240, 640)
        root.configure(bg=CLR_BG)

        # 全局 ttk 字体：Treeview（组成表、列表）默认字体是 TkDefaultFont（Segoe UI），
        # 和界面的微软雅黑不一致，这里统一成与正文相同的族与字号。
        try:
            st = ttk.Style()
            st.configure("Treeview", font=(UI, 10), rowheight=26)
            st.configure("Treeview.Heading", font=(UI, 10, "bold"))
            st.configure("TNotebook.Tab", font=(UI, 10))
            st.configure("TCombobox", font=(UI, 10))
        except Exception:
            pass

        self._build()
        self.refresh_collections()
        self.refresh_samples()
        self.refresh_reactions()
        self._show_empty()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Control-n>", lambda e: self.on_sample_new())
        root.bind("<Control-f>", lambda e: self.search_entry.focus_set())
        root.bind("<F5>", lambda e: self.refresh_all())
        root.bind("<F1>", lambda e: self.on_help())
        root.bind("<Control-e>", lambda e: self.on_effects())
        root.bind("<Control-Shift-B>", lambda e: self.on_notebook_toolbar())
        self.nb.bind("<<NotebookTabChanged>>", lambda e: root.after(30, self.apply_column_widths))
        root.after(120, self.apply_column_widths)

    # ------------------------------------------------------------ 布局
    def _build(self):
        bar = tk.Frame(self.root, bg=CLR_BG)
        bar.pack(fill="x", padx=12, pady=(10, 6))

        def btn(parent, text, cmd, bg="#e8eef7", fg=CLR_INK):
            return tk.Button(parent, text=text, command=cmd, relief="flat", bd=0,
                             bg=bg, fg=fg, font=(UI, 9), padx=6, pady=5,
                             cursor="hand2", activebackground="#d6e2f5")

        # 按钮顺序（按用户指定）：日历 → 试剂 → 反应 ｜ 导入 → 导出 → Ketcher
        #                    → 绘制 → 笔记 → 账户 → 备份 → 电子效应 → 帮助
        btn(bar, "日历", self.on_calendar, "#eef4fb", CLR_ACCENT).pack(side="left", padx=2)
        btn(bar, "药剂", self.on_sample_new, "#e8f4ec", CLR_GREEN).pack(side="left", padx=2)
        btn(bar, "反应", self.on_reaction_new, "#e8f4ec", CLR_GREEN).pack(side="left", padx=2)
        tk.Frame(bar, bg=CLR_LINE, width=1).pack(side="left", fill="y", padx=8, pady=6)
        btn(bar, "导入", self.on_import_sdf).pack(side="left", padx=2)
        self._btn_export = btn(bar, "导出 ▾", self.on_export_menu)
        self._btn_export.pack(side="left", padx=2)
        btn(bar, "Ketcher", self.on_ketcher_toolbar, "#e6f2f4", "#1b6f7a").pack(side="left", padx=2)
        btn(bar, "绘制", self.on_draw_toolbar, "#e8f4ec", CLR_GREEN).pack(side="left", padx=2)
        # 浏览器访问：按用户要求暂时隐藏；把文件顶部的 WEB_ENABLED 改成 True 即恢复
        if WEB_ENABLED:
            btn(bar, "浏览器", self.on_open_web, "#eef4fb", CLR_ACCENT).pack(side="left", padx=2)
        btn(bar, "笔记", self.on_notebook_toolbar, "#fff4e5", "#a06a1b").pack(side="left", padx=2)
        btn(bar, "账户", self.on_switch_user, "#f2f4f7", CLR_DIM).pack(side="left", padx=2)
        btn(bar, "备份", self.on_backup).pack(side="left", padx=2)
        btn(bar, "电子效应", self.on_effects, "#ede7f6", "#6a4fa3").pack(side="left", padx=(6, 2))
        btn(bar, "帮助", self.on_help, "#fff3e0", CLR_TAG).pack(side="left", padx=2)

        # 搜索区
        right = tk.Frame(bar, bg=CLR_BG)
        right.pack(side="right")
        self.search_mode = tk.StringVar(value="文本")
        ttk.Combobox(right, textvariable=self.search_mode, width=5, state="readonly",
                     values=["文本", "子结构", "相似性"], font=(UI, 9)).pack(side="left")
        self.search_entry = tk.Entry(right, width=14, font=(UI, 10), bd=1,
                                     relief="solid", bg="#ffffff", fg=CLR_INK)
        self.search_entry.pack(side="left", padx=6, ipady=3)
        self.search_entry.bind("<Return>", lambda e: self.on_search())
        btn(right, "搜索", self.on_search, CLR_ACCENT, "#ffffff").pack(side="left")
        btn(right, "清除", self.on_search_clear).pack(side="left", padx=(4, 0))

        # 三栏
        pw = tk.PanedWindow(self.root, orient="horizontal", bg=CLR_BG,
                            sashwidth=6, bd=0, sashrelief="flat")
        pw.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        left = tk.Frame(pw, bg=CLR_CARD, highlightthickness=1, highlightbackground=CLR_LINE)
        mid = tk.Frame(pw, bg=CLR_CARD, highlightthickness=1, highlightbackground=CLR_LINE)
        rightf = tk.Frame(pw, bg=CLR_CARD, highlightthickness=1, highlightbackground=CLR_LINE)
        pw.add(left, width=210, minsize=150)
        pw.add(mid, width=530, minsize=470)
        pw.add(rightf, width=540, minsize=320)

        self._build_collections(left)
        self._build_lists(mid)
        self._build_detail(rightf)

        foot = tk.Frame(self.root, bg=CLR_BG)
        foot.pack(fill="x", padx=14, pady=(0, 8))
        # 左：统计 / 临时提示；右：数据文件 · 定稿 · 保存 · 刷新 · 恢复
        self.status = tk.Label(foot, text="", bg=CLR_BG, fg=CLR_DIM,
                               font=(UI, 8), anchor="w")
        self.status.pack(side="left", fill="x", expand=True)

        self.lbl_db = tk.Label(foot, text="", bg=CLR_BG, fg="#a9b4c2",
                               font=(MONO, 8))
        self.lbl_db.pack(side="right", padx=(10, 12))

        self.btn_lock = tk.Button(foot, text="定稿", command=self.on_toggle_lock,
                                  relief="flat", bd=0, bg="#eef1f5", fg=CLR_INK,
                                  font=(UI, 8), padx=10, pady=2, cursor="hand2")
        self.btn_lock.pack(side="right", padx=(6, 0))
        self.btn_save = tk.Button(foot, text="保存", command=self.on_save_state,
                                  relief="flat", bd=0, bg=CLR_ACCENT, fg="#ffffff",
                                  font=(UI, 8, "bold"), padx=12, pady=2,
                                  cursor="hand2")
        self.btn_save.pack(side="right")
        self.btn_refresh = tk.Button(foot, text="⟳ 刷新", command=self.on_refresh_state,
                                     relief="flat", bd=0, bg="#eef1f5", fg="#1d7f5a",
                                     font=(UI, 8), padx=10, pady=2, cursor="hand2")
        self.btn_refresh.pack(side="right", padx=(6, 0))
        self.btn_restore = tk.Button(foot, text="↺ 恢复", command=self.on_restore_version,
                                     relief="flat", bd=0, bg="#eef1f5", fg="#6a4fa3",
                                     font=(UI, 8), padx=10, pady=2, cursor="hand2")
        self.btn_restore.pack(side="right", padx=(6, 0))

    def _build_collections(self, parent):
        head = tk.Frame(parent, bg=CLR_CARD)
        head.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(head, text="集合", bg=CLR_CARD, fg=CLR_INK,
                 font=(UI, 10, "bold")).pack(side="left")
        tk.Button(head, text="+", command=self.on_coll_new, relief="flat", bd=0,
                  bg=CLR_CARD, fg=CLR_ACCENT, font=(UI, 11, "bold"),
                  cursor="hand2").pack(side="right")

        self.coll_tree = ttk.Treeview(parent, show="tree", height=14)
        self.coll_tree.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        self.coll_tree.bind("<<TreeviewSelect>>", self.on_coll_pick)
        self.coll_tree.bind("<Double-1>", lambda e: self.on_coll_rename())

    def _build_lists(self, parent):
        self.nb = ttk.Notebook(parent)
        self.nb.pack(fill="both", expand=True, padx=4, pady=4)

        # 样品页
        p1 = tk.Frame(self.nb, bg=CLR_CARD)
        self.nb.add(p1, text="药剂")
        cols1 = ("code", "name", "formula", "mw", "amount", "purity")
        self.s_tree = ttk.Treeview(p1, columns=cols1, show="headings", selectmode="browse")
        for c, t, w in zip(cols1, ("编号", "名称", "分子式", "分子量", "数量", "纯度"),
                           (75, 132, 82, 60, 88, 50)):
            self.s_tree.heading(c, text=t)
            self.s_tree.column(c, width=w, minwidth=max(45, w - 15),
                               anchor="w" if c in ("code", "name") else "center",
                               stretch=(c == "purity"))
        self.s_tree.pack(fill="both", expand=True)
        self.s_tree.bind("<<TreeviewSelect>>", self.on_sample_pick)
        self.s_tree.bind("<Double-1>", lambda e: self.on_sample_edit())

        # 反应页
        p2 = tk.Frame(self.nb, bg=CLR_CARD)
        self.nb.add(p2, text="反应")
        cols2 = ("code", "title", "yield", "created")
        self.r_tree = ttk.Treeview(p2, columns=cols2, show="headings", selectmode="browse")
        for c, t, w in zip(cols2, ("编号", "标题", "产率", "创建时间"), (75, 225, 60, 130)):
            self.r_tree.heading(c, text=t)
            self.r_tree.column(c, width=w, minwidth=max(50, w - 15),
                               anchor="w" if c in ("code", "title") else "center",
                               stretch=(c == "created"))
        self.r_tree.pack(fill="both", expand=True)
        self.r_tree.bind("<<TreeviewSelect>>", self.on_reaction_pick)
        self.r_tree.bind("<Double-1>", lambda e: self.on_reaction_edit())

    def _build_detail(self, parent):
        self.detail = ScrollFrame(parent, bg=CLR_CARD)
        self.detail.pack(fill="both", expand=True)

    # ------------------------------------------------------------ 集合
    def refresh_collections(self):
        self.coll_tree.delete(*self.coll_tree.get_children())
        self.coll_tree.insert("", "end", iid="all", text="  全部条目")
        rows = self.store.collections()
        by_parent: dict = {}
        for r in rows:
            by_parent.setdefault(r["parent_id"], []).append(r)

        def add(parent_iid, pid):
            for r in by_parent.get(pid, []):
                iid = str(r["id"])
                self.coll_tree.insert(parent_iid, "end", iid=iid, text="  " + r["name"])
                add(iid, r["id"])

        add("all", None)
        self.coll_tree.item("all", open=True)
        for c in self.coll_tree.get_children("all"):
            self.coll_tree.item(c, open=True)
        # 保险：若有 collection_id=NULL 的孤儿记录，给一个「未归类」入口，
        # 让它们永远查得到，不会因为被过滤而从列表里消失。
        ns, nr = self.store.orphan_counts()
        if ns or nr:
            self.coll_tree.insert("", "end", iid="orphan",
                                  text=f"  未归类 ({ns + nr})",
                                  tags=("orphan",))
        self.coll_tree.selection_set("all")

    def on_coll_pick(self, _e=None):
        sel = self.coll_tree.selection()
        if not sel:
            return
        key = sel[0]
        self.cur_coll = (None if key == "all"
                         else ORPHAN if key == "orphan"
                         else int(key))
        self.refresh_samples()
        self.refresh_reactions()

    def on_coll_new(self):
        name = simpledialog_ask(self.root, "新建集合", "集合名称：")
        if not name:
            return
        parent = self.cur_coll
        self.store.add_collection(name, parent)
        self.refresh_collections()

    def on_coll_rename(self):
        sel = self.coll_tree.selection()
        if not sel or sel[0] == "all":
            return
        cid = int(sel[0])
        row = self.store.one("SELECT * FROM collections WHERE id=?", (cid,))
        name = simpledialog_ask(self.root, "重命名", "新名称：", row["name"] if row else "")
        if name:
            self.store.rename_collection(cid, name)
            self.refresh_collections()

    # ------------------------------------------------------------ 列表
    def refresh_samples(self):
        self.s_tree.delete(*self.s_tree.get_children())
        rows = self.store.samples(self.cur_coll, self._kw())
        if self._filter_ids is not None:
            rows = [r for r in rows if r["id"] in self._filter_ids]
        for r in rows:
            amt = ""
            if r["amount"] is not None:
                amt = _amt(r["amount"], r["unit"])
            nm = r["name"] or ""
            if len(nm) > 10:
                nm = nm[:9] + "…"
            self.s_tree.insert("", "end", iid=str(r["id"]), values=(
                r["code"] or "", nm, r["formula"] or "",
                _num(r["mw"], ".2f"), amt, r["purity"] or ""))
        self._update_status()

    def refresh_reactions(self):
        self.r_tree.delete(*self.r_tree.get_children())
        rows = self.store.reactions(self.cur_coll, self._kw())
        if self._reaction_ids is not None:
            rows = [r for r in rows if r["id"] in self._reaction_ids]
        for r in rows:
            created = (r["created"] or "")[5:10]      # 只留 "11-06"
            title = r["title"] or ""
            if len(title) > 16:
                title = title[:15] + "…"
            self.r_tree.insert("", "end", iid=str(r["id"]), values=(
                r["code"] or "", title,
                _pct(r["yield_pct"]),
                created))

    def refresh_all(self):
        self.refresh_collections()
        self.refresh_samples()
        self.refresh_reactions()

    def _kw(self) -> str:
        txt = self.search_entry.get().strip()
        if not txt or self.search_mode.get() != "文本":
            return ""
        return txt

    def apply_column_widths(self):
        """Notebook 未激活的页宽度是 1，列会被压到最小值。

        切页或窗口尺寸变化后重新设一遍，不然数字就挤成一团。
        """
        for tree, spec in ((self.s_tree, S_COLS), (self.r_tree, R_COLS)):
            if tree.winfo_width() <= 1:
                continue
            for col, w in spec:
                try:
                    tree.column(col, width=w)
                except Exception:
                    pass

    def _update_status(self):
        """状态栏分四段：统计/命中 ｜ 数据文件 ｜ 保存 ｜ 定稿。

        有临时提示（flash）时左段整段让位给提示并染成强调色。
        """
        flash = getattr(self, "_flash", "")
        if flash:
            self.status.configure(text=f"✦ {flash}", fg=CLR_ACCENT)
        else:
            st = self.store.stats()
            bits = [f"药剂 {st['samples']}", f"反应 {st['reactions']}",
                    f"附件 {st['attachments']}", f"绘制 {st['drawings']}",
                    f"笔记块 {st['blocks']}"]
            if self._filter_ids is not None:
                n_r = len(self._reaction_ids or ())
                bits.append(f"结构命中 {len(self._filter_ids)} 药剂 / {n_r} 反应")
            ok, _ = effects.available()
            bits.append("效应引擎 " + ("内置" if ok else "缺失"))
            self.status.configure(text="  ·  ".join(bits), fg=CLR_DIM)
        rec = self._current_record()
        locked = bool(rec and self.store.is_locked(rec[0], rec[1]))
        if locked and not flash:
            self.status.configure(text=self.status.cget("text") + "  ·  已定稿，只读",
                                  fg=CLR_DIM)
        self.lbl_db.configure(text="数据 " + os.path.basename(self.store.path))
        lock_btn = getattr(self, "btn_lock", None)
        if lock_btn is not None:
            lock_btn.configure(text="已定稿 · 解锁" if locked else "定稿",
                               bg="#fde8e8" if locked else "#eef1f5",
                               fg=CLR_RED if locked else CLR_INK)
        save_btn = getattr(self, "btn_save", None)
        if save_btn is not None:
            save_btn.configure(state="disabled" if locked else "normal",
                               bg="#c7d3e3" if locked else CLR_ACCENT)

    # ------------------------------------------------------------ 保存 / 定稿
    def _current_record(self):
        """当前详情页对应的记录：(owner_type, id, 显示名) 或 None。"""
        if self.cur_reaction:
            row = self.store.reaction(self.cur_reaction)
            if row:
                return ("reaction", row["id"], row["title"] or f"反应 {row['id']}")
        if self.cur_sample:
            row = self.store.sample(self.cur_sample)
            if row:
                return ("sample", row["id"], row["name"] or f"药剂 {row['id']}")
        return None

    def _guard_locked(self, owner_type: str, oid: int, action: str = "修改") -> bool:
        """记录已定稿就提示并返回 True，调用方直接 return。"""
        if not self.store.is_locked(owner_type, oid):
            return False
        messagebox.showinfo(
            "已定稿",
            f"这条记录已定稿，不能{action}。\n"
            "要改请点状态栏右下角的「已定稿 · 解锁」，输入登录密码即可解锁。",
            parent=self.root)
        return True

    def _reload_current(self):
        if self.cur_reaction:
            self.show_reaction(self.cur_reaction)
        elif self.cur_sample:
            self.show_sample(self.cur_sample)

    def _flash_status(self, text: str, ms: int = 2600):
        """状态栏左边短暂显示一句反馈。"""
        self._flash = f"{text}  {time.strftime('%H:%M')}"
        self._update_status()
        self.root.after(ms, lambda: (setattr(self, "_flash", ""), self._update_status()))

    def on_refresh_state(self):
        """刷新：从库里重读当前记录并重画列表/详情，不写库、不生成快照。

        与「保存」的区别：保存会额外存一份快照；刷新只做界面同步，
        定稿只读状态下也能用。未提交到库的输入框内容会被库里的值覆盖。
        """
        rec = self._current_record()
        self.refresh_samples()
        self.refresh_reactions()
        if rec:
            self._reload_current()
        self._update_status()
        self._flash_status("已刷新")

    def on_save_state(self):
        """保存：把当前状态刷到库里并重画详情，给一个明确的落库反馈。

        本程序是即时写库的（改一格就存），这个按钮负责「确认 + 刷新」：
        重新读一遍记录、刷新三个列表和详情页，状态栏显示保存时间。
        """
        rec = self._current_record()
        if rec and self.store.is_locked(rec[0], rec[1]):
            messagebox.showinfo("已定稿", "这条记录已定稿，不能再改。\n"
                                        "要修改请先点「已定稿 · 解锁」输入密码。",
                                parent=self.root)
            return
        self.refresh_samples()
        self.refresh_reactions()
        if rec:
            self._reload_current()
            self.store.save_snapshot(rec[0], rec[1], "save")
        self._update_status()
        self._flash_status("已保存")

    def on_toggle_lock(self):
        rec = self._current_record()
        if rec is None:
            messagebox.showinfo("先选一条记录", "在中间列表里点中一条药剂或反应，再点「定稿」。",
                                parent=self.root)
            return
        owner_type, oid, name = rec
        if self.store.is_locked(owner_type, oid):
            self._unlock_record(owner_type, oid, name)
        else:
            self._lock_record(owner_type, oid, name)

    def _lock_record(self, owner_type, oid, name):
        if not messagebox.askyesno(
                "定稿锁定",
                f"「{name}」定稿后将变成只读，不能再编辑。\n"
                "需要修改时输入登录密码即可解锁。\n\n确定定稿？",
                parent=self.root):
            return
        self.store.set_locked(owner_type, oid, True)
        self.store.save_snapshot(owner_type, oid, "finalize")
        self._reload_current()
        self._update_status()
        self._flash_status("已定稿")

    def _unlock_record(self, owner_type, oid, name):
        pwd = password_ask(self.root, "解锁", f"输入登录密码解锁「{name}」：")
        if not pwd:
            return
        who = self.user.get("name", "")
        if auth.verify(who, pwd) is None:
            messagebox.showerror("密码不对", "解锁失败：密码不正确。", parent=self.root)
            return
        self.store.set_locked(owner_type, oid, False)
        self._reload_current()
        self._update_status()
        self._flash_status("已解锁")

    def on_restore_version(self):
        """从最新快照恢复当前记录（保存版 / 定稿版，取较新的一份）。"""
        rec = self._current_record()
        if rec is None:
            messagebox.showinfo("先选一条记录",
                                "在中间列表里点中一条药剂或反应，再点「恢复」。",
                                parent=self.root)
            return
        owner_type, oid, name = rec
        snap = self.store.get_snapshot(owner_type, oid)
        if not snap:
            messagebox.showinfo(
                "没有快照",
                f"「{name}」还没有保存 / 定稿快照，无法恢复。\n"
                "先点一次「保存」或「定稿」会生成一份最新快照。",
                parent=self.root)
            return
        kind_label = "定稿" if snap["kind"] == "finalize" else "保存"
        if not messagebox.askyesno(
                "恢复快照",
                f"将把「{name}」恢复到最近一次【{kind_label}】的版本\n"
                f"（{snap.get('created', '')}）。\n\n"
                "当前未保存的改动会被这份快照覆盖。确定恢复？",
                parent=self.root):
            return
        self.store.restore_snapshot(owner_type, oid)
        self._reload_current()
        self._update_status()
        self._flash_status(f"已恢复（{kind_label}版）")

    # ------------------------------------------------------------ 样品详情
    def on_sample_pick(self, _e=None):
        sel = self.s_tree.selection()
        if not sel:
            return
        self.nb.select(0)
        self.show_sample(int(sel[0]))

    def show_sample(self, sid: int):
        row = self.store.sample(sid)
        if row is None:
            return
        self.nb.select(0)
        # 同一条记录刷新（比如刚保存完绘图）时保持滚动位置
        keep_pos = (self.cur_sample == sid)
        scroll = self.detail.canvas.yview()[0] if keep_pos else 0.0
        self.cur_sample = sid
        self.cur_reaction = None
        self.detail.clear()
        self._imgs.clear()
        body = self.detail.body

        # 标题行
        head = tk.Frame(body, bg=CLR_CARD)
        head.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(head, text=row["name"] or "（未命名）", bg=CLR_CARD, fg=CLR_INK,
                 font=(UI, 15, "bold")).pack(side="left")
        if row["code"]:
            tk.Label(head, text=f"  {row['code']}", bg=CLR_CARD, fg=CLR_TAG,
                     font=(MONO, 10)).pack(side="left")
        locked = self.store.is_locked("sample", sid)
        if locked:
            tk.Label(head, text=f"已定稿 {self.store.locked_at('sample', sid)}",
                     bg=CLR_CARD, fg=CLR_RED,
                     font=(UI, 8, "bold")).pack(side="left", padx=(10, 0))

        ops = tk.Frame(head, bg=CLR_CARD)
        ops.pack(side="right")
        tk.Button(ops, text="电子效应", relief="flat", bd=0, bg=CLR_CARD,
                  fg="#6a4fa3", font=(UI, 9), cursor="hand2",
                  command=lambda: self.on_effects(
                      row["smiles"] or "",
                      f"药剂 {row['name'] or row['code'] or sid}")).pack(side="left", padx=6)
        for t, cmd in (("编辑", self.on_sample_edit), ("删除", self.on_sample_delete)):
            fg = CLR_RED if t == "删除" else CLR_ACCENT
            b = tk.Button(ops, text=t, command=cmd, relief="flat", bd=0,
                          bg=CLR_CARD, fg=fg, font=(UI, 9), cursor="hand2")
            if locked:
                b.configure(state="disabled", fg="#b8c0cc", cursor="")
            b.pack(side="left", padx=6)

        # 结构图
        mol = chem.mol_from_record(row)
        img = chem.render(mol, 340, 240) if mol is not None else None
        if img is not None:
            photo = ImageTk.PhotoImage(img)
            self._imgs.append(photo)
            lbl = tk.Label(body, image=photo, bg=CLR_CARD, cursor="hand2")
            lbl.pack(anchor="w", padx=16, pady=(4, 8))
            lbl.bind("<Button-1>", lambda e, m=mol: self.show_big_structure(m))

        # 字段表
        grid = tk.Frame(body, bg=CLR_CARD)
        grid.pack(fill="x", padx=16)
        grid.columnconfigure(1, weight=1)
        r = 0
        for key, label in FIELDS_SAMPLE:
            val = row[key]
            if val in (None, ""):
                continue
            if key == "unit":
                continue                        # 已经并进「数量」里了
            if key == "mw":
                val = _num(val, ".3f")
            elif key == "amount":
                val = _amt(val, row["unit"])
            self._kv(grid, r, label, str(val), mono=key in ("smiles", "formula", "cas"))
            r += 1

        # 附件
        self._attachment_block(body, "sample", sid, locked=locked)

        # 归属集合
        if row["collection_id"]:
            c = self.store.one("SELECT name FROM collections WHERE id=?", (row["collection_id"],))
            if c:
                self._kv(grid, r, "所属集合", c["name"])

        self._polarity_block(body, self._structure_smiles("sample", sid, row), "")
        self._drawing_block(body, "sample", sid, locked=locked)
        self._notebook_block(body, "sample", sid, locked=locked)
        if keep_pos and scroll > 0:
            self.detail.after(40, lambda: self.detail.canvas.yview_moveto(scroll))

    def _kv(self, parent, row: int, key: str, val: str, mono=False):
        tk.Label(parent, text=key, bg=CLR_CARD, fg=CLR_DIM, font=(UI, 9),
                 anchor="w", width=9).grid(row=row, column=0, sticky="nw", pady=2)
        lbl = tk.Label(parent, text=val, bg=CLR_CARD, fg=CLR_INK,
                       font=(MONO if mono else UI, 10), anchor="w", justify="left",
                       wraplength=340)
        lbl.grid(row=row, column=1, sticky="nw", pady=2)

    def show_big_structure(self, mol):
        win = tk.Toplevel(self.root)
        win.title("结构式")
        img = chem.render(mol, 760, 560)
        if img is None:
            win.destroy()
            return
        photo = ImageTk.PhotoImage(img)
        lbl = tk.Label(win, image=photo, bg="white")
        lbl.image = photo
        lbl.pack(padx=8, pady=8)
        win.bind("<Escape>", lambda e: win.destroy())

    # ------------------------------------------------------------ 反应详情
    def on_reaction_pick(self, _e=None):
        sel = self.r_tree.selection()
        if not sel:
            return
        self.nb.select(1)
        self.show_reaction(int(sel[0]))

    def show_reaction(self, rid: int):
        row = self.store.reaction(rid)
        if row is None:
            return
        self.nb.select(1)
        # 同一条记录刷新（比如刚保存完绘图）时保持滚动位置
        keep_pos = (self.cur_reaction == rid)
        scroll = self.detail.canvas.yview()[0] if keep_pos else 0.0
        self.cur_reaction = rid
        self.cur_sample = None
        self.detail.clear()
        self._imgs.clear()
        body = self.detail.body

        head = tk.Frame(body, bg=CLR_CARD)
        head.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(head, text=row["title"] or "（未命名反应）", bg=CLR_CARD, fg=CLR_INK,
                 font=(UI, 15, "bold")).pack(side="left")
        if row["code"]:
            tk.Label(head, text=f"  {row['code']}", bg=CLR_CARD, fg=CLR_TAG,
                     font=(MONO, 10)).pack(side="left")
        locked = self.store.is_locked("reaction", rid)
        if locked:
            tk.Label(head, text=f"已定稿 {self.store.locked_at('reaction', rid)}",
                     bg=CLR_CARD, fg=CLR_RED,
                     font=(UI, 8, "bold")).pack(side="left", padx=(10, 0))

        ops = tk.Frame(head, bg=CLR_CARD)
        ops.pack(side="right")
        tk.Button(ops, text="电子效应", relief="flat", bd=0, bg=CLR_CARD,
                  fg="#6a4fa3", font=(UI, 9), cursor="hand2",
                  command=self.on_effects).pack(side="left", padx=6)
        b_tpl = tk.Button(ops, text="存为模板", relief="flat", bd=0, bg=CLR_CARD,
                          fg=CLR_TAG, font=(UI, 9), cursor="hand2",
                          command=self.on_reaction_save_template)
        for t, cmd in (("编辑", self.on_reaction_edit), ("删除", self.on_reaction_delete)):
            fg = CLR_RED if t == "删除" else CLR_ACCENT
            b = tk.Button(ops, text=t, command=cmd, relief="flat", bd=0,
                          bg=CLR_CARD, fg=fg, font=(UI, 9), cursor="hand2")
            if locked:
                b.configure(state="disabled", fg="#b8c0cc", cursor="")
            b.pack(side="left", padx=6)
        b_tpl.pack(side="left", padx=6)
        if locked:
            b_tpl.configure(state="disabled", fg="#b8c0cc", cursor="")

        grid = tk.Frame(body, bg=CLR_CARD)
        grid.pack(fill="x", padx=16, pady=(4, 8))
        grid.columnconfigure(1, weight=1)
        r = 0
        if row["yield_pct"] is not None:
            self._kv(grid, r, "产率", _pct(row["yield_pct"]) or "—")
            r += 1
        if row["conditions"]:
            self._kv(grid, r, "条件", row["conditions"])
            r += 1
        if row["created"]:
            self._kv(grid, r, "记录时间", row["created"])
            r += 1

        # 绘制区放在组成表前面：反应式是这条记录的脸面，别被大段操作文本挤到折叠线以下
        self._drawing_block(body, "reaction", rid, locked=locked)

        # 组成表（双击单元格就地编辑）
        self._components_block(body, rid, locked=locked)

        pol_a, pol_b = self.polarity_context()
        self._polarity_block(body, pol_a, pol_b)

        # 操作
        if row["procedure"]:
            tk.Label(body, text="操作", bg=CLR_CARD, fg=CLR_INK,
                     font=(UI, 11, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
            txt = tk.Text(body, height=8, wrap="word", bg="#fbfcfd", fg=CLR_INK,
                          font=(UI, 10), bd=1, relief="solid", padx=10, pady=8)
            txt.insert("1.0", row["procedure"])
            txt.configure(state="disabled")
            txt.pack(fill="x", padx=16, pady=(0, 8))

        if row["note"]:
            tk.Label(body, text=row["note"], bg=CLR_CARD, fg=CLR_DIM, font=(UI, 9),
                     wraplength=520, justify="left").pack(anchor="w", padx=16, pady=(0, 8))

        self._notebook_block(body, "reaction", rid, locked=locked)
        self._attachment_block(body, "reaction", rid, locked=locked)
        if keep_pos and scroll > 0:
            self.detail.after(40, lambda: self.detail.canvas.yview_moveto(scroll))

    # ------------------------------------------------------------ 组成表（可就地编辑）
    @staticmethod
    def _comp_cells(c) -> tuple:
        amt = ""
        if c["amount"] is not None:
            amt = _amt(c["amount"], c["unit"])
        mmol = stoich.row_mmol(c)
        mmol_s = f"{mmol:.2f}" if mmol is not None else "—"
        return (c["role"],
                c["s_name"] or c["label"] or "（未关联药剂）",
                _num(c["equivalents"]),
                amt, mmol_s)

    def _components_block(self, parent, rid: int, locked=False):
        comp = self.store.components(rid)
        head = tk.Frame(parent, bg=CLR_CARD)
        head.pack(fill="x", padx=16, pady=(10, 4))
        tk.Label(head, text="组成", bg=CLR_CARD, fg=CLR_INK,
                 font=(UI, 11, "bold")).pack(side="left")
        b_add = tk.Button(head, text="+ 添加", command=lambda: self.on_comp_add(rid),
                          relief="flat", bd=0, bg=CLR_CARD, fg=CLR_ACCENT,
                          font=(UI, 9), cursor="hand2")
        if locked:
            b_add.configure(state="disabled", fg="#b8c0cc", cursor="")
        b_add.pack(side="left", padx=8)
        tk.Label(head, text="已定稿，只读" if locked else
                 "双击改 · 改用量/当量自动重算其它行 · 右键删行",
                 bg=CLR_CARD, fg=CLR_RED if locked else "#a9b4c2",
                 font=(UI, 8)).pack(side="right")

        if not comp:
            tk.Label(parent, text="（还没有组成，点「+ 添加」加一条）", bg=CLR_CARD,
                     fg=CLR_DIM, font=(UI, 9)).pack(anchor="w", padx=16, pady=(0, 8))
            return

        tbl = ttk.Treeview(parent, columns=("role", "name", "eq", "amt", "mmol"),
                           show="headings", height=min(10, len(comp)),
                           selectmode="browse")
        for c, t, w in (("role", "角色", 80), ("name", "物质", 178),
                        ("eq", "当量", 58), ("amt", "用量", 112),
                        ("mmol", "摩尔量", 86)):
            tbl.heading(c, text=t)
            tbl.column(c, width=w, anchor="w" if c == "name" else "center")
        for c in comp:
            tbl.insert("", "end", iid=str(c["id"]), values=self._comp_cells(c))
        tbl.pack(fill="x", padx=16, pady=(0, 4))
        if not locked:
            tbl.bind("<Double-1>", lambda e, t=tbl: self._edit_comp_cell(t, e, rid))
            tbl.bind("<Button-3>", lambda e, t=tbl: self._comp_menu(t, e, rid))

        rep = stoich.yield_report([dict(r) for r in comp])
        s = stoich.summary_text([dict(r) for r in comp], rep)
        if s:
            fg = "#1a7f37" if rep.get("pct") is not None else CLR_DIM
            tk.Label(parent, text=s, bg=CLR_CARD, fg=fg, font=(UI, 8),
                     wraplength=560, justify="left").pack(anchor="w", padx=16, pady=(0, 8))

    def _comp_menu(self, tbl, event, rid: int):
        item = tbl.identify_row(event.y)
        if not item:
            return
        cid = int(item)
        menu = tk.Menu(tbl, tearoff=0, font=(UI, 9))
        menu.add_command(label="在对话框里编辑…",
                         command=lambda: self.on_comp_edit(rid, cid))
        menu.add_separator()
        menu.add_command(label="删除这条组成",
                         command=lambda: self.on_comp_delete(rid, cid))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _edit_comp_cell(self, tbl, event, rid: int):
        """双击单元格就地编辑：角色给下拉，其余给输入框。"""
        item = tbl.identify_row(event.y)
        col = tbl.identify_column(event.x)
        if not item or not col:
            return
        try:
            col_idx = int(col[1:]) - 1
        except ValueError:
            return
        if col_idx not in (0, 1, 2, 3):
            return
        if col_idx == 4:
            messagebox.showinfo("摩尔量是算出来的",
                                "摩尔量由用量、单位、分子量自动算得，不能直接填。\n"
                                "想按摩尔投料，把用量单位写成 mmol 就行。",
                                parent=self.root)
            return
        cid = int(item)
        comp = next((c for c in self.store.components(rid) if c["id"] == cid), None)
        if comp is None:
            return
        bbox = tbl.bbox(item, col)
        if not bbox:
            return
        x, y, w, h = bbox

        if col_idx == 1 and comp["sample_id"]:
            messagebox.showinfo(
                "这条关联了药剂",
                f"「{comp['s_name']}」来自药剂台账。\n"
                "要改名请到药剂页改，这里可以改角色、当量、用量。",
                parent=self.root)
            return

        if col_idx == 0:
            var = tk.StringVar(value=comp["role"] or "反应物")
            ed = ttk.Combobox(tbl, textvariable=var, values=ROLES,
                              state="readonly", font=(UI, 9))
        else:
            cur = {1: comp["label"] or "",
                   2: _num(comp["equivalents"]),
                   3: _amt(comp["amount"], comp["unit"])}[col_idx]
            var = tk.StringVar(value=cur)
            if col_idx in (2, 3):  # 当量 / 用量：允许输入小数（含全角标点）
                _bind_num_norm(var)
            ed = tk.Entry(tbl, textvariable=var, font=(UI, 9), bd=1, relief="solid",
                          bg="#fffdf0", justify="left" if col_idx == 1 else "center")

        ed.place(x=x, y=y, width=w, height=h)
        ed.focus_set()
        if isinstance(ed, tk.Entry):
            ed.select_range(0, "end")

        def save(_=None):
            if not ed.winfo_exists():
                return "break"
            val = var.get().strip()
            ed.destroy()
            self._apply_comp_cell(rid, cid, col_idx, val)
            return "break"

        def cancel(_=None):
            if ed.winfo_exists():
                ed.destroy()
            return "break"

        ed.bind("<Return>", save)
        ed.bind("<FocusOut>", save)
        ed.bind("<Escape>", cancel)
        if isinstance(ed, ttk.Combobox):
            ed.bind("<<ComboboxSelected>>", save)

    def _apply_comp_cell(self, rid: int, cid: int, col_idx: int, val: str):
        kw = {}
        if col_idx == 0:
            if val:
                kw["role"] = val
        elif col_idx == 1:
            kw["label"] = val or None
        elif col_idx == 2:
            try:
                kw["equivalents"] = float(norm_num(val)) if val else None
            except ValueError:
                messagebox.showwarning("当量格式不对", "当量要写数字，比如 1.2。", parent=self.root)
                return
        elif col_idx == 3:
            amount, unit = parse_amount(val)
            kw["amount"] = amount
            kw["unit"] = unit
        if not kw:
            return
        try:
            self.store.update_component(cid, **kw)
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self.root)
            return
        # 双向实时计算：改用量 / 改当量后，重算其它行的所需量与当量
        mode = {3: "amount", 2: "equiv"}.get(col_idx)
        if mode:
            comp = self.store.components(rid)
            updates, note = stoich.recalc([dict(r) for r in comp], cid, mode)
            if note:
                # 提示走状态栏，不弹窗打断输入
                self._flash_status(f"双向计算：{note}", 4200)
            for ucid, u in updates:
                try:
                    self.store.update_component(ucid, **u)
                except Exception as e:
                    messagebox.showerror("重算写入失败", str(e), parent=self.root)
                    break
        self.show_reaction(rid)

    def on_comp_add(self, rid: int):
        def done(data):
            try:
                self.store.add_component(rid, **data)
            except Exception as e:
                messagebox.showerror("添加失败", str(e), parent=self.root)
                return
            self.show_reaction(rid)
        ComponentDialog(self.root, self.store, done)

    def on_comp_edit(self, rid: int, cid: int):
        comp = next((c for c in self.store.components(rid) if c["id"] == cid), None)
        if comp is None:
            return

        def done(data):
            try:
                self.store.update_component(cid, **data)
            except Exception as e:
                messagebox.showerror("保存失败", str(e), parent=self.root)
                return
            self.show_reaction(rid)
        ComponentDialog(self.root, self.store, done, existing=dict(comp))

    def on_comp_delete(self, rid: int, cid: int):
        comp = next((c for c in self.store.components(rid) if c["id"] == cid), None)
        if comp is None:
            return
        name = comp["s_name"] or comp["label"] or "这一条"
        if not messagebox.askyesno("删除组成", f"删掉「{name}」？", parent=self.root):
            return
        self.store.delete_component(cid)
        self.show_reaction(rid)

    # ------------------------------------------------------------ 附件
    def _attachment_block(self, parent, owner_type: str, owner_id: int,
                          locked=False):
        rows = self.store.attachments(owner_type, owner_id)
        head = tk.Frame(parent, bg=CLR_CARD)
        head.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(head, text="附件", bg=CLR_CARD, fg=CLR_INK,
                 font=(UI, 11, "bold")).pack(side="left")
        b_add = tk.Button(head, text="+ 添加",
                          command=lambda: self.on_attach_add(owner_type, owner_id),
                          relief="flat", bd=0, bg=CLR_CARD, fg=CLR_ACCENT,
                          font=(UI, 9), cursor="hand2")
        if locked:
            b_add.configure(state="disabled", fg="#b8c0cc", cursor="")
        b_add.pack(side="left", padx=8)

        if not rows:
            tk.Label(parent, text="（还没有附件，双击文件可以直接打开）", bg=CLR_CARD,
                     fg=CLR_DIM, font=(UI, 9)).pack(anchor="w", padx=16, pady=(0, 8))
            return

        for a in rows:
            row = tk.Frame(parent, bg="#fafbfc", highlightthickness=1,
                           highlightbackground=CLR_LINE)
            row.pack(fill="x", padx=16, pady=2)
            name = a["title"] or os.path.basename(a["path"] or "")
            tk.Label(row, text=f"{a['kind'] or '文件'}", bg="#fafbfc", fg=CLR_TAG,
                     font=(UI, 8), width=6, anchor="w").pack(side="left", padx=(8, 4), pady=5)
            lbl = tk.Label(row, text=name, bg="#fafbfc", fg=CLR_ACCENT, font=(UI, 9),
                           anchor="w", cursor="hand2")
            lbl.pack(side="left", fill="x", expand=True)
            lbl.bind("<Button-1>", lambda e, p=a["path"]: open_path(p) if p else None)
            b_rm = tk.Button(row, text="移除",
                             command=lambda aid=a["id"], ot=owner_type, oi=owner_id:
                             self.on_attach_remove(aid, ot, oi),
                             relief="flat", bd=0, bg="#fafbfc", fg=CLR_DIM,
                             font=(UI, 8), cursor="hand2")
            if locked:
                b_rm.configure(state="disabled", fg="#c8ccd4", cursor="")
            b_rm.pack(side="right", padx=6)

    def on_attach_add(self, owner_type: str, owner_id: int):
        paths = filedialog.askopenfilenames(parent=self.root, title="选择附件")
        if not paths:
            return
        for p in paths:
            ext = os.path.splitext(p)[1].lower().lstrip(".")
            kind = {"pdf": "PDF", "png": "图片", "jpg": "图片", "jpeg": "图片",
                    "xlsx": "表格", "csv": "表格", "docx": "文档"}.get(ext, ext.upper() or "文件")
            if any(k in os.path.basename(p).lower() for k in ("nmr", "fid", "1h", "13c")):
                kind = "NMR"
            self.store.import_attachment(owner_type, owner_id, p, kind)
        if owner_type == "sample":
            self.show_sample(owner_id)
        else:
            self.show_reaction(owner_id)
        self._update_status()

    def on_attach_remove(self, aid: int, owner_type: str, owner_id: int):
        self.store.delete_attachment(aid)
        if owner_type == "sample":
            self.show_sample(owner_id)
        else:
            self.show_reaction(owner_id)
        self._update_status()

    # ------------------------------------------------------------ 绘制区
    def on_draw_toolbar(self):
        """顶部「绘制」：给当前选中的药剂或反应开一张新图。"""
        if self.cur_sample:
            if self._guard_locked("sample", self.cur_sample, "改绘制"):
                return
            self.open_drawpad("sample", self.cur_sample)
        elif self.cur_reaction:
            if self._guard_locked("reaction", self.cur_reaction, "改绘制"):
                return
            self.open_drawpad("reaction", self.cur_reaction)
        else:
            messagebox.showinfo("先选一条记录",
                                "先在中间列表选一个药剂或反应，再点「绘制」。",
                                parent=self.root)

    def open_drawpad(self, owner_type, owner_id, drawing=None):
        initial = ""
        if drawing is None and owner_type == "sample":
            row = self.store.sample(owner_id)
            initial = (row["smiles"] or "") if row else ""
        return drawpad.open_drawpad(
            self.root, self.store, owner_type, owner_id,
            drawing=drawing, initial_smiles=initial,
            on_smiles=lambda s: self.apply_drawn_smiles(owner_type, owner_id, s),
            on_saved=lambda did: self._after_draw_saved(owner_type, owner_id))

    def apply_drawn_smiles(self, owner_type, owner_id, smi):
        """药剂的结构式画完，把 SMILES/molfile/分子式/分子量回填到台账。"""
        if owner_type != "sample" or not smi or ">>" in smi:
            return
        info = chem.analyze(smi)
        if "error" in info:
            return
        self.store.update_sample(owner_id, smiles=info["smiles"],
                                 molfile=info["molfile"],
                                 formula=info["formula"], mw=info["mw"])
        self.refresh_samples()

    def _after_draw_saved(self, owner_type, owner_id):
        self.refresh_samples()
        self.refresh_reactions()
        if owner_type == "sample":
            self.show_sample(owner_id)
        else:
            self.show_reaction(owner_id)
        self._update_status()

    def _drawing_block(self, parent, owner_type, owner_id, locked=False):
        rows = self.store.drawings(owner_type, owner_id)
        head = tk.Frame(parent, bg=CLR_CARD)
        head.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(head, text="绘制", bg=CLR_CARD, fg=CLR_INK,
                 font=(UI, 11, "bold")).pack(side="left")
        b_new = tk.Button(head, text="+ 新建",
                          command=lambda: self.open_drawpad(owner_type, owner_id),
                          relief="flat", bd=0, bg=CLR_CARD, fg=CLR_GREEN,
                          font=(UI, 9), cursor="hand2")
        if locked:
            b_new.configure(state="disabled", fg="#b8c0cc", cursor="")
        b_new.pack(side="left", padx=8)
        tk.Label(head, text="结构式 / 反应式 · 可再编辑", bg=CLR_CARD, fg=CLR_DIM,
                 font=(UI, 8)).pack(side="left")

        if not rows:
            tk.Label(parent, text="（还没有绘制，点「+ 新建」画结构式或反应式）",
                     bg=CLR_CARD, fg=CLR_DIM, font=(UI, 9)).pack(anchor="w", padx=16)
            return

        for d in rows:
            card = tk.Frame(parent, bg="#fafbfc", highlightthickness=1,
                            highlightbackground=CLR_LINE)
            card.pack(fill="x", padx=16, pady=3)
            top = tk.Frame(card, bg="#fafbfc")
            top.pack(fill="x")
            try:
                sk = drawpad.Sketch.from_json(d["data"])
                x0, y0, x1, y1 = sk.bounds(36.0)
                bw = max(1.0, x1 - x0)
                bh = max(1.0, y1 - y0)
                # 右侧文字块已隐藏；缩略图改为**铺满卡片宽度**，高度按图示比例算，
                # 这样不会留下大片空白，也不会有多余留白边。
                thumb = tk.Label(top, bg="#fafbfc", cursor="hand2")
                thumb.pack(fill="x")
                thumb.bind("<Button-1>",
                           lambda e, did=d["id"]: self.show_big_drawing(did))
                state = {"w": 0, "job": None}

                def _fit(_e=None, sk=sk, lbl=thumb, holder=top, st=state,
                         bw=bw, bh=bh):
                    w = max(200, holder.winfo_width())
                    if abs(w - st["w"]) < 8:
                        return
                    if st["job"]:
                        try:
                            holder.after_cancel(st["job"])
                        except Exception:
                            pass

                    def _render():
                        st["w"] = w
                        st["job"] = None
                        h = max(70, int(round(w * bh / bw)))
                        ph = ImageTk.PhotoImage(sk.render_png(w, h))
                        lbl.configure(image=ph)
                        lbl.image = ph        # 挂在控件上，避免被 GC
                    st["job"] = holder.after(120, _render)

                top.bind("<Configure>", _fit)
            except Exception:
                pass

            # 操作按钮单独一行，避免右栏窄的时候被缩略图挤出可视区
            ops = tk.Frame(card, bg="#fafbfc")
            ops.pack(fill="x", padx=10, pady=(0, 6))
            tk.Button(ops, text="放大",
                      command=lambda did=d["id"]: self.show_big_drawing(did),
                      relief="flat", bd=0, bg="#fafbfc", fg=CLR_DIM,
                      font=(UI, 8), cursor="hand2").pack(side="left")
            b_del = tk.Button(ops, text="删除",
                              command=lambda did=d["id"]: self.on_draw_delete(
                                  did, owner_type, owner_id),
                              relief="flat", bd=0, bg="#fafbfc", fg=CLR_DIM,
                              font=(UI, 8), cursor="hand2")
            if locked:
                b_del.configure(state="disabled", fg="#c8ccd4", cursor="")
            b_del.pack(side="right", padx=4)
            b_edit = tk.Button(ops, text="编辑",
                               command=lambda dd=d: self.open_drawpad(
                                   owner_type, owner_id, drawing=dd),
                               relief="flat", bd=0, bg="#fafbfc", fg=CLR_ACCENT,
                               font=(UI, 8), cursor="hand2")
            if locked:
                b_edit.configure(state="disabled", fg="#c8ccd4", cursor="")
            b_edit.pack(side="right", padx=4)

    def show_big_drawing(self, did):
        d = self.store.drawing(did)
        if d is None:
            return
        win = tk.Toplevel(self.root)
        win.title(d["title"] or "绘制")
        try:
            img = drawpad.Sketch.from_json(d["data"]).render_png(1080, 780)
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(win, image=photo, bg="white")
            lbl.image = photo
            lbl.pack(padx=8, pady=8)
        except Exception as e:
            tk.Label(win, text=f"这张图渲染不了：{e}").pack(padx=20, pady=20)
        win.bind("<Escape>", lambda e: win.destroy())

    def on_draw_delete(self, did, owner_type, owner_id):
        if not messagebox.askyesno("确认删除", "删掉这张绘制？", parent=self.root):
            return
        self.store.delete_drawing(did)
        self._after_draw_saved(owner_type, owner_id)

    # ------------------------------------------------------------ 实验笔记
    def on_calendar(self):
        """月历视图：按天回溯做过的实验，点条目直接打开。"""
        calwin.CalendarWindow(self.root, self.store, self._open_record_from_calendar)

    def _open_record_from_calendar(self, kind, oid):
        if kind == "sample":
            self.show_sample(oid)
        else:
            self.show_reaction(oid)

    def on_notebook_toolbar(self):
        """工具栏「笔记」：给当前选中的记录打开块式笔记。"""
        if self.cur_sample:
            if self._guard_locked("sample", self.cur_sample, "改笔记"):
                return
            self.open_notebook("sample", self.cur_sample)
        elif self.cur_reaction:
            if self._guard_locked("reaction", self.cur_reaction, "改笔记"):
                return
            self.open_notebook("reaction", self.cur_reaction)
        else:
            messagebox.showinfo("先选一条记录",
                                "先在中间列表选一个药剂或反应，再点「笔记」。\n"
                                "笔记按块记：文本、步骤、化学、表格、计算。",
                                parent=self.root)

    def _record_label(self, owner_type: str, owner_id: int) -> tuple[str, str]:
        if owner_type == "sample":
            row = self.store.sample(owner_id)
            if row is None:
                return f"药剂 {owner_id}", ""
            name = row["name"] or f"药剂 {owner_id}"
            code = f"（{row['code']}）" if row["code"] else ""
            sub = " · ".join(x for x in ("药剂", row["formula"] or "",
                                         _num(row["mw"], ".2f")) if x)
            return f"{name}{code}", sub
        row = self.store.reaction(owner_id)
        if row is None:
            return f"反应 {owner_id}", ""
        return (f"{row['code'] + ' ' if row['code'] else ''}{row['title']}",
                " · ".join(x for x in ("反应", row["created"] or "") if x))

    def open_notebook(self, owner_type, owner_id):
        title, subtitle = self._record_label(owner_type, owner_id)
        return notebook.open_notebook(
            self.root, self.store, owner_type, owner_id,
            title=title, subtitle=subtitle,
            on_close=lambda: self._after_notebook_closed(owner_type, owner_id))

    def _after_notebook_closed(self, owner_type, owner_id):
        if owner_type == "sample" and self.cur_sample == owner_id:
            self.show_sample(owner_id)
        elif owner_type == "reaction" and self.cur_reaction == owner_id:
            self.show_reaction(owner_id)
        self._update_status()

    def quick_note(self, owner_type, owner_id):
        """不打开整本笔记，直接记一条文本块，然后进编辑。"""
        bid = self.store.add_block(
            owner_type, owner_id, "text",
            notebook.dump_content(notebook.default_content("text")))
        win = self.open_notebook(owner_type, owner_id)
        win.focus_block(bid)
        self._update_status()

    def _notebook_block(self, parent, owner_type, owner_id, locked=False):
        rows = self.store.blocks(owner_type, owner_id)
        counts = self.store.block_counts(owner_type, owner_id)

        head = tk.Frame(parent, bg=CLR_CARD)
        head.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(head, text="实验笔记", bg=CLR_CARD, fg=CLR_INK,
                 font=(UI, 11, "bold")).pack(side="left")
        b_open = tk.Button(head, text="打开笔记本",
                           command=lambda: self.open_notebook(owner_type, owner_id),
                           relief="flat", bd=0, bg=CLR_CARD, fg="#a06a1b",
                           font=(UI, 9), cursor="hand2")
        b_note = tk.Button(head, text="+ 记一笔",
                           command=lambda: self.quick_note(owner_type, owner_id),
                           relief="flat", bd=0, bg=CLR_CARD, fg=CLR_GREEN,
                           font=(UI, 9), cursor="hand2")
        if locked:
            for b in (b_open, b_note):
                b.configure(state="disabled", fg="#b8c0cc", cursor="")
        b_open.pack(side="left", padx=10)
        b_note.pack(side="left")
        if locked:
            tk.Label(head, text="已定稿，笔记只读", bg=CLR_CARD, fg=CLR_RED,
                     font=(UI, 8)).pack(side="right")

        if not rows:
            tk.Label(parent, text="（还没有笔记。按块记：文本、步骤、化学、表格、计算）",
                     bg=CLR_CARD, fg=CLR_DIM,
                     font=(UI, 9)).pack(anchor="w", padx=16)
            return

        parts = [f"{notebook.KINDS[k]} {counts[k]}" for k in notebook.KINDS
                 if counts.get(k)]
        tk.Label(parent, text=f"{len(rows)} 块 · " + " / ".join(parts),
                 bg=CLR_CARD, fg=CLR_DIM, font=(UI, 8)).pack(anchor="w", padx=16)

        card = tk.Frame(parent, bg="#fbfcfe", highlightthickness=1,
                        highlightbackground=CLR_LINE)
        card.pack(fill="x", padx=16, pady=(4, 6))
        preview_texts = []
        for i, b in enumerate(rows[:4]):
            content = notebook.load_content(b)
            text = notebook.summary(b["kind"], content).replace("\n", " ")
            # 预览不再硬截断到 29 字：换行展示全文（过长才收尾）
            if len(text) > 200:
                text = text[:199] + "…"
            row = tk.Frame(card, bg="#fbfcfe", cursor="hand2")
            row.pack(fill="x", padx=8, pady=2)
            bg, fg = notebook.KIND_COLORS.get(b["kind"], ("#eef2f8", CLR_INK))
            tk.Label(row, text=notebook.KINDS.get(b["kind"], b["kind"]), bg=bg,
                     fg=fg, font=(UI, 8, "bold"), padx=6).pack(side="left")

            # 正文用只读 Text：中文强制宋体、西文 Times New Roman（逐字切标签）
            lbl = tk.Text(row, height=1, wrap="word", bd=0, relief="flat",
                          bg="#fbfcfe", highlightthickness=0, cursor="hand2",
                          fg=CLR_INK, font=(F_LATIN, CONTENT_SIZE))
            lbl.tag_configure("pv", font=(F_LATIN, CONTENT_SIZE),
                              foreground=CLR_INK)
            lbl.tag_configure("pv_cjk", font=(F_CJK, CONTENT_SIZE),
                             foreground=CLR_INK)
            lbl.insert("end", f"{i + 1:02d}  ", ("pv",))
            insert_mixed(lbl, text, "pv", "pv_cjk")
            lbl.configure(state="disabled")
            lbl.pack(side="left", fill="x", expand=True, padx=(8, 0))
            preview_texts.append(lbl)
            for w in (row, lbl):
                w.bind("<Button-1>",
                       lambda e, ot=owner_type, oi=owner_id:
                       self.open_notebook(ot, oi))

        # 面板宽度稳定后，按「实际显示行数」设每个预览块的高度，避免空白被撑高。
        # Text 在拿到真实宽度前 winfo_width() 可能为 0/1，displaylines 会误判成很多行，
        # 所以宽度没就绪就延迟重试，就绪后再一次性设准。
        def _fit_preview(_=None, depth=0):
            if depth > 12:
                return
            ready = True
            for tx in preview_texts:
                tx.update_idletasks()
                if tx.winfo_width() <= 1:
                    ready = False
                    continue
                try:
                    n = int(tx.count("1.0", "end-1c", "displaylines")[0])
                except Exception:
                    n = 1
                n = max(1, n)
                if tx.cget("height") != n:
                    tx.configure(height=n)
            if not ready and depth < 12:
                card.after(40, lambda d=depth + 1: _fit_preview(depth=d))

        card.bind("<Configure>", _fit_preview)
        card.after(50, _fit_preview)
        card.after(250, _fit_preview)

        more = len(rows) - 4
        foot = tk.Frame(card, bg="#fbfcfe")
        foot.pack(fill="x", padx=8, pady=(2, 6))
        tk.Label(foot, text=(f"还有 {more} 块…" if more > 0 else "点任意一行打开整本笔记"),
                 bg="#fbfcfe", fg="#9aa6b3", font=(UI, 8)).pack(side="left")

    # ------------------------------------------------------------ 空态
    def _show_empty(self):
        self.detail.clear()
        body = self.detail.body
        tk.Label(body, text="ELN", bg=CLR_CARD, fg="#c9d3e0",
                 font=(UI, 30, "bold")).pack(pady=(80, 8))
        tk.Label(body, text="左边选集合，中间选一条，这里显示详情",
                 bg=CLR_CARD, fg=CLR_DIM, font=(UI, 10)).pack()
        tk.Label(body, text="Ctrl+N 新建药剂    Ctrl+F 搜索    Ctrl+E 电子效应    "
                            "Ctrl+Shift+B 笔记    F5 刷新    F1 帮助",
                 bg=CLR_CARD, fg="#a9b4c2", font=(UI, 9)).pack(pady=(6, 0))

    # ------------------------------------------------------------ 搜索
    def on_search(self):
        mode = self.search_mode.get()
        kw = self.search_entry.get().strip()
        if not kw:
            self._filter_ids = None
            self._reaction_ids = None
            self.refresh_samples()
            self.refresh_reactions()
            return

        if mode == "文本":
            self._filter_ids = None
            self._reaction_ids = None
            self.refresh_samples()
            self.refresh_reactions()
            self.nb.select(0)
            self._update_status()
            return

        records = self.store.all_molfiles()
        if mode == "子结构":
            hits = set(chem.substructure_hits(kw, records))
        else:
            hits = {i for i, s in chem.similarity_hits(kw, records, 0.3)}

        self._filter_ids = hits
        self._reaction_ids = self.store.reaction_ids_by_samples(hits)
        self.refresh_samples()
        self.refresh_reactions()
        self.nb.select(0)
        self._update_status()
        if not hits:
            messagebox.showinfo("没有命中",
                                f"没有药剂含有这个结构。\n\n查询：{kw}\n"
                                "子结构检索的速度依赖结构字段，先给药剂填上 SMILES 再试。",
                                parent=self.root)

    def on_search_clear(self):
        self.search_entry.delete(0, "end")
        self._filter_ids = None
        self._reaction_ids = None
        self.refresh_samples()
        self.refresh_reactions()
        self._update_status()

    # ------------------------------------------------------------ 浏览器访问
    def on_open_web(self):
        """起本地 Web 服务，用浏览器浏览 / 搜索 / 编辑记录。"""
        try:
            import webapp
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("浏览器访问", f"加载失败：{exc}", parent=self.root)
            return
        url = getattr(self, "_web_url", None)
        if url:
            webbrowser.open(url)
            self._flash_status(f"浏览器访问：{url}")
            return

        lan = messagebox.askyesnocancel(
            "浏览器访问",
            "是否允许同一局域网内的其他电脑 / 手机访问？\n\n"
            "「否」＝只本机可看（最安全）\n"
            "「是」＝开放到局域网，自动生成访问口令\n\n"
            "（端口 8765 起，被占用会自动往后找）",
            parent=self.root)
        if lan is None:
            return
        try:
            if lan:
                token = webapp.new_token()
                self._web_url = webapp.start(host="0.0.0.0", token=token,
                                             db=self.store.path)
                self._web_token = token
                try:                      # 顺手把地址复制到剪贴板，方便发到手机
                    self.root.clipboard_clear()
                    self.root.clipboard_append(self._web_url)
                except Exception:
                    pass
                messagebox.showinfo(
                    "局域网访问已开启",
                    f"本机访问：\n{self._web_url}\n\n"
                    "其他设备（同一 Wi-Fi）打开上面的地址即可。\n"
                    f"访问口令：{token}\n\n"
                    "地址已复制到剪贴板，可直接发到手机。\n"
                    "提示：重启程序或关闭 ELN 后失效；\n"
                    "若手机打不开，检查 Windows 防火墙是否允许 Python 的专用网络。",
                    parent=self.root)
            else:
                self._web_url = webapp.start(db=self.store.path)
            self._flash_status(f"浏览器访问：{self._web_url}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("浏览器访问", f"启动失败：{exc}", parent=self.root)

    # ------------------------------------------------------------ 导入导出
    def on_export_menu(self):
        """合并的导出入口：记录文档 + 可迁移包 + 数据交换。"""
        m = tk.Menu(self.root, tearoff=0, font=(UI, 9))
        m.add_command(label="当前记录 → PDF…", command=self.on_export_pdf)
        m.add_command(label="当前记录 → DOCX…", command=self.on_export_docx)
        m.add_separator()
        m.add_command(label="当前记录 → Markdown 包（zip）…",
                      command=lambda: self._export_pack("md", "record"))
        m.add_command(label="当前记录 → .eln 标准包（RO-Crate）…",
                      command=lambda: self._export_pack("eln", "record"))
        m.add_command(label="当前集合 → Markdown 包（zip）…",
                      command=lambda: self._export_pack("md", "collection"))
        m.add_command(label="整库 → .eln 标准包（RO-Crate）…",
                      command=lambda: self._export_pack("eln", "all"))
        m.add_separator()
        m.add_command(label="药剂表 → CSV…（当前列表）", command=self.on_export_csv)
        m.add_command(label="药剂结构 → SDF…（当前列表）", command=self.on_export_sdf)
        x = self._btn_export.winfo_rootx()
        y = self._btn_export.winfo_rooty() + self._btn_export.winfo_height()
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def _cur_record(self):
        """当前详情页指向的记录，返回 (owner_type, oid) 或 None。"""
        if getattr(self, "cur_reaction", None):
            return "reaction", self.cur_reaction
        if getattr(self, "cur_sample", None):
            return "sample", self.cur_sample
        return None

    def _export_record(self, builder, ext, desc):
        cur = self._cur_record()
        if cur is None:
            messagebox.showinfo("还没有选记录", "先在左中两栏选中一条药剂或反应，再导出。",
                                parent=self.root)
            return
        owner_type, oid = cur
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=ext,
                                            filetypes=[(desc, f"*{ext}")],
                                            initialfile=f"ELN-{owner_type}-{oid}{ext}")
        if not path:
            return
        try:
            content = recexport.gather(self.store, owner_type, oid)
            if content is None:
                messagebox.showwarning("记录不存在", "这条记录可能已被删除。",
                                       parent=self.root)
                return
            builder(content, path)
        except ImportError as e:
            messagebox.showerror(
                "缺导出库",
                f"导出 {desc} 需要 {e.name} 这个库，源码环境装一下：\n"
                f"pip install {e.name}\n"
                "（requirements.txt 里有，便携版自带）", parent=self.root)
            return
        except Exception as e:
            messagebox.showerror("导出失败", f"{type(e).__name__}: {e}", parent=self.root)
            return
        self._flash_status(f"已导出 {os.path.basename(path)}")
        messagebox.showinfo("导出完成", f"写了\n{path}", parent=self.root)

    def on_export_pdf(self):
        self._export_record(recexport.build_pdf, ".pdf", "PDF")

    def on_export_docx(self):
        self._export_record(recexport.build_docx, ".docx", "Word 文档")

    def _export_pack(self, kind: str, scope: str):
        """可迁移包导出：Markdown zip / .eln（RO-Crate）。

        kind: md | eln   scope: record | collection | all
        """
        cur = self._cur_record()
        if scope == "record" and cur is None:
            messagebox.showinfo("还没有选记录",
                                "先在左中两栏选中一条药剂或反应，再导出。",
                                parent=self.root)
            return
        if scope == "record":
            initial = f"ELN-{_safe_zipname(cur[2])}.zip"
        elif scope == "collection":
            initial = "ELN-当前集合.zip"
        else:
            initial = f"ELN-整库-{time.strftime('%Y%m%d')}.zip"
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".zip",
                                            filetypes=[("ZIP", "*.zip")],
                                            initialfile=initial)
        if not path:
            return
        try:
            if scope == "record":
                n = (packexport.export_md_zip(self.store, path,
                                              owner_type=cur[0], oid=cur[1])
                     if kind == "md" else
                     packexport.export_eln_zip(self.store, path,
                                               owner_type=cur[0], oid=cur[1],
                                               root_name=cur[2]))
            elif scope == "collection":
                n = (packexport.export_md_zip(self.store, path, coll_id=self.cur_coll)
                     if kind == "md" else
                     packexport.export_eln_zip(self.store, path,
                                               coll_id=self.cur_coll))
            else:
                n = (packexport.export_md_zip(self.store, path) if kind == "md"
                     else packexport.export_eln_zip(self.store, path))
        except Exception as e:
            messagebox.showerror("导出失败", f"{type(e).__name__}: {e}", parent=self.root)
            return
        if not n:
            messagebox.showinfo("没有可打包的", "这个范围里还没有记录。", parent=self.root)
            return
        self._flash_status(f"已打包 {n} 条记录")
        messagebox.showinfo("导出完成", f"打了 {n} 条记录到\n{path}", parent=self.root)

    def on_import_sdf(self):
        path = filedialog.askopenfilename(parent=self.root, title="导入 SDF",
                                          filetypes=[("SDF", "*.sdf *.mol"), ("所有文件", "*.*")])
        if not path:
            return
        rows = chem.read_sdf(path)
        if not rows:
            messagebox.showwarning("没读到东西", "这个文件里没有可解析的结构。", parent=self.root)
            return
        for r in rows:
            r["collection_id"] = self.cur_coll
            self.store.add_sample(**r)
        self.refresh_all()
        messagebox.showinfo("导入完成", f"导入了 {len(rows)} 条药剂。", parent=self.root)

    def on_export_sdf(self):
        rows = self.store.samples(self.cur_coll, self._kw())
        rows = [r for r in rows if r["molfile"]]
        if not rows:
            messagebox.showinfo("没有可导出的", "当前列表里没有带结构的药剂。", parent=self.root)
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".sdf",
                                            filetypes=[("SDF", "*.sdf")],
                                            initialfile="ELN-export.sdf")
        if not path:
            return
        n = chem.write_sdf(path, rows)
        messagebox.showinfo("导出完成", f"写了 {n} 条结构到\n{path}", parent=self.root)

    def on_export_csv(self):
        rows = self.store.samples(self.cur_coll, self._kw())
        if not rows:
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")],
                                            initialfile="ELN-export.csv")
        if not path:
            return
        cols = ["id", "code", "name", "cas", "formula", "mw", "amount", "unit",
                "purity", "state", "location", "note"]
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["ID", "编号", "名称", "CAS", "分子式", "分子量",
                        "数量", "单位", "纯度", "状态", "位置", "备注"])
            for r in rows:
                w.writerow([r[c] if c not in ("name", "code") else (r[c] or "") for c in cols])
        messagebox.showinfo("导出完成", f"写了 {len(rows)} 条到\n{path}", parent=self.root)

    def on_backup(self):
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".db",
                                            filetypes=[("SQLite", "*.db")],
                                            initialfile="eln-backup.db")
        if not path:
            return
        self.store.backup_to(path)
        messagebox.showinfo("备份完成", f"已保存到\n{path}\n\n"
                                        "注意：附件单独存在 attachments/ 目录，要一起备份。",
                            parent=self.root)

    # ------------------------------------------------------------ 增删改（占位，由 dialogs 模块实现）
    def on_sample_new(self):
        SampleDialog(self, self.store, None, self.cur_coll, self._after_sample_saved)

    def on_sample_edit(self):
        if not self.cur_sample:
            return
        if self._guard_locked("sample", self.cur_sample):
            return
        SampleDialog(self, self.store, self.store.sample(self.cur_sample),
                     self.cur_coll, self._after_sample_saved)

    def _after_sample_saved(self, sid):
        self.refresh_samples()
        self.show_sample(sid)

    def on_sample_delete(self):
        if not self.cur_sample:
            return
        if self._guard_locked("sample", self.cur_sample, "删除"):
            return
        row = self.store.sample(self.cur_sample)
        if not messagebox.askyesno("确认删除",
                                   f"删除「{row['name']}」？\n附件记录也会一起删。",
                                   parent=self.root):
            return
        self.store.delete_sample(self.cur_sample)
        self.cur_sample = None
        self.refresh_samples()
        self._show_empty()
        self._update_status()

    def on_reaction_new(self):
        ReactionDialog(self, self.store, None, self.cur_coll, self._after_reaction_saved)

    def on_reaction_edit(self):
        if not self.cur_reaction:
            return
        if self._guard_locked("reaction", self.cur_reaction):
            return
        ReactionDialog(self, self.store, self.store.reaction(self.cur_reaction),
                       self.cur_coll, self._after_reaction_saved)

    def _after_reaction_saved(self, rid):
        self.refresh_reactions()
        self.show_reaction(rid)

    def on_reaction_save_template(self):
        """把当前反应存成模板（标题/条件/操作/组成），供以后新建时一键载入。"""
        rid = self.cur_reaction
        row = self.store.reaction(rid) if rid else None
        if row is None:
            return
        name = simpledialog.askstring("存为模板", "模板名字：",
                                      initialvalue=row["title"] or "", parent=self.root)
        if not name or not name.strip():
            return
        name = name.strip()
        comps = [{"sample_id": c["sample_id"], "label": c["label"] or "",
                  "role": c["role"], "equivalents": c["equivalents"],
                  "amount": c["amount"], "unit": c["unit"] or "g"}
                 for c in self.store.components(rid)]
        content = json.dumps({"title": row["title"] or "",
                              "conditions": row["conditions"] or "",
                              "procedure": row["procedure"] or "",
                              "components": comps}, ensure_ascii=False)
        self.store.add_template(name, content)
        self._flash_status(f"已存模板「{name}」，下次新建反应可载入")

    def on_reaction_delete(self):
        if not self.cur_reaction:
            return
        if self._guard_locked("reaction", self.cur_reaction, "删除"):
            return
        row = self.store.reaction(self.cur_reaction)
        if not messagebox.askyesno("确认删除", f"删除反应「{row['title']}」？", parent=self.root):
            return
        self.store.delete_reaction(self.cur_reaction)
        self.cur_reaction = None
        self.refresh_reactions()
        self._show_empty()
        self._update_status()

    # ------------------------------------------------------------ 电子效应
    def effects_context(self) -> tuple[str, str]:
        """给分析窗口取当前记录的结构：药剂直接用，反应优先取产物。"""
        if self.cur_sample:
            row = self.store.sample(self.cur_sample)
            if row is not None and row["smiles"]:
                return row["smiles"], f"药剂 {row['name'] or row['code'] or self.cur_sample}"
        if self.cur_reaction:
            row = self.store.reaction(self.cur_reaction)
            title = (row["title"] if row else None) or "未命名反应"
            comps = self.store.components(self.cur_reaction)
            for role in ("产物", "反应物", "试剂"):
                for c in comps:
                    if c["role"] == role and c["s_smiles"]:
                        nm = c["s_name"] or "未命名"
                        return c["s_smiles"], f"反应 {title} · {role} {nm}"
        return "", ""

    def on_effects(self, smiles: str = "", label: str = ""):
        """工具栏 / 详情 / Ctrl+E：打开基团电子效应分析窗口。"""
        ok, why = effects.available()
        if not ok:
            messagebox.showwarning(
                "效应引擎缺失",
                why + "\n\nELN 的其它功能不受影响；补齐内置引擎文件后重开即可。")
            return
        if not smiles:
            smiles, label = self.effects_context()
        return effectswin.open_effects(self.root, self, smiles, label)

    # ------------------------------------------------------------ Ketcher
    def on_ketcher_toolbar(self):
        """工具栏「Ketcher」：直接开 Ketcher，省掉先进「绘制」那一步。

        选中药剂时载入它的结构，保存后回填到该药剂；
        没选药剂则新建一条药剂接住结构。
        """
        try:
            import ketcherwin
        except Exception as e:                       # noqa: BLE001
            messagebox.showerror("打不开 Ketcher", str(e))
            return
        if not ketcherwin.is_built():
            messagebox.showwarning(
                "Ketcher 还没构建",
                "找不到 vendor\\ketcher-app\\dist。\n\n"
                "在项目目录双击 tools\\build_ketcher.bat 构建一次即可"
                "（需要 Node.js，约 1–2 分钟；构建产物随程序一起用，"
                "之后不用联网）。")
            return

        sid = self.cur_sample
        if sid and self._guard_locked("sample", sid, "改结构"):
            return
        initial = ""
        if sid:
            row = self.store.sample(sid)
            if row:
                initial = (row["smiles"] or "").strip()
                if not initial:
                    initial = (row["molfile"] or "").strip()

        def done(payload):
            if not payload or not payload.get("saved"):
                if payload and payload.get("timeout"):
                    messagebox.showinfo(
                        "已超时", "等了太久没收到 Ketcher 的回写，什么都没改。")
                return
            d = payload.get("data") or {}
            smi = (d.get("smiles") or "").strip()
            mol = (d.get("mol") or "").strip()
            if not smi and not mol:
                messagebox.showwarning("没有结构",
                                       "Ketcher 里没有可以保存的结构。")
                return
            kw = {}
            if smi:
                info = chem.analyze(smi)
                if "error" in info:
                    messagebox.showerror("结构解析失败", str(info["error"]))
                    return
                kw["smiles"] = info["smiles"]
                kw["molfile"] = info["molfile"]
                kw["formula"] = info["formula"]
                kw["mw"] = info["mw"]
            else:
                kw["molfile"] = mol
            try:
                if sid:
                    self.store.update_sample(sid, **kw)
                    self.refresh_samples()
                    self.show_sample(sid)
                else:
                    kw["name"] = "未命名（Ketcher）"
                    new_id = self.store.add_sample(**kw)
                    self.refresh_samples()
                    self.show_sample(new_id)
                self._update_status()
            except Exception as e:                   # noqa: BLE001
                messagebox.showerror("保存失败", str(e))

        if not ketcherwin.open_editor(self.root, initial, done):
            messagebox.showerror("打不开 Ketcher", "没能启动浏览器窗口。")

    # ------------------------------------------------------------ 极性变化
    def _latest_drawing_smiles(self, owner_type: str, owner_id: int) -> str:
        """这条记录最近一张带 SMILES 的绘图（drawings 按 id 倒序）。"""
        for d in self.store.drawings(owner_type, owner_id):
            s = (d["smiles"] or "").strip()
            if s:
                return s
        return ""

    def _structure_smiles(self, owner_type: str, owner_id: int, row=None) -> str:
        """详情页展示用的结构：优先最新绘图，其次台账里的 SMILES。"""
        a, _ = split_rxn_pair(self._latest_drawing_smiles(owner_type, owner_id))
        if a:
            return a
        if row is not None:
            return (row["smiles"] or "").strip()
        return ""

    def polarity_context(self) -> tuple[str, str]:
        """给极性变化卡片取 A/B。

        优先用这条记录最新的绘图结构——画完保存后调用方会重建详情页，
        这样卡片能立刻反映新结构；没有绘图才退回组成表 / 药剂台账。
        """
        if self.cur_reaction:
            a, b = split_rxn_pair(
                self._latest_drawing_smiles("reaction", self.cur_reaction))
            if a and b:
                return a, b
            comps = self.store.components(self.cur_reaction)
            reactants = [c["s_smiles"] for c in comps
                         if c["role"] == "反应物" and c["s_smiles"]]
            products = [c["s_smiles"] for c in comps
                        if c["role"] == "产物" and c["s_smiles"]]
            if reactants and products:
                # 只取主底物 / 主产物：多组分直接相加会让描述符失真
                return reactants[0], products[0]
        if self.cur_sample:
            a, _ = split_rxn_pair(
                self._latest_drawing_smiles("sample", self.cur_sample))
            if a:
                return a, ""
            row = self.store.sample(self.cur_sample)
            if row is not None and row["smiles"]:
                return row["smiles"], ""
        return "", ""

    def on_polarity(self, before: str = "", after: str = ""):
        """详情区卡片 / 电子效应窗口：打开极性变化卡片。"""
        if not before:
            before, after = self.polarity_context()
        return polaritywin.open_polarity(self.root, self, before, after)

    def _polarity_block(self, body, before: str, after: str):
        """详情区的一张紧凑卡片：一行结论 + 展开完整解析。"""
        card = tk.Frame(body, bg=CLR_CARD, highlightthickness=1,
                        highlightbackground=CLR_LINE)
        card.pack(fill="x", padx=16, pady=(8, 4))
        head = tk.Frame(card, bg=CLR_CARD)
        head.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(head, text="极性变化", bg=CLR_CARD, fg=CLR_INK,
                 font=(UI, 11, "bold")).pack(side="left")

        res = None
        if before and after:
            try:
                res = polarity.compare(before, after)
            except Exception:
                res = None
        if res is not None and "error" not in res:
            tk.Label(head, text=res["verdict"], bg=CLR_CARD, fg="#6a4fa3",
                     font=(UI, 10, "bold")).pack(side="left", padx=10)
            d = res["delta"]
            tk.Label(card, text=(
                f"ΔTPSA {d['tpsa']:+.1f} Å²   ΔlogP {d['logp']:+.2f}   "
                f"HBD {res['a']['hbd']}→{res['b']['hbd']}   "
                f"HBA {res['a']['hba']}→{res['b']['hba']}"),
                bg=CLR_CARD, fg=CLR_DIM, font=(UI, 9), anchor="w",
                justify="left").pack(fill="x", padx=10, pady=(0, 4))
        else:
            tk.Label(card, text="填一个对照结构，或打开反应记录自动比较反应物 / 产物。",
                     bg=CLR_CARD, fg=CLR_DIM, font=(UI, 9),
                     anchor="w").pack(fill="x", padx=10, pady=(0, 4))
        tk.Button(card, text="展开成因与后果解析 →", relief="flat", bd=0,
                  bg=CLR_CARD, fg=CLR_ACCENT, font=(UI, 9), cursor="hand2",
                  command=lambda: self.on_polarity(before, after)).pack(
                      anchor="w", padx=8, pady=(0, 8))

    # ------------------------------------------------------------ 帮助
    def on_help(self):
        """F1 / 工具栏「帮助」：同一时刻只开一个手册窗口。"""
        w = getattr(self, "_help_win", None)
        try:
            if w is not None and w.win.winfo_exists():
                w.win.lift()
                w.win.focus_set()
                return
        except Exception:
            pass
        self._help_win = helpwin.open_help(self.root)

    def on_switch_user(self):
        """切换账户：清掉 30 天会话并重启，让新账户从启动就加载自己的数据目录。"""
        if not messagebox.askyesno(
                "切换账户",
                "会关闭当前窗口并回到登录页。\n\n"
                "当前账户的数据已经保存，下次用它登录还能看到。",
                parent=self.root):
            return
        auth.clear_session()
        try:
            self.store.close()
        except Exception:
            pass
        restart_app(self.root)

    def on_close(self):
        w = getattr(self, "_effects_win", None)
        try:
            if w is not None and w.win.winfo_exists():
                w.win.destroy()
        except Exception:
            pass
        self.store.close()
        self.root.destroy()


# ---------------------------------------------------------------- 简易输入框

def simpledialog_ask(parent, title, prompt, initial=""):
    from tkinter import simpledialog
    return simpledialog.askstring(title, prompt, initialvalue=initial, parent=parent)


def password_ask(parent, title, prompt):
    """带掩码的输入框（解锁定稿用）。"""
    from tkinter import simpledialog
    return simpledialog.askstring(title, prompt, show="*", parent=parent)


# 对话框（避免循环导入，放这里）
from dialogs import ComponentDialog, ReactionDialog, SampleDialog  # noqa: E402


def restart_app(root=None):
    """重新启动自己（切换账户时用）：源码版重启 gui.py，打包版重启 exe。"""
    exe = sys.executable
    try:
        if getattr(sys, "frozen", False):
            subprocess.Popen([exe], cwd=app_dir())
        else:
            py = exe
            if py.lower().endswith("python.exe"):
                alt = os.path.join(os.path.dirname(py), "pythonw.exe")
                if os.path.isfile(alt):
                    py = alt
            subprocess.Popen([py, os.path.join(app_dir(), "gui.py")],
                             cwd=app_dir())
    except Exception as e:
        messagebox.showerror("重启失败", f"{e}\n\n请手动重新打开 ELN。",
                             parent=root)
        return
    try:
        if root is not None:
            root.destroy()
    except Exception:
        pass
    os._exit(0)


def selftest() -> int:
    """便携版 --selftest：不依赖源码文件的轻量冒烟自检，结果写进程序目录。"""
    lines: list[str] = []

    def ck(ok, msg):
        lines.append(("OK   " if ok else "FAIL ") + msg)
        return bool(ok)

    try:
        import tempfile
        import rdkit
        from PIL import Image                       # noqa: F401
        import win32crypt                           # noqa: F401
        import store
        import effects
        import structure
        ck(True, f"依赖 rdkit {rdkit.__version__} / Pillow / pywin32")
        tmp = tempfile.mkdtemp(prefix="eln-selftest-")
        s = store.Store(os.path.join(tmp, "t.db"))
        sid = s.add_sample(name="自检药剂", code="SELF-CHECK", smiles="CCO")
        ck(sid is not None, "数据库建表与写入")
        row = s.one("SELECT name FROM samples WHERE id=?", (sid,))
        ck(row is not None and row[0] == "自检药剂", "数据库读取")
        s.close()
        shutil.rmtree(tmp, ignore_errors=True)
        ck(len(effects.catalog()) >= 40, "内置效应引擎基团表")
        res = structure.analyze_file(res_path("assets", "示例-对硝基苯酚.cdxml"))
        ck(len(res["items"]) == 2, "ChemDraw CDXML 解析")
        blob = auth.protect(b"portable-check")
        ck(auth.unprotect(blob) == b"portable-check", "本机密文加解密")
        ck(os.path.isdir(app_dir()) and os.access(app_dir(), os.W_OK),
           "便携数据目录可写")
    except Exception as e:
        ck(False, f"异常 {type(e).__name__}: {e}")
    out = os.path.join(app_dir(), "selftest-result.txt")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n"
                 + "\n".join(lines) + "\n")
    return 0 if all(x.startswith("OK") for x in lines) else 1


def main():
    dpi_aware()
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    import keyfix
    keyfix.install()                   # 修 Text 吞字符（如 '-' 被报成 keysym Insert）
    root = tk.Tk()
    root.withdraw()                    # 先藏起来，登录窗口关掉之前不露主界面

    def _on_tk_error(exc, val, tb):
        """快捷方式用 pythonw.exe 启动，没有控制台，Tk 回调异常默认被静默吞掉。

        这里写 error.log 并弹一次框，避免再出现「点了没反应但查不到原因」。
        """
        import time
        import traceback
        text = "".join(traceback.format_exception(exc, val, tb))
        try:
            log = os.path.join(app_dir(), "error.log")
            with open(log, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + text + "\n")
        except Exception:
            pass
        try:
            messagebox.showerror(
                "界面出错了",
                f"{type(val).__name__}: {val}\n\n详细信息已写入 error.log",
                parent=root)
        except Exception:
            pass

    root.report_callback_exception = _on_tk_error
    ico = res_path("assets", "app.ico")
    if os.path.exists(ico):
        try:
            root.iconbitmap(ico)
        except Exception:
            pass                       # Linux 下没有 iconbitmap，忽略即可

    user = auth.load_session()         # 30 天会话有效就不弹登录页
    if user is None:
        user = loginwin.show_login(root)
    if user is None:                   # 登录页点了取消
        root.destroy()
        return
    auth.apply_user(user)              # ★ 必须在 App 创建 Store 之前切数据目录
    root.deiconify()
    App(root, user)
    root.mainloop()


if __name__ == "__main__":
    main()
