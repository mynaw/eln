# -*- coding: utf-8 -*-
"""新建/编辑对话框：样品、反应、反应组成。"""

from __future__ import annotations

import json
import threading

import tkinter as tk
from tkinter import messagebox, ttk

from PIL import ImageTk

import chem
import caslookup
from store import ROLES

UI = "Microsoft YaHei UI"
MONO = UI   # 字体统一：等宽位也用同一族
CARD = "#ffffff"
INK = "#16202c"
DIM = "#6b7684"


def _bind_num_norm(var: tk.StringVar) -> None:
    """给数字 StringVar 挂一个写入时自动折全角标点的钩子（中文输入法友好）。"""
    from gui import norm_num
    def _cb(*_a):
        cur = var.get()
        nw = norm_num(cur)
        if nw != cur:
            var.set(nw)
    var.trace_add("write", _cb)
ACCENT = "#1f6feb"
GREEN = "#1a7f4b"
LINE = "#dde3ea"


def _center(win, parent, w=None, h=None):
    win.update_idletasks()
    w = w or win.winfo_width()
    h = h or win.winfo_height()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    win.geometry(f"{w}x{h}+{px + (pw - w) // 2}+{py + max(20, (ph - h) // 2)}")


# ---------------------------------------------------------------- 样品

class SampleDialog:
    KEYS = [("name", "名称 *"), ("code", "编号"), ("cas", "CAS 号"),
            ("amount", "数量"), ("unit", "单位"), ("purity", "纯度"),
            ("state", "状态"), ("location", "存放位置")]

    def __init__(self, app, store, row, coll_id, on_saved):
        self.app = app
        self.store = store
        self.row = row
        self.on_saved = on_saved
        self._img = None
        self._cas_result = None     # 后台 CAS 线程 -> 主线程的结果槽

        self.win = tk.Toplevel(app.root)
        self.win.title("编辑药剂" if row else "新建药剂")
        self.win.configure(bg=CARD)
        self.win.transient(app.root)
        self.win.grab_set()

        self.vars = {}
        self._build(row, coll_id)
        self.win.bind("<Escape>", lambda e: self.win.destroy())
        self.win.bind("<Control-Return>", lambda e: self.save())
        _center(self.win, app.root, 780, 560)
        self.win.focus_set()

    def _build(self, row, coll_id):
        wrap = tk.Frame(self.win, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=18, pady=14)
        wrap.columnconfigure(0, weight=1)
        wrap.columnconfigure(1, weight=0)

        # 左：表单
        form = tk.Frame(wrap, bg=CARD)
        form.grid(row=0, column=0, sticky="nsew")
        form.columnconfigure(1, weight=1)

        # 灰色提示文字已全部隐藏（原 unit/purity/state/location 四条说明）
        tips = {}
        # 单位、状态改成「点击后选择」：可下拉，也允许直接输入自定义值
        choices = {
            "unit": ("g", "mg", "μg", "mL", "μL", "mmol", "mol"),
            "state": ("固体", "液体", "油状", "溶液"),
        }

        r = 0
        for key, label in self.KEYS:
            tk.Label(form, text=label, bg=CARD, fg=DIM, font=(UI, 9),
                     anchor="w", width=9).grid(row=r, column=0, sticky="w", pady=5)
            var = tk.StringVar(value="" if row is None else (str(row[key]) if row[key] is not None else ""))
            if key in choices:
                ent = ttk.Combobox(form, textvariable=var, values=choices[key],
                                   state="normal", font=(UI, 10))
                ent.grid(row=r, column=1, sticky="ew", pady=5, ipady=2)
            else:
                ent = tk.Entry(form, textvariable=var, font=(UI, 10), bd=1, relief="solid",
                               bg="#ffffff", fg=INK)
                ent.grid(row=r, column=1, sticky="ew", pady=5, ipady=3)
            self.vars[key] = var
            if key == "cas":
                # CAS 和 SMILES 一样是「结构入口」：旁边给一个「查结构」按钮，
                # 联网解析成 SMILES 后走 on_parse 同一条渲染通道。
                cell = tk.Frame(form, bg=CARD)
                cell.grid(row=r, column=2, sticky="w", padx=(8, 0))
                tk.Button(cell, text="查结构", command=self.on_resolve_cas,
                          relief="flat", bd=0, bg="#e8eef7", fg=ACCENT,
                          font=(UI, 9), padx=8, cursor="hand2").pack(side="left")
            elif key in tips:
                tk.Label(form, text=tips[key], bg=CARD, fg="#a9b4c2",
                         font=(UI, 8)).grid(row=r, column=2, sticky="w", padx=(8, 0))
            r += 1

        # SMILES 单独一行，带解析按钮
        tk.Label(form, text="SMILES", bg=CARD, fg=DIM, font=(UI, 9),
                 anchor="w", width=9).grid(row=r, column=0, sticky="w", pady=5)
        self.smiles = tk.StringVar(value=row["smiles"] if row and row["smiles"] else "")
        ent = tk.Entry(form, textvariable=self.smiles, font=(MONO, 10), bd=1,
                       relief="solid", bg="#ffffff", fg=INK)
        ent.grid(row=r, column=1, sticky="ew", pady=5, ipady=3)
        cell = tk.Frame(form, bg=CARD)
        cell.grid(row=r, column=2, sticky="w", padx=(8, 0))
        tk.Button(cell, text="解析", command=self.on_parse, relief="flat", bd=0,
                  bg="#e8eef7", fg=ACCENT, font=(UI, 9), padx=8,
                  cursor="hand2").pack(side="left")
        r += 1

        # 备注
        tk.Label(form, text="备注", bg=CARD, fg=DIM, font=(UI, 9),
                 anchor="w", width=9).grid(row=r, column=0, sticky="nw", pady=5)
        self.note = tk.Text(form, height=4, font=(UI, 10), bd=1, relief="solid",
                            bg="#ffffff", fg=INK, wrap="word", padx=6, pady=4)
        self.note.grid(row=r, column=1, columnspan=2, sticky="ew", pady=5)
        if row and row["note"]:
            self.note.insert("1.0", row["note"])

        # 右：结构预览
        side = tk.Frame(wrap, bg=CARD, width=300)
        side.grid(row=0, column=1, sticky="n", padx=(16, 0))
        side.grid_propagate(False)
        tk.Label(side, text="结构预览", bg=CARD, fg=DIM,
                 font=(UI, 9)).pack(anchor="w")
        self.preview = tk.Label(side, text="（填 SMILES 后点解析）", bg="#fafbfc",
                                fg="#a9b4c2", font=(UI, 9), width=32, height=13,
                                relief="solid", bd=1)
        self.preview.pack(pady=(4, 8))
        self.props = tk.Label(side, text="", bg=CARD, fg=INK, font=(UI, 9),
                              justify="left", anchor="nw")
        self.props.pack(anchor="w", fill="x")

        # 底部按钮
        btns = tk.Frame(self.win, bg=CARD)
        btns.pack(fill="x", padx=18, pady=(0, 14))
        tk.Button(btns, text="保存", command=self.save, relief="flat", bd=0,
                  bg=ACCENT, fg="#ffffff", font=(UI, 10, "bold"), padx=22,
                  pady=6, cursor="hand2").pack(side="right")
        tk.Button(btns, text="取消", command=self.win.destroy, relief="flat", bd=0,
                  bg="#eef1f5", fg=INK, font=(UI, 10), padx=16,
                  pady=6, cursor="hand2").pack(side="right", padx=(0, 8))
        tk.Label(btns, text="Ctrl+Enter 保存 · Esc 取消", bg=CARD, fg="#a9b4c2",
                 font=(UI, 8)).pack(side="left")

        self.collection_id = row["collection_id"] if row and row["collection_id"] else None
        if self.collection_id is None:
            self.coll_var = coll_id

        if self.smiles.get():
            self.on_parse(silent=True)
        elif self.vars["cas"].get().strip():
            # 只有 CAS 没有 SMILES 时，打开即自动联网解析结构（和 SMILES 自动渲染对称）
            self.on_resolve_cas(silent=True)

    def on_parse(self, silent=False):
        text = self.smiles.get().strip()
        if not text:
            self._clear_preview()
            return
        info = chem.analyze(text)
        if "error" in info:
            if not silent:
                messagebox.showwarning("解析失败", info["error"], parent=self.win)
            self._clear_preview()
            return

        img = chem.render(info["mol"], 290, 230)
        if img is not None:
            self._img = ImageTk.PhotoImage(img)
            self.preview.configure(image=self._img, text="", width=290, height=230)

        self.props.configure(
            text=f"分子式  {info['formula']}\n"
                 f"分子量  {info['mw']:.2f}\n"
                 f"精确质量 {info['exact_mw']:.4f}\n"
                 f"环数    {info['rings']}\n"
                 f"TPSA   {info['tpsa']:.1f}   logP {info['logp']:.2f}")
        self._info = info

        # 分子式/分子量自动填
        if not self.vars["name"].get().strip():
            pass
        self._auto_formula = info["formula"]
        self._auto_mw = info["mw"]
        self._auto_molfile = info["molfile"]

    def on_resolve_cas(self, silent=False):
        """CAS 号 -> 联网解析成 SMILES -> 走 on_parse 同一条渲染通道。

        与 SMILES 行的「解析」并列，是另一个结构入口；CAS 解析必须放在后台线程，
        否则联网时会卡住 Tk 主线程。
        """
        cas = self.vars["cas"].get().strip()
        if not cas:
            if not silent:
                messagebox.showinfo("提示", "先在「CAS 号」里填一个 CAS，比如 64-17-5。",
                                    parent=self.win)
            return
        if not caslookup.is_cas(cas):
            if not silent:
                messagebox.showwarning("不是 CAS 格式",
                                       "CAS 号应形如 64-17-5（也可写 CAS:64-17-5）。",
                                       parent=self.win)
            return
        self._cas_result = None
        self.preview.configure(image="", text=f"正在解析 CAS {cas} …",
                               width=32, height=13)
        self.props.configure(text="")
        threading.Thread(target=self._cas_worker, args=(cas,),
                         daemon=True).start()
        self.win.after(80, self._poll_cas)

    def _cas_worker(self, cas):
        """后台查 CAS，只写结果变量；UI 更新交给主线程轮询。"""
        smi, note = caslookup.resolve(cas)
        self._cas_result = (cas, smi, note)

    def _poll_cas(self):
        """主线程轮询，把 CAS 解析结果落到界面上。"""
        res = getattr(self, "_cas_result", None)
        if res is None:
            self.win.after(80, self._poll_cas)
            return
        self._cas_result = None
        cas, smi, note = res
        if smi is None:
            self.preview.configure(image="", width=32, height=13,
                                   text=f"CAS {cas}\n解析失败：{note}")
            self._auto_formula = self._auto_mw = self._auto_molfile = None
            return
        # 解析成功：回填 SMILES 并走 SMILES 同一条渲染/解析通道
        self.smiles.set(smi)
        self.on_parse(silent=True)
        if getattr(self, "_auto_molfile", None):
            cur = self.props.cget("text")
            self.props.configure(text=cur + f"\nCAS 来源  {note}")

    def _clear_preview(self):
        self.preview.configure(image="", text="（结构解析不了）", width=32, height=13)
        self.props.configure(text="")
        self._auto_formula = None
        self._auto_mw = None
        self._auto_molfile = None

    def save(self):
        name = self.vars["name"].get().strip()
        if not name:
            messagebox.showwarning("还差一步", "名称是必填的。", parent=self.win)
            return

        smiles = self.smiles.get().strip()
        formula = getattr(self, "_auto_formula", None) or (self.row["formula"] if self.row else "")
        mw = getattr(self, "_auto_mw", None)
        molfile = getattr(self, "_auto_molfile", None) or (self.row["molfile"] if self.row else "")

        if smiles and not formula:
            info = chem.analyze(smiles)
            if "error" not in info:
                formula, mw, molfile = info["formula"], info["mw"], info["molfile"]

        data = {
            "name": name,
            "code": self.vars["code"].get().strip(),
            "cas": self.vars["cas"].get().strip(),
            "smiles": smiles,
            "molfile": molfile,
            "formula": formula or "",
            "mw": float(mw) if mw else None,
            "purity": self.vars["purity"].get().strip(),
            "state": self.vars["state"].get().strip(),
            "location": self.vars["location"].get().strip(),
            "note": self.note.get("1.0", "end").strip(),
            "collection_id": getattr(self, "collection_id", None),
        }
        amt = self.vars["amount"].get().strip()
        try:
            from gui import norm_num
            data["amount"] = float(norm_num(amt)) if amt else None
        except ValueError:
            messagebox.showwarning("数量格式不对", "数量要写数字，比如 1.25", parent=self.win)
            return
        data["unit"] = self.vars["unit"].get().strip() or "g"

        try:
            if self.row:
                self.store.update_sample(self.row["id"], **data)
                sid = self.row["id"]
            else:
                sid = self.store.add_sample(**data)
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self.win)
            return

        self.win.destroy()
        self.on_saved(sid)


