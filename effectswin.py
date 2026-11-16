# -*- coding: utf-8 -*-
"""ELN 里的「基团电子效应」分析窗口。

默认形式：左边基团目录（当前记录命中的排最上面并高亮），右边完整结论报告，
顶部两行工具栏（查询 / 分析 / 当前记录 · 全分子杂化 / 极性变化 / 复制报告 / 关闭）。

在此之上合并了原独立判断器的两项能力，窗口外观不变、只在需要时多出一块结构图：

* 解析 ChemDraw / MDL 文件：.cdx .cdxml .mol .mdl .sdf .sd .mol2 .smi .rxn .pdb
  （.cdx / .mol2 / .rxn 由 Open Babel 转换，其余 RDKit / 内置 CDXML 解析器直读）
* 自己绘制：调用 ELN 已有的「绘制区」画板，保存后结构回填到本窗口
* 点选基团判定：结构图上点原子（橙色高亮）→「判定这块」→ 按圈出的片段出报告；
  也能「自动检出」环上全部取代基、「返回基团目录」回到原来的目录形式

判断器引擎（engine / groups / hybrid / structure / ext）已完整并入 ELN，
纯本地、无外部项目依赖、无独立启动入口。
"""
from __future__ import annotations

import io
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from rdkit import Chem

import effects
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

FILE_TYPES = (
    ("ChemDraw 与结构文件",
     "*.cdx *.cdxml *.mol *.mdl *.sdf *.sd *.mol2 *.smi *.smiles *.rxn *.pdb"),
    ("ChemDraw 二进制", "*.cdx"),
    ("ChemDraw XML", "*.cdxml"),
    ("MDL 结构", "*.mol *.sdf *.mdl *.sd"),
    ("全部文件", "*.*"),
)


def _btn(parent, text, cmd, bg="#e8eef7", fg=INK):
    return tk.Button(parent, text=text, command=cmd, relief="flat", bd=0,
                     bg=bg, fg=fg, font=(UI, 9), padx=10, pady=5,
                     cursor="hand2", activebackground="#d6e2f5")


class EffectsWindow:
    def __init__(self, root: tk.Misc, app, smiles: str = "", label: str = ""):
        self.root = root
        self.app = app
        self.smiles = smiles
        self.label = label
        self.hits: list[dict] = []
        self.rows: dict[str, dict] = {}        # tree iid → 报告 dict
        self._file_items: dict[str, dict] = {}  # tree iid → 文件检出项
        self.current_query = ""

        # 结构文件 / 绘制 / 点选模式的状态
        self.file_ctx = None                  # effects.file_result() 的返回值
        self.picked: set[int] = set()          # 用户在结构图上点选的原子
        self._atom_xy: dict[int, tuple[float, float]] = {}
        self._cur_atoms: list[int] = []        # 当前判定项高亮的原子
        self._img = None                       # PhotoImage 必须留引用

        self.win = tk.Toplevel(root)
        self.win.title("基团电子效应 · ELN 联动")
        self.win.geometry("1020x660")
        self.win.minsize(860, 540)
        self.win.configure(bg=BG)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda e: self.close())
        self.win.bind("<Control-w>", lambda e: self.close())

        ico = res_path("assets", "app.ico")
        if os.path.exists(ico):
            try:
                self.win.iconbitmap(ico)
            except Exception:
                pass

        self._build()
        if smiles:
            self.load_molecule(smiles, label)
        else:
            self.reload_tree()
            self.show_text(self._intro_text())
            self._status("就绪 · 未载入记录结构")

    # ------------------------------------------------------------ 布局
    def _build(self):
        # 顶栏分两行：单行塞太多控件会被挤出窗口右边界
        top = tk.Frame(self.win, bg=BG)
        top.pack(fill="x", padx=12, pady=(10, 2))
        row1 = tk.Frame(top, bg=BG)
        row1.pack(fill="x")
        row2 = tk.Frame(top, bg=BG)
        row2.pack(fill="x", pady=(6, 2))

        tk.Label(row1, text="基团电子效应", bg=BG, fg=INK,
                 font=(UI, 14, "bold")).pack(side="left")
        tk.Label(row1, text="由「判断器」引擎驱动", bg=BG, fg=DIM,
                 font=(UI, 9)).pack(side="left", padx=(8, 14))

        self.query = tk.StringVar()
        ent = tk.Entry(row1, textvariable=self.query, width=30, font=(UI, 10),
                       bd=1, relief="solid", bg=CARD, fg=INK)
        ent.pack(side="left", ipady=3)
        ent.bind("<Return>", lambda e: self.on_analyze())
        _btn(row1, "分析", self.on_analyze, ACCENT, "#ffffff").pack(side="left", padx=(6, 2))
        _btn(row1, "当前记录", self.on_current, "#e8f4ec", GREEN).pack(side="left", padx=2)
        tk.Label(row1, text="回车分析 · Esc 关闭", bg=BG, fg=DIM,
                 font=(UI, 8)).pack(side="right", padx=(0, 4))

        # 第一行新增的三个入口：结构文件 / 自己绘制 / ChemDraw 剪贴板
        _btn(row2, "打开结构文件", self.on_open_file, "#e8f4ec", GREEN).pack(side="left", padx=(0, 6))
        _btn(row2, "绘制结构", self.on_draw, "#ede7f6", PURPLE).pack(side="left", padx=(0, 6))
        _btn(row2, "从剪贴板", self.on_clip, "#ede7f6", PURPLE).pack(side="left", padx=(0, 6))
        _btn(row2, "全分子杂化", self.on_hybrid, "#ede7f6", PURPLE).pack(side="left", padx=(0, 6))
        _btn(row2, "极性变化", self.on_polarity, "#e8f4ec", GREEN).pack(side="left", padx=(0, 6))
        _btn(row2, "复制报告", self.on_copy).pack(side="left", padx=(0, 6))
        _btn(row2, "关闭", self.close, "#f2f4f7", DIM).pack(side="left", padx=(0, 6))
        tk.Label(row2, text="σ 值以「苯环上取代、H 为零点」为准", bg=BG, fg=DIM,
                 font=(UI, 8)).pack(side="right", padx=(0, 4))

        # 状态栏先占底部：否则主体 expand 后空间不够，最后 pack 的状态栏会被挤没
        self.status = tk.Label(self.win, text="", bg=BG, fg=DIM, font=(UI, 8),
                               anchor="w")
        self.status.pack(side="bottom", fill="x", padx=14, pady=(0, 8))

        body = tk.PanedWindow(self.win, orient="horizontal", bg=BG,
                              sashwidth=6, bd=0, sashrelief="flat")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 4))

        left = tk.Frame(body, bg=CARD, highlightthickness=1,
                        highlightbackground=LINE)
        right = tk.Frame(body, bg=CARD, highlightthickness=1,
                         highlightbackground=LINE)
        body.add(left, width=360, minsize=280)
        body.add(right, width=630, minsize=380)

        self.tree_head = tk.Label(left, text="基团目录（绿色 = 当前记录命中）",
                                  bg=CARD, fg=DIM, font=(UI, 9))
        self.tree_head.pack(anchor="w", padx=10, pady=(8, 4))
        wrap = tk.Frame(left, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=(8, 2), pady=(0, 8))
        self.tree = ttk.Treeview(wrap, columns=("name", "sp", "cls"),
                                 show="headings", selectmode="browse")
        for col, title, width, anchor in (("name", "基团", 148, "w"),
                                          ("sp", "σp", 62, "center"),
                                          ("cls", "总效应", 108, "w")):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.tag_configure("hit", background="#e7f6ec", foreground=INK)
        self.tree.tag_configure("cat", background=CARD, foreground=INK)
        self.tree.tag_configure("sep", background="#f2f4f7", foreground=DIM)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_pick)
        self.tree.bind("<Double-1>", self.on_pick)

        self.title_lbl = tk.Label(right, text="结论报告", bg=CARD, fg=INK,
                                  font=(UI, 11, "bold"), anchor="w")
        self.title_lbl.pack(fill="x", padx=14, pady=(10, 4))

        # 结构图面板：默认不 pack，只有读入结构文件 / 绘制后才出现，
        # 所以平时窗口和原来完全一样（左目录 + 右报告）。
        self.struct = self._build_struct(right)

        self.report_wrap = tk.Frame(right, bg=CARD)
        self.report_wrap.pack(fill="both", expand=True, padx=(12, 4), pady=(0, 10))
        self.txt = tk.Text(self.report_wrap, wrap="char", bg="#fbfcfd", fg=INK,
                           bd=1, relief="solid", font=(MONO, 10), padx=12,
                           pady=10, spacing1=2, spacing3=2)
        tsb = ttk.Scrollbar(self.report_wrap, orient="vertical",
                            command=self.txt.yview)
        self.txt.configure(yscrollcommand=tsb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")
        self.txt.tag_configure("dim", foreground=DIM)

    def _build_struct(self, parent):
        """结构图 + 点选工具条。返回未 pack 的 Frame，由 _apply_res 显示。"""
        box = tk.Frame(parent, bg=CARD)
        head = tk.Frame(box, bg=CARD)
        head.pack(fill="x", padx=12, pady=(0, 2))
        self.struct_title = tk.Label(
            head, text="结构图 · 点原子可自己圈出要判的一块", bg=CARD, fg=DIM,
            font=(UI, 9), anchor="w")
        self.struct_title.pack(side="left")
        _btn(head, "返回基团目录", self.on_back, "#f2f4f7", DIM).pack(side="right")

        imgbox = tk.Frame(box, bg="#fbfcfd", highlightthickness=1,
                          highlightbackground=LINE)
        imgbox.pack(fill="x", padx=12, pady=(0, 2))
        self.img_lbl = tk.Label(imgbox, bg="#fbfcfd", cursor="hand2")
        self.img_lbl.pack(pady=3)
        self.img_lbl.bind("<Button-1>", self.on_img_click)

        selbar = tk.Frame(box, bg=CARD)
        selbar.pack(fill="x", padx=12, pady=(0, 6))
        self.sel_hint = tk.Label(selbar, text="", bg=CARD, fg=DIM,
                                 font=(UI, 8), anchor="w")
        self.sel_hint.pack(side="left")
        self.pick_btn = _btn(selbar, "判定这块", self.on_judge_pick,
                             "#e8f4ec", GREEN)
        self.pick_btn.pack(side="right", padx=(4, 0))
        self.hybrid_btn = _btn(selbar, "看杂化", self.on_show_hybrid,
                               "#f2f4f7", DIM)
        self.hybrid_btn.pack(side="right", padx=(4, 0))
        self.clear_btn = _btn(selbar, "清除选择", self.on_clear_pick,
                              "#f2f4f7", DIM)
        self.clear_btn.pack(side="right", padx=(4, 0))
        self.auto_btn = _btn(selbar, "自动检出", self.on_reset_auto,
                             "#f2f4f7", DIM)
        self.auto_btn.pack(side="right", padx=(4, 0))
        return box

    @staticmethod
    def _intro_text() -> str:
        return (
            "基团电子效应判断器已连接。\n\n"
            "用法：\n"
            "  · 左边点一个基团，看它的 σ 值、诱导 / 共轭拆解与芳环定位效应。\n"
            "  · 顶部输入基团名（硝基、甲氧基…）或带 * 的片段 SMILES，回车分析。\n"
            "  · 输入完整分子 SMILES 会扫描分子里出现的取代基。\n"
            "  · 在 ELN 里选中药剂后点「电子效应」，会自动带入该结构。\n"
            "  · 点「打开结构文件」读 ChemDraw / MDL 文件（.cdx .cdxml .mol .sdf…）；\n"
            "    点「绘制结构」用画板自己画；点「从剪贴板」读 ChemDraw 复制的片段。\n"
            "  · 载入结构后，可在图上点选原子，再点「判定这块」只判你圈的那一部分。\n\n"
            "口径：σ 值以「取代基连在苯环上、H 为零点」为标准，\n"
            "      数据来自 ELN 内置效应引擎，趋势可靠、数值仅供比较。")

    # ------------------------------------------------------------ 数据
    def reload_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        self._file_items.clear()

        if self.file_ctx is not None:
            self.tree_head.configure(
                text=f"检出取代基 · {self.file_ctx.get('file', '')}")
            for it in self.file_ctx["items"]:
                iid = f"file:{it.get('no', 1)}"
                self.tree.insert("", "end", iid=iid, tags=("hit",),
                                 values=effects.item_brief(it))
                self._file_items[iid] = it
            kids = self.tree.get_children()
            if kids:
                self.tree.selection_set(kids[0])
                self.tree.see(kids[0])
                self.on_pick()
            return

        self.tree_head.configure(text="基团目录（绿色 = 当前记录命中）")
        for i, hit in enumerate(self.hits):
            rec = hit["rec"]
            iid = f"hit:{i}"
            self.tree.insert("", "end", iid=iid, tags=("hit",),
                             values=(rec["name"], self._sp(rec["sp"]), rec["cls"]))
            self.rows[iid] = rec
        if self.hits:
            self.tree.insert("", "end", iid="sep", tags=("sep",),
                             values=("以下为全部基团", "", ""))
        for item in effects.catalog():
            iid = "cat:" + item["key"]
            if self.tree.exists(iid):
                continue
            self.tree.insert("", "end", iid=iid, tags=("cat",),
                             values=(item["name"], self._sp(item["sp"]), item["cls"]))
            self.rows[iid] = None
        if self.hits:
            self.tree.selection_set("hit:0")
            self.tree.see("hit:0")
            self.show_rec(self.hits[0]["rec"], "当前记录命中")

    @staticmethod
    def _sp(v) -> str:
        return "—" if v is None else (f"+{v:.2f}" if v > 0 else f"{v:.2f}")

    def load_molecule(self, smiles: str, label: str = ""):
        self._leave_file()
        self.smiles = smiles or ""
        self.label = label or "当前记录"
        try:
            self.hits = effects.scan_molecule(self.smiles)
        except Exception as e:
            self.hits = []
            messagebox.showerror("分析失败", str(e), parent=self.win)
        self.reload_tree()
        if not self.hits:
            self.show_text(
                f"{self.label}\nSMILES  {self.smiles or '（空）'}\n\n"
                "这个结构里没有命中判断器收录的 45 个常见基团。\n\n"
                "可以：\n"
                "  · 在顶部直接输基团名或带 * 的片段 SMILES 单独查询；\n"
                "  · 点「全分子杂化」看每个原子的杂化轨道与孤对；\n"
                "  · 点「极性变化」看整体描述符增减与实验后果；\n"
                "  · 点「打开结构文件 / 绘制结构」，再在图上手选要判的一块。")
        self._status(f"{self.label} · 命中 {len(self.hits)} 个基团："
                     + effects.summarize(self.hits))

    # ------------------------------------------------------------ 交互
    def on_pick(self, _e=None):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        if self.file_ctx is not None and iid.startswith("file:"):
            item = self._file_items.get(iid)
            if item:
                self.show_item(item)
            return
        rec = self.rows.get(iid)
        if rec is None and iid.startswith("cat:"):
            item = next((x for x in effects.catalog() if x["key"] == iid[4:]), None)
            if item:
                rec, err = effects.analyze(item["name"])
                if not rec:
                    rec, err = effects.analyze(item["smiles"])
                if rec:
                    self.rows[iid] = rec
        if rec is None:
            return
        self.show_rec(rec, "当前记录命中" if iid.startswith("hit:") else "基团目录")

    def show_rec(self, rec: dict, source: str = ""):
        self.current_query = rec.get("name") or rec.get("smiles") or ""
        try:
            text = effects.report_text(rec, width=64)
        except Exception as e:
            text = f"报告生成失败：{e}"
        self.title_lbl.configure(text=f"{rec['name']}   ·   {source}")
        self.show_text(text)

    def show_item(self, item: dict):
        """文件 / 绘制 / 点选模式下，左栏选中一项 → 报告 + 结构图高亮。"""
        name, _sp, cls = effects.item_brief(item)
        self.current_query = item.get("frag") or name
        self.title_lbl.configure(text=f"{name}   ·   {cls}")
        try:
            self.show_text(effects.item_report(item, self.file_ctx, width=64))
        except Exception as e:
            self.show_text(f"报告生成失败：{type(e).__name__}: {e}")
        rec = item.get("rec") or {}
        self._cur_atoms = list(item.get("atoms")
                               or (rec.get("src") or {}).get("atoms") or [])
        self._render_mol()

    def show_text(self, text: str):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", text)
        self.txt.configure(state="disabled")
        self.txt.yview_moveto(0)

    def on_analyze(self):
        q = self.query.get().strip()
        if not q:
            messagebox.showinfo("提示", "先输入基团名、别名或 SMILES。", parent=self.win)
            return
        self._leave_file()
        # 完整分子（不含 * 且能解析）→ 扫描其中的取代基
        try:
            mol = Chem.MolFromSmiles(q) if "*" not in q else None
        except Exception:
            mol = None
        if mol is not None and mol.GetNumAtoms() > 1:
            self.load_molecule(q, "手动输入的分子")
            return
        try:
            rec, err = effects.analyze(q)
        except Exception as e:
            rec, err = None, str(e)
        if not rec:
            self.title_lbl.configure(text="没查到")
            self.show_text(err or "没查到这个基团。\n\n"
                           "试试中文名（硝基、甲氧基）、英文缩写（NO2、OMe），\n"
                           "或带连接点的片段 SMILES（*OC 表示甲氧基）。")
            self._status("未命中")
            return
        self.show_rec(rec, "手动查询")

    def on_current(self):
        self._leave_file()
        try:
            smi, label = self.app.effects_context()
        except Exception as e:
            smi, label = "", str(e)
        if not smi:
            messagebox.showinfo("提示", "ELN 里还没有选中带结构的药剂或产物。",
                                parent=self.win)
            return
        self.load_molecule(smi, label)

    def on_hybrid(self):
        smi = self.smiles or self.query.get().strip()
        if not smi:
            messagebox.showinfo("提示", "先载入一个分子结构。", parent=self.win)
            return
        self.title_lbl.configure(text="全分子杂化轨道")
        self.show_text(f"SMILES  {smi}\n\n" + effects.hybrid_text(smi, width=64))
        self._status("杂化轨道来自判断器 hybrid 模块")

    def on_polarity(self):
        """打开「极性变化」卡片：反应自动带入反应物 / 产物，药剂带入当前结构。"""
        try:
            import polaritywin
            ctx = getattr(self.app, "polarity_context", None)
            before, after = ctx() if callable(ctx) else ("", "")
            polaritywin.open_polarity(self.win, self.app, before=before, after=after)
            self._status("已打开极性变化卡片")
        except Exception as e:
            messagebox.showerror("打不开", str(e), parent=self.win)

    def on_copy(self):
        text = self.txt.get("1.0", "end").rstrip()
        if not text:
            return
        self.win.clipboard_clear()
        self.win.clipboard_append(text)
        self._status("报告已复制到剪贴板")

    # ------------------------------------------------------------ 结构文件 / 绘制
    def on_open_file(self):
        path = filedialog.askopenfilename(
            parent=self.win, title="打开结构文件（ChemDraw / MDL）",
            filetypes=FILE_TYPES)
        if path:
            self.load_file(path)

    def load_file(self, path: str) -> bool:
        """给测试和外部调用留的公开入口：读一个结构文件并切换到结构模式。"""
        try:
            res = effects.file_result(path)
        except Exception as e:
            messagebox.showerror(
                "读不了这个文件",
                f"{e}\n\n支持的格式：{' '.join(effects.supported_formats())}\n"
                f"{effects.babel_status()}\n"
                ".cdx 若读不出来，在 ChemDraw 里另存为 .cdxml 或 .mol 更稳。",
                parent=self.win)
            return False
        return self._apply_res(res)

    def on_clip(self):
        """ChemDraw 里用选择工具框住片段 Ctrl+C，再点这里。"""
        try:
            res = effects.clipboard_result()
        except Exception as e:
            messagebox.showwarning(
                "剪贴板里没有结构",
                f"{e}\n\n要复制结构本身（不是图片）；也可以直接存成 .cdxml / .mol 再打开。",
                parent=self.win)
            return False
        return self._apply_res(res)

    def on_draw(self):
        """借用 ELN 绘制区画结构，保存后把 SMILES 回填到本窗口。"""
        try:
            import drawpad
            store = getattr(self.app, "store", None)
            drawpad.open_drawpad(self.win, store, "effects", None,
                                 initial_smiles=self.smiles or "",
                                 on_smiles=self.on_drawn)
            self._status("绘制区已打开 · 画完点「保存」，结构会自动带回来")
        except Exception as e:
            messagebox.showerror("打不开绘制区", str(e), parent=self.win)

    def on_drawn(self, smiles: str):
        """绘制区保存回调：与打开结构文件走同一条分析链。"""
        try:
            res = effects.from_smiles(
                smiles, name="绘制结构",
                notes=["来自 ELN 绘制区，只用于分析，未写入实验记录。"])
        except Exception as e:
            messagebox.showerror("画的结构读不了", str(e), parent=self.win)
            return
        self._apply_res(res)

    def _apply_res(self, res: dict) -> bool:
        """进入结构模式：显示结构图，左栏换成检出的取代基。"""
        self.file_ctx = res
        res.setdefault("auto_items", list(res.get("items") or []))
        self.picked.clear()
        self._cur_atoms = []
        self.query.set("")
        self.smiles = res.get("smiles") or self.smiles
        self.struct.pack(fill="x", padx=12, pady=(0, 2), before=self.report_wrap)
        self.struct_title.configure(
            text=f"结构图 · {res.get('file', '')} · 点原子可自己圈出要判的一块")
        self.reload_tree()
        self._render_mol()
        self._update_selbar()
        n = len(res.get("items") or [])
        if not n:
            self.title_lbl.configure(text=f"{res.get('file', '')} · 未自动检出取代基")
            self.show_text(
                f"文件    {res.get('file', '')}  ·  {res.get('fmt', '')}\n"
                f"结构    {res.get('smiles', '')}\n\n"
                "环上没检出取代基（可能只画了裸环，或者取代基不在芳环上）。\n\n"
                "可以直接在结构图上点选原子，把要判的那一块圈出来，\n"
                "再点「判定这块」——不用改文件、也不用重新打开。\n\n"
                "提示：只圈环外那一块（可以连上它连着的那个环原子），\n"
                "圈住整个分子或切到半个双键都判不了。")
        self._status(f"{res.get('file', '')} · {res.get('fmt', '')} · "
                     f"检出 {n} 个取代基 · {effects.babel_status()}")
        return True

    def _leave_file(self, rebuild: bool = True):
        """退出结构模式，恢复原来的基团目录形式。"""
        if self.file_ctx is None:
            return
        self.file_ctx = None
        self.picked.clear()
        self._cur_atoms = []
        self._atom_xy.clear()
        self._img = None
        try:
            self.struct.pack_forget()
            self.img_lbl.configure(image="", text="")
        except Exception:
            pass
        if rebuild:
            self.reload_tree()

    def on_back(self):
        self._leave_file()
        self.title_lbl.configure(text="结论报告")
        self.show_text(self._intro_text())
        self._status("已返回基团目录")

    # ------------------------------------------------------------ 结构图绘制 / 点选
    def _render_mol(self):
        """蓝色 = 当前判定的片段，橙色 = 自己点选的原子；同时记录像素坐标。"""
        if self.file_ctx is None:
            return
        try:
            from rdkit.Chem import AllChem
            from rdkit.Chem.Draw import rdMolDraw2D
            from PIL import Image, ImageTk

            mol = self.file_ctx["mol"]
            if mol.GetNumConformers() == 0:
                AllChem.Compute2DCoords(mol)
            W, H = 470, 200
            d = rdMolDraw2D.MolDraw2DCairo(W, H)
            opt = d.drawOptions()
            opt.padding = 0.10
            opt.bondLineWidth = 2
            hl, colors = [], {}
            for i in self._cur_atoms:
                hl.append(i)
                colors[i] = (0.55, 0.76, 1.0)
            for i in self.picked:
                hl.append(i)
                colors[i] = (1.0, 0.80, 0.32)
            rdMolDraw2D.PrepareAndDrawMolecule(
                d, mol, highlightAtoms=hl or None,
                highlightAtomColors=colors or None)
            d.FinishDrawing()
            self._atom_xy = {}
            for a in mol.GetAtoms():
                pt = d.GetDrawCoords(a.GetIdx())
                self._atom_xy[a.GetIdx()] = (pt.x, pt.y)
            img = Image.open(io.BytesIO(d.GetDrawingText()))
            self._img = ImageTk.PhotoImage(img)
            self.img_lbl.configure(image=self._img, text="")
        except Exception as e:
            self._atom_xy = {}
            self.img_lbl.configure(image="", text=f"（结构图绘制失败：{e}）")

    def on_img_click(self, event):
        """点结构图上的原子：选中 / 取消。图片在 Label 里居中，先换算偏移。"""
        if self.file_ctx is None or not self._atom_xy:
            return
        lw = max(1, self.img_lbl.winfo_width())
        lh = max(1, self.img_lbl.winfo_height())
        iw = self._img.width() if self._img is not None else lw
        ih = self._img.height() if self._img is not None else lh
        ox = (lw - iw) / 2 if iw < lw else 0
        oy = (lh - ih) / 2 if ih < lh else 0
        x, y = event.x - ox, event.y - oy
        best, bestd = None, 18.0
        for idx, (ax, ay) in self._atom_xy.items():
            dist = ((ax - x) ** 2 + (ay - y) ** 2) ** 0.5
            if dist < bestd:
                best, bestd = idx, dist
        if best is None:
            return
        if best in self.picked:
            self.picked.discard(best)
        else:
            self.picked.add(best)
        self._render_mol()
        self._update_selbar()

    def _update_selbar(self):
        if self.file_ctx is None:
            return
        n = len(self.picked)
        if n:
            tip = ""
            if n == 1:
                try:
                    import hybrid
                    h = hybrid.analyze_atom(self.file_ctx["mol"],
                                            next(iter(self.picked)))
                    if h:
                        tip = f"：{h['symbol']} {hybrid.brief(h)}"
                except Exception:
                    pass
            self.sel_hint.configure(text=f"已选 {n} 个原子（橙色）{tip}")
            self.pick_btn.configure(state="normal", text=f"判定这 {n} 个原子")
            self.hybrid_btn.configure(state="normal" if n == 1 else "disabled")
        else:
            self.sel_hint.configure(text="点图上的原子可自己选片段，再点一次取消")
            self.pick_btn.configure(state="disabled", text="判定这块")
            self.hybrid_btn.configure(state="disabled")

    def on_clear_pick(self):
        self.picked.clear()
        self._render_mol()
        self._update_selbar()
        self._status("已清除点选的原子")

    def on_judge_pick(self):
        """只判用户圈出来的那一块。"""
        if self.file_ctx is None or not self.picked:
            return
        try:
            item = effects.selection_result(self.file_ctx["mol"], self.picked)
        except Exception as e:
            messagebox.showwarning("这一块判不了", str(e), parent=self.win)
            return
        self.file_ctx["items"] = [item]
        self.file_ctx["picked"] = sorted(self.picked)
        self.reload_tree()
        self._status(f"自定义片段 · 圈了 {len(self.picked)} 个原子 · "
                     + effects.item_brief(item)[0])

    def on_reset_auto(self):
        """放弃自定义点选，回到自动检出的全部取代基。"""
        if self.file_ctx is None:
            return
        self.file_ctx["items"] = list(self.file_ctx.get("auto_items") or [])
        self.file_ctx["picked"] = []
        self.picked.clear()
        self.reload_tree()
        self._render_mol()
        self._update_selbar()
        self._status(f"已恢复自动检出 · {len(self.file_ctx['items'])} 个取代基")

    def on_show_hybrid(self):
        """只点了一个原子时，单独看它的杂化轨道。"""
        if self.file_ctx is None or len(self.picked) != 1:
            return
        try:
            import hybrid
            idx = next(iter(self.picked))
            h = hybrid.analyze_atom(self.file_ctx["mol"], idx)
            if not h:
                return
            lines = [f"{h['symbol']} 原子（第 {idx + 1} 号）的杂化", "",
                     f"    {h['hybrid']}  ·  {h['geometry']}  ·  {h['angle']}", ""]
            lines += ["    " + x for x in hybrid.report_lines(h, 62)]
            self.title_lbl.configure(text="单个原子的杂化")
            self.show_text("\n".join(lines))
            self._status("单原子杂化来自判断器 hybrid 模块")
        except Exception as e:
            messagebox.showwarning("看不了", str(e), parent=self.win)

    # ------------------------------------------------------------ 收尾
    def _status(self, msg: str):
        ok, d = effects.available()
        tail = "引擎 内置" if ok else d
        self.status.configure(text=f"{msg}        ·        {tail}")

    def close(self):
        try:
            self.win.destroy()
        finally:
            if getattr(self.app, "_effects_win", None) is self:
                self.app._effects_win = None


def open_effects(root, app, smiles: str = "", label: str = ""):
    """同一时刻只开一个分析窗口；重复调用会复用并把新结构带进去。"""
    old = getattr(app, "_effects_win", None)
    try:
        if old is not None and old.win.winfo_exists():
            old.win.lift()
            old.win.focus_set()
            if smiles:
                old.load_molecule(smiles, label)
            return old
    except Exception:
        pass
    win = EffectsWindow(root, app, smiles, label)
    app._effects_win = win
    return win