# ---------------------------------------------------------------- 反应组成

class ComponentDialog:
    def __init__(self, parent, store, on_ok, existing=None):
        self.store = store
        self.on_ok = on_ok
        self.existing = existing or {}
        self.samples = store.samples()

        self.win = tk.Toplevel(parent)
        self.win.title("添加组成" if not existing else "编辑组成")
        self.win.configure(bg=CARD)
        self.win.transient(parent)
        self.win.grab_set()

        wrap = tk.Frame(self.win, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=18, pady=14)
        wrap.columnconfigure(1, weight=1)

        r = 0
        tk.Label(wrap, text="物质", bg=CARD, fg=DIM, font=(UI, 9), width=7,
                 anchor="w").grid(row=r, column=0, sticky="w", pady=5)
        names = ["（手写名称）"] + [
            f"{s['name']}{' [' + s['code'] + ']' if s['code'] else ''}" for s in self.samples]
        self.pick = ttk.Combobox(wrap, values=names, state="readonly", font=(UI, 10))
        self.pick.grid(row=r, column=1, sticky="ew", pady=5)
        self.pick.current(0)
        r += 1

        tk.Label(wrap, text="手写名", bg=CARD, fg=DIM, font=(UI, 9), width=7,
                 anchor="w").grid(row=r, column=0, sticky="w", pady=5)
        self.label = tk.StringVar(value=self.existing.get("label", ""))
        tk.Entry(wrap, textvariable=self.label, font=(UI, 10), bd=1, relief="solid",
                 bg="#ffffff").grid(row=r, column=1, sticky="ew", pady=5, ipady=3)
        r += 1

        tk.Label(wrap, text="角色", bg=CARD, fg=DIM, font=(UI, 9), width=7,
                 anchor="w").grid(row=r, column=0, sticky="w", pady=5)
        self.role = ttk.Combobox(wrap, values=ROLES, state="readonly", font=(UI, 10))
        self.role.grid(row=r, column=1, sticky="ew", pady=5)
        self.role.set(self.existing.get("role", "反应物"))
        r += 1

        tk.Label(wrap, text="当量", bg=CARD, fg=DIM, font=(UI, 9), width=7,
                 anchor="w").grid(row=r, column=0, sticky="w", pady=5)
        self.eq = tk.StringVar(value=str(self.existing.get("equivalents") or ""))
        _bind_num_norm(self.eq)
        tk.Entry(wrap, textvariable=self.eq, font=(UI, 10), bd=1, relief="solid",
                 bg="#ffffff").grid(row=r, column=1, sticky="ew", pady=5, ipady=3)
        r += 1

        tk.Label(wrap, text="用量", bg=CARD, fg=DIM, font=(UI, 9), width=7,
                 anchor="w").grid(row=r, column=0, sticky="w", pady=5)
        amt_row = tk.Frame(wrap, bg=CARD)
        amt_row.grid(row=r, column=1, sticky="ew", pady=5)
        self.amt = tk.StringVar(value=str(self.existing.get("amount") or ""))
        _bind_num_norm(self.amt)
        tk.Entry(amt_row, textvariable=self.amt, font=(UI, 10), bd=1, relief="solid",
                 bg="#ffffff", width=12).pack(side="left", ipady=3)
        self.unit = ttk.Combobox(amt_row, values=["g", "mg", "mL", "μL", "mmol"], width=7,
                                 font=(UI, 9))
        self.unit.set(self.existing.get("unit") or "g")
        self.unit.pack(side="left", padx=6)

        btns = tk.Frame(self.win, bg=CARD)
        btns.pack(fill="x", padx=18, pady=(0, 14))
        tk.Button(btns, text="确定", command=self.ok, relief="flat", bd=0, bg=ACCENT,
                  fg="#ffffff", font=(UI, 10, "bold"), padx=20, pady=6,
                  cursor="hand2").pack(side="right")
        tk.Button(btns, text="取消", command=self.win.destroy, relief="flat", bd=0,
                  bg="#eef1f5", fg=INK, font=(UI, 10), padx=14, pady=6,
                  cursor="hand2").pack(side="right", padx=(0, 8))

        self.win.bind("<Escape>", lambda e: self.win.destroy())
        _center(self.win, parent, 420, 320)

    def ok(self):
        idx = self.pick.current()
        sample_id = None if idx <= 0 else self.samples[idx - 1]["id"]
        label = self.label.get().strip()
        if sample_id is None and not label:
            messagebox.showwarning("还差一步", "选一个药剂，或者手写一个名称。", parent=self.win)
            return
        from gui import norm_num
        try:
            eq = float(norm_num(self.eq.get())) if self.eq.get().strip() else None
        except ValueError:
            messagebox.showwarning("当量格式不对", "当量要写数字，比如 1.2。", parent=self.win)
            return
        try:
            amount = float(norm_num(self.amt.get())) if self.amt.get().strip() else None
        except ValueError:
            messagebox.showwarning("用量格式不对", "用量要写数字，比如 2.5。", parent=self.win)
            return

        self.on_ok({
            "sample_id": sample_id,
            "label": label,
            "role": self.role.get() or "反应物",
            "equivalents": eq,
            "amount": amount,
            "unit": self.unit.get() or "g",
        })
        self.win.destroy()


# ---------------------------------------------------------------- 反应

class ReactionDialog:
    def __init__(self, app, store, row, coll_id, on_saved):
        self.app = app
        self.store = store
        self.row = row
        self.on_saved = on_saved
        self.comps: list[dict] = []

        if row:
            for c in store.components(row["id"]):
                self.comps.append({
                    "sample_id": c["sample_id"], "label": c["label"] or "",
                    "role": c["role"], "equivalents": c["equivalents"],
                    "amount": c["amount"], "unit": c["unit"] or "g",
                    "_name": c["s_name"] or c["label"] or "",
                })

        self.win = tk.Toplevel(app.root)
        self.win.title("编辑反应" if row else "新建反应")
        self.win.configure(bg=CARD)
        self.win.transient(app.root)
        self.win.grab_set()
        self._build(row, coll_id)
        self.win.bind("<Escape>", lambda e: self.win.destroy())
        _center(self.win, app.root, 820, 620)

    def _build(self, row, coll_id):
        wrap = tk.Frame(self.win, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=18, pady=14)
        wrap.columnconfigure(1, weight=1)

        def field(label, var, r, hint=""):
            tk.Label(wrap, text=label, bg=CARD, fg=DIM, font=(UI, 9), width=8,
                     anchor="w").grid(row=r, column=0, sticky="w", pady=5)
            e = tk.Entry(wrap, textvariable=var, font=(UI, 10), bd=1, relief="solid",
                         bg="#ffffff", fg=INK)
            e.grid(row=r, column=1, sticky="ew", pady=5, ipady=3)
            if hint:
                tk.Label(wrap, text=hint, bg=CARD, fg="#a9b4c2", font=(UI, 8)).grid(
                    row=r, column=2, sticky="w", padx=(8, 0))
            return e

        self.title_var = tk.StringVar(value=row["title"] if row else "")
        field("标题 *", self.title_var, 0)
        self.code_var = tk.StringVar(value=row["code"] if row and row["code"] else "")
        field("编号", self.code_var, 1)
        self.yield_var = tk.StringVar(
            value=f"{row['yield_pct']:g}" if row and row["yield_pct"] is not None else "")
        field("产率", self.yield_var, 2, "% 可以不写")
        self.cond_var = tk.StringVar(value=row["conditions"] if row and row["conditions"] else "")
        field("条件", self.cond_var, 3, "温度 / 时间 / 气氛")

        tk.Label(wrap, text="操作", bg=CARD, fg=DIM, font=(UI, 9), width=8,
                 anchor="nw").grid(row=4, column=0, sticky="nw", pady=5)
        self.proc = tk.Text(wrap, height=6, font=(UI, 10), bd=1, relief="solid",
                            bg="#ffffff", fg=INK, wrap="word", padx=8, pady=6)
        self.proc.grid(row=4, column=1, columnspan=2, sticky="ew", pady=5)
        if row and row["procedure"]:
            self.proc.insert("1.0", row["procedure"])

        # 组成
        tk.Label(wrap, text="组成", bg=CARD, fg=INK, font=(UI, 11, "bold")).grid(
            row=5, column=0, sticky="w", pady=(12, 4))
        comp_btns = tk.Frame(wrap, bg=CARD)
        comp_btns.grid(row=5, column=1, sticky="w", pady=(12, 4))
        tk.Button(comp_btns, text="+ 添加", command=self.on_add_comp, relief="flat",
                  bd=0, bg="#e8f4ec", fg=GREEN, font=(UI, 9), padx=8, pady=3,
                  cursor="hand2").pack(side="left")
        self.btn_tpl = tk.Button(comp_btns, text="载入模板 ▾", command=self.on_load_template,
                                 relief="flat", bd=0, bg="#eef4fb", fg=ACCENT,
                                 font=(UI, 9), padx=8, pady=3, cursor="hand2")
        self.btn_tpl.pack(side="left", padx=8)

        self.comp_tree = ttk.Treeview(wrap, columns=("role", "name", "eq", "amt"),
                                      show="headings", height=5)
        for c, t, w in (("role", "角色", 70), ("name", "物质", 260),
                        ("eq", "当量", 70), ("amt", "用量", 110)):
            self.comp_tree.heading(c, text=t)
            self.comp_tree.column(c, width=w, anchor="w" if c == "name" else "center")
        self.comp_tree.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        self.comp_tree.bind("<Double-1>", lambda e: self.on_edit_comp())

        tk.Button(wrap, text="删除选中组成", command=self.on_del_comp, relief="flat",
                  bd=0, bg=CARD, fg="#c0392b", font=(UI, 8),
                  cursor="hand2").grid(row=7, column=1, sticky="w")

        btns = tk.Frame(self.win, bg=CARD)
        btns.pack(fill="x", padx=18, pady=(0, 14))
        tk.Button(btns, text="保存", command=self.save, relief="flat", bd=0, bg=ACCENT,
                  fg="#ffffff", font=(UI, 10, "bold"), padx=22, pady=6,
                  cursor="hand2").pack(side="right")
        tk.Button(btns, text="取消", command=self.win.destroy, relief="flat", bd=0,
                  bg="#eef1f5", fg=INK, font=(UI, 10), padx=16, pady=6,
                  cursor="hand2").pack(side="right", padx=(0, 8))
        tk.Label(btns, text="双击组成可以改", bg=CARD, fg="#a9b4c2",
                 font=(UI, 8)).pack(side="left")

        self.collection_id = row["collection_id"] if row and row["collection_id"] else coll_id
        self._refresh_comps()

    def _refresh_comps(self):
        self.comp_tree.delete(*self.comp_tree.get_children())
        for i, c in enumerate(self.comps):
            name = c.get("_name") or c.get("label") or "（未命名）"
            amt = f"{c['amount']:g} {c.get('unit') or ''}".strip() if c.get("amount") else ""
            eq = f"{c['equivalents']:g}" if c.get("equivalents") else ""
            self.comp_tree.insert("", "end", iid=str(i), values=(c["role"], name, eq, amt))

    def on_add_comp(self):
        ComponentDialog(self.win, self.store, self._add_comp)

    def on_load_template(self):
        """从模板预填标题 / 条件 / 操作 / 组成。"""
        tpls = self.store.templates("reaction")
        m = tk.Menu(self.win, tearoff=0, font=(UI, 9))
        if not tpls:
            m.add_command(label="（还没有模板，在反应详情页点「存为模板」）",
                          state="disabled")
        for t in tpls:
            m.add_command(label=t["name"],
                          command=lambda tt=t: self._apply_template(tt))
        x = self.btn_tpl.winfo_rootx()
        y = self.btn_tpl.winfo_rooty() + self.btn_tpl.winfo_height()
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def _apply_template(self, t):
        try:
            data = json.loads(t["content"] or "{}")
        except ValueError:
            messagebox.showwarning("模板坏了", "这个模板的内容不是合法 JSON。",
                                   parent=self.win)
            return
        if self.row:  # 编辑已有反应，确认覆盖
            if not messagebox.askyesno(
                    "载入模板",
                    f"用模板「{t['name']}」覆盖当前的标题、条件、操作和组成？",
                    parent=self.win):
                return
        if data.get("title"):
            self.title_var.set(data["title"])
        self.code_var.set("")
        self.cond_var.set(data.get("conditions") or "")
        self.proc.delete("1.0", "end")
        self.proc.insert("1.0", data.get("procedure") or "")
        comps = []
        for c in data.get("components") or []:
            c = dict(c)
            sid = c.get("sample_id")
            name = c.get("label") or ""
            if sid:
                srow = self.store.sample(sid)
                name = srow["name"] if srow else name
            c["_name"] = name
            comps.append(c)
        self.comps = comps
        self._refresh_comps()

    def _add_comp(self, data):
        sid = data.get("sample_id")
        name = data.get("label") or ""
        if sid:
            row = self.store.sample(sid)
            name = row["name"] if row else name
        data["_name"] = name
        self.comps.append(data)
        self._refresh_comps()

    def on_edit_comp(self):
        sel = self.comp_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        cur = self.comps[idx]

        def done(data):
            sid = data.get("sample_id")
            name = data.get("label") or ""
            if sid:
                row = self.store.sample(sid)
                name = row["name"] if row else name
            data["_name"] = name
            self.comps[idx] = data
            self._refresh_comps()

        dlg = ComponentDialog(self.win, self.store, done, existing=cur)
        if cur.get("sample_id"):
            names = dlg.pick["values"]
            for i, s in enumerate(dlg.samples, start=1):
                if s["id"] == cur["sample_id"]:
                    dlg.pick.current(i)
                    break

    def on_del_comp(self):
        sel = self.comp_tree.selection()
        if not sel:
            return
        del self.comps[int(sel[0])]
        self._refresh_comps()

    def save(self):
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("还差一步", "标题是必填的。", parent=self.win)
            return
        try:
            from gui import norm_num
            y = float(norm_num(self.yield_var.get())) if self.yield_var.get().strip() else None
        except ValueError:
            messagebox.showwarning("产率格式不对", "产率写数字，比如 85 或 92.5", parent=self.win)
            return

        data = {
            "title": title,
            "code": self.code_var.get().strip(),
            "conditions": self.cond_var.get().strip(),
            "procedure": self.proc.get("1.0", "end").strip(),
            "yield_pct": y,
            "collection_id": getattr(self, "collection_id", None),
        }
        try:
            if self.row:
                rid = self.row["id"]
                self.store.update_reaction(rid, **data)
                self.store.run("DELETE FROM reaction_components WHERE reaction_id=?", (rid,))
            else:
                rid = self.store.add_reaction(**data)
            for c in self.comps:
                self.store.add_component(rid, sample_id=c.get("sample_id"),
                                         role=c["role"], equivalents=c.get("equivalents"),
                                         amount=c.get("amount"), unit=c.get("unit"),
                                         label=c.get("label"))
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self.win)
            return

        self.win.destroy()
        self.on_saved(rid)
