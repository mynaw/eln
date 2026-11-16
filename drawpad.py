# -*- coding: utf-8 -*-
"""化学绘制区：画结构式 / 反应式，转 SMILES，和 ChemDraw 做文件交换。

设计取舍：
  - 画板是纯 Tkinter Canvas，不引入 WebView / COM，换台机器照样能画。
  - 图存成 JSON（原子、键、标签、箭头），随时能再打开编辑，不是死图片。
  - 化学合法性交给 RDKit：手绘的图 -> RWMol -> sanitize -> SMILES / molfile / RXN。
  - ChemDraw 只做「外部专业编辑器」：写 .mol / .rxn -> 打开 -> 用户保存 -> 读回。
    不实例化 ChemDraw.Application（会弹独立窗口、绑死本机授权）。

    from drawpad import Sketch, DrawWindow
    s = Sketch(); s.example_benzene(); print(s.smiles())
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, simpledialog, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk
from rdkit import Chem, RDLogger
from rdkit.Chem import AllChem, Descriptors, rdMolDescriptors
from rdkit.Geometry import Point3D

from paths import app_dir
from store import attach_dir_path

RDLogger.DisableLog("rdApp.*")


def exchange_dir() -> str:
    """ChemDraw 交换文件放在当前账户的附件目录下，各账户不混。"""
    return os.path.join(attach_dir_path(), "chemdraw")


def handoff_dir(create: bool = False) -> str:
    """ChemDraw 改稿的默认目录（``attachments/chemdraw/edited``）。

    为什么要单独开一层：ChemDraw 的「另存为」默认落在*当前打开文件所在的
    目录*。以前导出文件写在 ``attachments/chemdraw/``，用户另存时被它记事
    的默认路径（常常是桌面）带跑，改好的结构存到别处，回来读回拿到的还是
    那份只有箭头的原始导出件——看起来就像"读回只能读到箭头"。

    现在导出件直接写进这个目录并从这儿打开，另存默认就回到同一处，
    覆盖原文件即可。``create=True`` 时会按需建目录。
    """
    d = os.path.join(exchange_dir(), "edited")
    if create:
        os.makedirs(d, exist_ok=True)
        note = os.path.join(d, "把文件存回本目录.txt")
        if not os.path.isfile(note):
            try:
                with open(note, "w", encoding="utf-8") as fh:
                    fh.write(
                        "这个目录是 ELN 与 ChemDraw 之间的默认交换目录。\n\n"
                        "从 ELN 点「用 ChemDraw 编辑」时，导出文件就写在这里，\n"
                        "所以你在 ChemDraw 里按 Ctrl+S / 另存为，默认位置就是本目录，\n"
                        "直接覆盖 ELN-drawing.cdxml 即可，不用另找地方。\n\n"
                        "改完回到 ELN 点「读回 ChemDraw 文件」，默认也打开这个目录。\n"
                        "如果改存到了别处，读回时手动切到那个目录选文件。\n\n"
                        "本目录可以随时清空——它只是中转站，结构本身存在 ELN 里。\n")
            except OSError:
                pass
    return d


HERE = app_dir()
CHEMDRAW_EXE = r"C:\Program Files\RevvitySignalsSoftware\ChemDrawApplications_x64\ChemDraw.exe"

# CDXML 根元素的默认属性：照抄 ChemDraw 26 自己写出的文件。
# 少了这些默认值，带 <arrow>/<scheme> 的文件会被 CDXMLParser 判为无效
# （报 Assertion "document != nullptr" failed）。
CDXML_ROOT_ATTRS = [
    ('FractionalWidths', 'yes'),
    ('InterpretChemically', 'yes'),
    ('ShowAtomQuery', 'yes'),
    ('ShowAtomStereo', 'no'),
    ('ShowAtomEnhancedStereo', 'yes'),
    ('ShowAtomNumber', 'no'),
    ('ShowResidueID', 'no'),
    ('ShowBondQuery', 'yes'),
    ('ShowBondRxn', 'yes'),
    ('ShowBondStereo', 'no'),
    ('ShowTerminalCarbonLabels', 'no'),
    ('ShowNonTerminalCarbonLabels', 'no'),
    ('HideImplicitHydrogens', 'no'),
    ('LabelFont', '3'),
    ('LabelSize', '10'),
    ('LabelFace', '96'),
    ('CaptionFont', '3'),
    ('CaptionSize', '10'),
    ('HashSpacing', '2.50'),
    ('MarginWidth', '1.60'),
    ('LineWidth', '0.60'),
    ('BoldWidth', '2'),
    ('BondLength', '14.40'),
    ('BondSpacing', '18'),
    ('ChainAngle', '120'),
    ('LabelJustification', 'Auto'),
    ('CaptionJustification', 'Left'),
    ('AminoAcidTermini', 'HOH'),
    ('ShowSequenceTermini', 'yes'),
    ('ShowSequenceBonds', 'yes'),
    ('ShowSequenceUnlinkedBranches', 'no'),
    ('ShowPrimeLabels', 'no'),
    ('ResidueWrapCount', '40'),
    ('PrintMargins', '36 36 36 36'),
    ('ChemPropName', ''),
    ('ChemPropFormula', 'Chemical Formula: '),
    ('ChemPropExactMass', 'Exact Mass: '),
    ('ChemPropMolWt', 'Molecular Weight: '),
    ('ChemPropMOverZ', 'm/z: '),
    ('ChemPropAnalysis', 'Elemental Analysis: '),
    ('ChemPropBoilingPt', 'Boiling Point: '),
    ('ChemPropMeltingPt', 'Melting Point: '),
    ('ChemPropCritTemp', 'Critical Temp: '),
    ('ChemPropCritPres', 'Critical Pres: '),
    ('ChemPropCritVol', 'Critical Vol: '),
    ('ChemPropGibbs', 'Gibbs Energy: '),
    ('ChemPropLogP', 'Log P: '),
    ('ChemPropMR', 'MR: '),
    ('ChemPropHenry', "Henry's Law: "),
    ('ChemPropEForm', 'Heat of Form: '),
    ('ChemProptPSA', 'tPSA: '),
    ('ChemPropCLogP', 'CLogP: '),
    ('ChemPropCMR', 'CMR: '),
    ('ChemPropLogS', 'LogS: '),
    ('ChemPropPKa', 'pKa: '),
    ('ChemPropID', ''),
    ('ChemPropFragmentLabel', ''),
    ('color', '0'),
    ('bgcolor', '1'),
    ('RxnAutonumberStart', '1'),
    ('RxnAutonumberConditions', 'no'),
    ('RxnAutonumberStyle', 'Roman'),
    ('RxnAutonumberFormat', '(#)'),
]

UI = "Microsoft YaHei UI"
MONO = UI   # 字体统一：等宽位也用同一族
INK = "#16202c"
DIM = "#6b7684"
ACCENT = "#1f6feb"
TOOL_ACTIVE_BG = "#0b3f91"   # 选中工具的底色（避开各角色按钮本色）
GREEN = "#1a7f4b"
RED = "#c0392b"
BOND = "#374151"
GRID = "#eef2f7"

ELEMENTS = ["C", "N", "O", "S", "P", "F", "Cl", "Br", "I", "H"]
ELEMENT_COLORS = {"O": "#c0392b", "N": "#1f4e9c", "S": "#a06800",
                  "F": "#1a7f4b", "Cl": "#1a7f4b", "Br": "#1a7f4b",
                  "I": "#6b3fa0", "P": "#a06800", "H": "#6b7684"}

BOND_TYPES = {1: Chem.BondType.SINGLE, 2: Chem.BondType.DOUBLE,
              3: Chem.BondType.TRIPLE}
CANVAS_W, CANVAS_H = 680, 520
GRID_STEP = 20
H_BOND = 30.0            # 「显示 H」时补画的 H 离父原子的距离（画板单位）


def _free_angles(taken, count):
    """在已有键方向之间挑 count 个最空的角度，避免 H 压住键或彼此重叠。"""
    if count <= 0:
        return []
    def dist(a, b):
        return abs((a - b + math.pi) % (2 * math.pi) - math.pi)
    cands = [2 * math.pi * k / 72 for k in range(72)]
    def clearance(a):
        return math.pi if not taken else min(dist(a, t) for t in taken)
    chosen = []
    for a in sorted(cands, key=lambda v: -clearance(v)):
        if all(dist(a, c) > 0.72 for c in chosen):
            chosen.append(a)
            if len(chosen) == count:
                break
    k = 0
    while len(chosen) < count:          # 空隙不够的极端情况：均匀补齐
        chosen.append(2 * math.pi * k / max(1, count))
        k += 1
    return chosen


def _atomic_number(sym: str) -> int:
    """元素符号 -> 原子序数；认不出来就按碳处理。"""
    try:
        return Chem.GetPeriodicTable().GetAtomicNumber(sym) or 6
    except Exception:
        return 6


# 反应角色
ROLE_REACTANT = "reactant"
ROLE_PRODUCT = "product"
ROLE_CATALYST = "catalyst"
ROLE_SOLVENT = "solvent"
ROLE_ORDER = (ROLE_REACTANT, ROLE_PRODUCT, ROLE_CATALYST, ROLE_SOLVENT)
ROLE_NAMES = {ROLE_REACTANT: "反应物", ROLE_PRODUCT: "产物",
              ROLE_CATALYST: "催化剂", ROLE_SOLVENT: "溶剂"}
ROLE_COLORS = {ROLE_REACTANT: "#1f6feb", ROLE_PRODUCT: "#1a7f4b",
               ROLE_CATALYST: "#a06800", ROLE_SOLVENT: "#6b3fa0"}
ROLE_BADGES = {ROLE_REACTANT: "R", ROLE_PRODUCT: "P",
               ROLE_CATALYST: "Cat", ROLE_SOLVENT: "Solv"}


def tool_title(tool: str) -> str:
    """把内部工具名换成状态栏上给人看的中文。"""
    if not tool:
        return "未选择"
    if tool.startswith("atom:"):
        return "原子 " + tool.split(":", 1)[1]
    if tool.startswith("bond:"):
        return {"1": "单键", "2": "双键", "3": "三键"}.get(
            tool.split(":", 1)[1], "键")
    if tool.startswith("ring:"):
        return "苯环" if tool.endswith("arom") else "环己烷"
    if tool.startswith("role:"):
        return "标记" + ROLE_NAMES.get(tool.split(":", 1)[1], "")
    return {"select": "选择 / 拖动", "abbrev": "缩写基团", "label": "文字",
            "arrow": "反应箭头", "erase": "橡皮（点删）",
            "box": "框选删除"}.get(tool, tool)


def _font(size: int):
    for path in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
                 r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


_PT = Chem.GetPeriodicTable()

# 这些写法在有机化学里几乎一定是缩写，即使恰好等于某个元素符号
COMMON_ABBREV = {
    "Ac", "Bn", "Bz", "Et", "Me", "Pr", "Bu", "iPr", "tBu", "TBS", "TBDPS",
    "Boc", "Cbz", "Fmoc", "Ts", "Ms", "Tf", "Tr", "Ph", "Alloc", "THP", "Piv",
    "TMS", "TIPS", "DMP", "NBS", "NCS", "DMF", "THF", "DCM", "DMSO",
}


def is_element_symbol(sym: str) -> bool:
    try:
        return 1 <= _PT.GetAtomicNumber(sym) <= 118
    except Exception:
        return False


def parse_atom_text(text: str) -> tuple[str, str]:
    """把用户输入拆成 (元素符号, 缩写文字)。

    'Cl'      -> ('Cl', '')       纯元素
    'OBz'     -> ('O',  'OBz')    O 上挂 Bz
    'CH2OBz'  -> ('C',  'CH2OBz')
    'Ph'/'TBS'-> ('C',  'Ph')     不以元素开头的整体当缩写
    'Ac'      -> ('C',  'Ac')     乙酰基，不按锕处理
    """
    t = (text or "").strip()
    if not t:
        return ("C", "")
    if t in COMMON_ABBREV:
        return ("C", t)
    m = re.match(r"^([A-Z][a-z]?)(.*)$", t)
    if m:
        sym, rest = m.group(1), m.group(2)
        if is_element_symbol(sym):
            if not rest:
                return (sym, "")
            head = rest[0]
            # OBz / CH2OBz / CO2Et：元素后面紧跟大写或数字，才视为「元素 + 缩写」
            if head.isupper() or head.isdigit() or not head.isalpha():
                return (sym, t)
    return ("C", t)


def parse_atom_attrs(text: str) -> tuple[str, str, int, int]:
    """把输入拆成 (元素符号, 缩写文字, 电荷, 同位素质量数)。

    'N+'   -> ('N', '',  +1, 0)
    'O-'   -> ('O', '',  -1, 0)
    'S2+'  -> ('S', '',  +2, 0)
    '13C'  -> ('C', '',   0, 13)
    'OBz'  -> ('O', 'OBz', 0, 0)
    """
    t = (text or "").strip()
    if not t:
        return ("C", "", 0, 0)
    iso = 0
    m = re.match(r"^(\d+)([A-Za-z].*)$", t)
    if m and 1 <= int(m.group(1)) <= 300:
        iso = int(m.group(1))
        t = m.group(2)
    charge = 0
    m = re.search(r"(\d*)\s*([+\-±∓]+)$", t)
    if m:
        n = int(m.group(1)) if m.group(1) else 1
        neg = any(ch in m.group(2) for ch in "-−")
        charge = -n if neg else n
        t = t[:m.start()].strip()
    sym, lab = parse_atom_text(t)
    return sym, lab, charge, iso


# ---------------------------------------------------------------- 数据模型

class Sketch:
    """一张可编辑的图。坐标就是画布像素，序列化后仍然是同一套坐标。"""

    def __init__(self, mode="structure", title="", atoms=None, bonds=None,
                 labels=None, arrows=None, roles=None):
        self.mode = mode                      # structure / scheme
        self.title = title
        self.atoms: list[dict] = atoms or []  # {"id":1,"e":"C","x":120,"y":80}
        self.bonds: list[dict] = bonds or []  # {"a":1,"b":2,"o":1}
        self.labels: list[dict] = labels or []
        self.arrows: list[dict] = arrows or []
        # 片段角色：{"锚点原子id": "reactant"|"product"|"catalyst"|"solvent"}
        # 锚点取该连通片段里最小的原子 id；片段增删后找不到就退回自动判定
        self.roles: dict[str, str] = roles or {}
        self._next = 1 + max([a["id"] for a in self.atoms] or [0])
        self._next_lid = 1 + max([l.get("id", 0) for l in self.labels] or [0])
        self._next_aid = 1 + max([a.get("id", 0) for a in self.arrows] or [0])

    def ensure_obj_ids(self):
        """旧图里的文字 / 箭头没有 id，补上并把计数器推到后面。"""
        for i, l in enumerate(self.labels):
            if not l.get("id"):
                l["id"] = i + 1
        for i, a in enumerate(self.arrows):
            if not a.get("id"):
                a["id"] = i + 1
        self._next_lid = max([l.get("id", 0) for l in self.labels] or [0]) + 1
        self._next_aid = max([a.get("id", 0) for a in self.arrows] or [0]) + 1
        self._next = 1 + max([a["id"] for a in self.atoms] or [0])

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict:
        return {"mode": self.mode, "title": self.title,
                "atoms": self.atoms, "bonds": self.bonds,
                "labels": self.labels, "arrows": self.arrows,
                "roles": self.roles}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "Sketch":
        s = cls(d.get("mode", "structure"), d.get("title", ""),
                [dict(a) for a in d.get("atoms", [])],
                [dict(b) for b in d.get("bonds", [])],
                [dict(l) for l in d.get("labels", [])],
                [dict(a) for a in d.get("arrows", [])],
                {str(k): v for k, v in d.get("roles", {}).items()})
        s.ensure_obj_ids()
        return s

    @classmethod
    def from_json(cls, text: str) -> "Sketch":
        return cls.from_dict(json.loads(text or "{}"))

    def copy(self) -> "Sketch":
        return Sketch.from_dict(json.loads(self.to_json()))

    # ------------------------------------------------------------ 编辑
    def add_atom(self, element: str, x: float, y: float,
                 label: str = "", charge: int = 0, isotope: int = 0) -> int:
        aid = self._next
        self._next += 1
        a = {"id": aid, "e": element, "x": float(x), "y": float(y)}
        if label:
            a["label"] = label
        if charge:
            a["charge"] = int(charge)
        if isotope:
            a["isotope"] = int(isotope)
        self.atoms.append(a)
        return aid

    def atom(self, aid: int):
        return next((a for a in self.atoms if a["id"] == aid), None)

    @staticmethod
    def atom_label(a) -> str:
        """需要显示的文字；碳且无缩写时返回空串。"""
        lab = (a.get("label") or "").strip()
        if lab:
            return lab
        return "" if a["e"] == "C" else a["e"]

    @staticmethod
    def atom_shows_text(a) -> bool:
        """这个原子要不要写成文字（碳带电荷/同位素时也要写）。"""
        if (a.get("label") or "").strip():
            return True
        if a.get("charge") or a.get("isotope"):
            return True
        return a["e"] != "C"

    @staticmethod
    def atom_display(a) -> str:
        """画在原子位置上的完整文字：同位素 + 元素/缩写 + 电荷。"""
        lab = (a.get("label") or "").strip()
        base = lab if lab else a["e"]
        iso = int(a.get("isotope") or 0)
        ch = int(a.get("charge") or 0)
        text = (str(iso) + base) if iso else base
        if ch:
            text += ("+" if ch > 0 else "-") * (abs(ch) if abs(ch) > 1 else 1)
        return text

    def is_abbrev(self, a) -> bool:
        return bool((a.get("label") or "").strip())

    def abbrev_count(self) -> int:
        return sum(1 for a in self.atoms if self.is_abbrev(a))

    def add_bond(self, a1: int, a2: int, order: int = 1):
        if a1 == a2:
            return
        for b in self.bonds:
            if {b["a"], b["b"]} == {a1, a2}:
                b["o"] = order if order != b["o"] else (b["o"] % 3) + 1
                return
        self.bonds.append({"a": a1, "b": a2, "o": order})

    # ------------------------------------------------------------ 文字 / 箭头
    def add_label(self, x: float, y: float, text: str) -> int:
        """加一条文字标注，返回它的 id（可选中、可整体移动）。"""
        lid = self._next_lid
        self._next_lid += 1
        self.labels.append({"id": lid, "x": float(x), "y": float(y), "text": text})
        return lid

    def add_arrow(self, x1: float, y1: float, x2: float, y2: float) -> int:
        """加一根反应箭头，返回它的 id。"""
        aid = self._next_aid
        self._next_aid += 1
        self.arrows.append({"id": aid, "x1": float(x1), "y1": float(y1),
                            "x2": float(x2), "y2": float(y2)})
        return aid

    def label_by_id(self, lid: int):
        return next((l for l in self.labels if l.get("id") == lid), None)

    def arrow_by_id(self, aid: int):
        return next((a for a in self.arrows if a.get("id") == aid), None)

    @staticmethod
    def label_hit(l, x: float, y: float, r: float) -> bool:
        return math.hypot(l["x"] - x, l["y"] - y) <= r

    @staticmethod
    def arrow_hit(a, x: float, y: float, r: float) -> bool:
        """点到箭头本身（中点）或端点附近都算命中。"""
        x1, y1, x2, y2 = a["x1"], a["y1"], a["x2"], a["y2"]
        if math.hypot((x1 + x2) / 2 - x, (y1 + y2) / 2 - y) <= r:
            return True
        return (math.hypot(x1 - x, y1 - y) <= r
                or math.hypot(x2 - x, y2 - y) <= r)

    def remove_atom(self, aid: int):
        self.atoms = [a for a in self.atoms if a["id"] != aid]
        self.bonds = [b for b in self.bonds if aid not in (b["a"], b["b"])]
        self.prune_roles()

    def add_ring(self, cx: float, cy: float, aromatic=True) -> list[int]:
        r = 46
        ids = []
        for i in range(6):
            ang = math.radians(-90 + 60 * i)
            ids.append(self.add_atom("C", cx + r * math.cos(ang),
                                     cy + r * math.sin(ang)))
        for i in range(6):
            order = (2 if i % 2 == 0 else 1) if aromatic else 1
            self.add_bond(ids[i], ids[(i + 1) % 6], order)
        return ids

    def nearest_atom(self, x, y, radius=22):
        best, dist = None, radius
        for a in self.atoms:
            d = math.hypot(a["x"] - x, a["y"] - y)
            if d < dist:
                best, dist = a, d
        return best

    def nearest_bond(self, x, y, radius=10):
        best, dist = None, radius
        for b in self.bonds:
            p, q = self.atom(b["a"]), self.atom(b["b"])
            if not p or not q:
                continue
            d = self._point_line(x, y, p["x"], p["y"], q["x"], q["y"])
            if d < dist:
                best, dist = b, d
        return best

    @staticmethod
    def _point_line(px, py, x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        n = dx * dx + dy * dy
        if n == 0:
            return math.hypot(px - x1, py - y1)
        t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / n))
        return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))

    # ------------------------------------------------------------ 连通分量
    def fragments(self) -> list[list[int]]:
        adj: dict[int, list[int]] = {a["id"]: [] for a in self.atoms}
        for b in self.bonds:
            if b["a"] in adj and b["b"] in adj:
                adj[b["a"]].append(b["b"])
                adj[b["b"]].append(b["a"])
        seen, out = set(), []
        for a in self.atoms:
            aid = a["id"]
            if aid in seen:
                continue
            stack, group = [aid], []
            seen.add(aid)
            while stack:
                cur = stack.pop()
                group.append(cur)
                for nb in adj.get(cur, []):
                    if nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            out.append(group)
        return out

    # ------------------------------------------------------------ 反应角色
    def fragment_at(self, aid: int) -> list[int]:
        for group in self.fragments():
            if aid in group:
                return group
        return []

    def fragment_role(self, ids) -> str:
        if not ids:
            return ""
        return self.roles.get(str(min(ids)), "")

    def set_role(self, ids, role: str):
        """role 传空表示清除，退回按位置自动判定。"""
        if not ids:
            return
        anchor = str(min(ids))
        self.roles.pop(anchor, None)
        if role:
            self.roles[anchor] = role

    def prune_roles(self):
        alive = {str(a["id"]) for a in self.atoms}
        for k in [k for k in self.roles if k not in alive]:
            self.roles.pop(k, None)

    def main_arrow(self):
        return min(self.arrows, key=lambda a: a["x1"]) if self.arrows else None

    def _frag_bbox(self, ids):
        pts = [(self.atom(i)["x"], self.atom(i)["y"]) for i in ids if self.atom(i)]
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    def shift(self, ids, dx, dy):
        for i in ids:
            a = self.atom(i)
            if a:
                a["x"] += dx
                a["y"] += dy

    def reaction_groups(self) -> dict:
        """按角色分组；没标角色的片段按箭头左右自动归到反应物/产物。"""
        out = {r: [] for r in ROLE_ORDER}
        out[""] = []
        frags = self.fragments()
        if not frags:
            return out
        arr = self.main_arrow()
        mid = (arr["x1"] + arr["x2"]) / 2 if arr else None
        for ids in frags:
            role = self.fragment_role(ids)
            if role in ROLE_ORDER:
                out[role].append(ids)
            elif mid is None:
                out[ROLE_REACTANT].append(ids)
            else:
                bb = self._frag_bbox(ids)
                cx = (bb[0] + bb[2]) / 2
                out[ROLE_REACTANT if cx < mid else ROLE_PRODUCT].append(ids)
        return out

    def _row_left(self, groups, right_edge, cy, gap=64):
        """在 right_edge 左侧横向排开；最后一个片段紧贴箭头（加入顺序从右往左）。"""
        if not groups:
            return
        x = right_edge
        for ids in reversed(groups):
            bb = self._frag_bbox(ids)
            if not bb:
                continue
            w = bb[2] - bb[0]
            self.shift(ids, (x - w) - bb[0], cy - (bb[1] + bb[3]) / 2)
            x -= w + gap

    def _row_right(self, groups, left_edge, cy, gap=64):
        """在 left_edge 右侧横向排开；第一个片段紧贴箭头。"""
        if not groups:
            return
        x = left_edge
        for ids in groups:
            bb = self._frag_bbox(ids)
            if not bb:
                continue
            w = bb[2] - bb[0]
            self.shift(ids, x - bb[0], cy - (bb[1] + bb[3]) / 2)
            x += w + gap

    def _row_centered(self, groups, cx, cy, gap=72):
        """一行整体居中于 cx，每个片段的垂直中心对齐 cy。"""
        if not groups:
            return
        boxes = [self._frag_bbox(g) for g in groups]
        widths = [(b[2] - b[0]) if b else 0.0 for b in boxes]
        total = sum(widths) + gap * (len(groups) - 1)
        x = cx - total / 2
        for ids, bb, w in zip(groups, boxes, widths):
            if not bb:
                continue
            self.shift(ids, x - bb[0], cy - (bb[1] + bb[3]) / 2)
            x += w + gap

    def layout_reaction(self, hgap=70, vgap=120) -> int:
        """按角色摆位：反应物在箭头左侧横向排开、产物在右侧、
        催化剂在上方一行、溶剂在下方一行，同一行水平对齐。"""
        groups = self.reaction_groups()
        count = sum(len(v) for v in groups.values())
        if not count:
            return 0
        arr = self.main_arrow()
        if arr is None:
            b = self.bounds(0)
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            arr = {"x1": cx - 70, "y1": cy, "x2": cx + 70, "y2": cy}
            self.add_arrow(arr["x1"], arr["y1"], arr["x2"], arr["y2"])
        ax = (arr["x1"] + arr["x2"]) / 2
        cy = arr["y1"]
        self._row_left(groups[ROLE_REACTANT], arr["x1"] - hgap, cy)
        self._row_right(groups[ROLE_PRODUCT], arr["x2"] + hgap, cy)
        self._row_centered(groups[ROLE_CATALYST], ax, cy - vgap)
        self._row_centered(groups[ROLE_SOLVENT], ax, cy + vgap)

        # 排完可能跑到负坐标，整体挪回可视区
        b = self.bounds(0)
        dx = max(0.0, 40 - b[0])
        dy = max(0.0, 40 - b[1])
        if dx or dy:
            for a in self.atoms:
                a["x"] += dx
                a["y"] += dy
            for l in self.labels:
                l["x"] += dx
                l["y"] += dy
            for r in self.arrows:
                r["x1"] += dx
                r["y1"] += dy
                r["x2"] += dx
                r["y2"] += dy
        self.mode = "scheme"
        return count

    def clear_all(self):
        """清掉全部内容（调用方负责先存撤销点）。"""
        self.atoms, self.bonds = [], []
        self.labels, self.arrows = [], []
        self.roles.clear()
        self._next = 1
        self._next_lid = self._next_aid = 1

    def erase_rect(self, x0, y0, x1, y1) -> int:
        """删除矩形范围内的原子（连带其键）、文字与箭头，返回删除的元素数。"""
        xa, xb = (x0, x1) if x0 <= x1 else (x1, x0)
        ya, yb = (y0, y1) if y0 <= y1 else (y1, y0)

        def inside(x, y):
            return xa <= x <= xb and ya <= y <= yb

        keep = [a for a in self.atoms if not inside(a["x"], a["y"])]
        n_atoms = len(self.atoms) - len(keep)
        n_labels = sum(1 for l in self.labels if inside(l["x"], l["y"]))
        n_arrows = sum(1 for r in self.arrows
                       if inside(r["x1"], r["y1"]) or inside(r["x2"], r["y2"])
                       or inside((r["x1"] + r["x2"]) / 2, (r["y1"] + r["y2"]) / 2))
        if not (n_atoms or n_labels or n_arrows):
            return 0
        alive = {a["id"] for a in keep}
        self.atoms = keep
        self.bonds = [b for b in self.bonds if b["a"] in alive and b["b"] in alive]
        self.labels = [l for l in self.labels if not inside(l["x"], l["y"])]
        self.arrows = [r for r in self.arrows
                       if not (inside(r["x1"], r["y1"]) or inside(r["x2"], r["y2"])
                               or inside((r["x1"] + r["x2"]) / 2, (r["y1"] + r["y2"]) / 2))]
        self.prune_roles()
        return n_atoms + n_labels + n_arrows

    # ------------------------------------------------------------ RDKit
    def mol_for(self, ids) -> tuple[Chem.Mol | None, str]:
        """把一组原子构成 RDKit Mol，带上画布坐标（转成 Å 量级）。"""
        ids = [i for i in ids if self.atom(i) is not None]
        if not ids:
            return None, "画布还是空的"
        index = {aid: k for k, aid in enumerate(ids)}
        rw = Chem.RWMol()
        for aid in ids:
            a = self.atom(aid)
            # 缩写基团当作 dummy 原子（SMILES 里是 *），并写上别名，
            # 这样导出的 .mol 在 ChemDraw 里仍显示 OBz 而不是 *
            if self.is_abbrev(a):
                at = Chem.Atom(0)
                at.SetProp("molFileAlias", (a.get("label") or "").strip())
                rw.AddAtom(at)
            else:
                at = Chem.Atom(a["e"])
                ch = int(a.get("charge") or 0)
                iso = int(a.get("isotope") or 0)
                if ch:
                    at.SetFormalCharge(ch)
                if iso:
                    at.SetIsotope(iso)
                rw.AddAtom(at)
        for b in self.bonds:
            if b["a"] in index and b["b"] in index:
                rw.AddBond(index[b["a"]], index[b["b"]],
                           BOND_TYPES.get(int(b["o"]), Chem.BondType.SINGLE))
        mol = rw.GetMol()
        try:
            Chem.SanitizeMol(mol)
        except Exception as e:
            return None, f"结构不合法：{str(e).splitlines()[0][:90]}"
        conf = Chem.Conformer(len(ids))
        for aid, k in index.items():
            a = self.atom(aid)
            conf.SetAtomPosition(k, Point3D(a["x"] / 32.0, -a["y"] / 32.0, 0.0))
        mol.AddConformer(conf)
        return mol, ""

    def hydrogen_overlays(self) -> list[dict]:
        """补画的氢原子（纯显示，不写进 self.atoms，也不影响 SMILES/MOL 导出）。

        RDKit 的 AddHs 只用来算「每个重原子还缺几个 H」；它自带的坐标会重叠
        （同一个 CH2 的两个 H 几乎同点），所以位置改由 _free_angles() 放到
        该原子周围最空的方向上。返回 [{"x","y","px","py"}]，px/py 为父原子坐标。
        """
        out = []
        for ids in self.fragments():
            mol, _err = self.mol_for(ids)
            if mol is None:
                continue
            try:
                mh = Chem.AddHs(mol)
            except Exception:  # noqa: BLE001  价态不合法就跳过这一片
                continue
            n = mol.GetNumAtoms()
            counts: dict[int, int] = {}
            for i in range(n, mh.GetNumAtoms()):
                at = mh.GetAtomWithIdx(i)
                if at.GetAtomicNum() != 1:
                    continue
                for nb in at.GetNeighbors():
                    if nb.GetIdx() < n:
                        counts[nb.GetIdx()] = counts.get(nb.GetIdx(), 0) + 1
            for idx, cnt in counts.items():
                a = self.atom(ids[idx])
                if a is None or self.is_abbrev(a):
                    continue
                ax, ay = a["x"], a["y"]
                angs = []
                for b in self.bonds:
                    other = None
                    if b["a"] == a["id"]:
                        other = self.atom(b["b"])
                    elif b["b"] == a["id"]:
                        other = self.atom(b["a"])
                    if other is not None:
                        angs.append(math.atan2(other["y"] - ay, other["x"] - ax))
                for ang in _free_angles(angs, cnt):
                    out.append({"px": ax, "py": ay,
                                "x": ax + math.cos(ang) * H_BOND,
                                "y": ay + math.sin(ang) * H_BOND})
        return out

    @staticmethod
    def _smi(mol) -> str:
        return Chem.MolToSmiles(mol) if mol is not None else ""

    def split_scheme(self):
        """按角色（没标角色的按箭头左右）分成 反应物 / 产物 / 条件。"""
        groups = self.reaction_groups()
        reactants = groups[ROLE_REACTANT]
        products = groups[ROLE_PRODUCT]
        agents = []
        arr = self.main_arrow()
        if arr:
            top = min(arr["y1"], arr["y2"]) - 8
            agents = [l["text"] for l in self.labels
                      if l["y"] < top and arr["x1"] - 60 <= l["x"] <= arr["x2"] + 60]
        # 催化剂 / 溶剂的分子片段也当条件，不塞进 >> 两侧
        for role in (ROLE_CATALYST, ROLE_SOLVENT):
            for ids in groups[role]:
                mol, _ = self.mol_for(ids)
                if mol is not None:
                    agents.append(self._smi(mol))
        return reactants, products, agents

    def smiles(self) -> tuple[str, str]:
        """返回 (SMILES, 错误说明)。反应式返回 A>>B 形式。"""
        frags = self.fragments()
        if not frags:
            return "", "画布还是空的"
        parts, errs = [], []
        for group in frags:
            mol, err = self.mol_for(group)
            if mol is not None:
                parts.append(self._smi(mol))
            elif err:
                errs.append(err)
        if not parts:
            return "", errs[0] if errs else "结构解析不了"

        if self.mode == "scheme" and (self.arrows or self.roles):
            reactants, products, _agents = self.split_scheme()
            left, right = [], []
            for group in reactants:
                mol, _ = self.mol_for(group)
                if mol is not None:
                    left.append(self._smi(mol))
            for group in products:
                mol, _ = self.mol_for(group)
                if mol is not None:
                    right.append(self._smi(mol))
            if left and right:
                return ".".join(left) + ">>" + ".".join(right), ""
            # 只标了一侧（比如刚放好反应物），先按普通结构给出
        return ".".join(parts), errs[0] if errs else ""

    def molfile(self) -> tuple[str, str]:
        mol, err = self.mol_for([a["id"] for a in self.atoms])
        if mol is None:
            return "", err
        return Chem.MolToMolBlock(mol), ""

    def rxnfile(self) -> tuple[str, str]:
        """手写 MDL RXN；头部按 RDKit 要求写满 5 行。"""
        reactants, products, _ = self.split_scheme()
        blocks = []
        for group in reactants + products:
            mol, err = self.mol_for(group)
            if mol is None:
                return "", err
            blocks.append("$MOL\n" + Chem.MolToMolBlock(mol).rstrip() + "\n")
        if not blocks:
            return "", "反应式里没有结构"
        head = f"$RXN\n{self.title or 'ELN reaction'}\n\n\n" \
               f"{len(reactants):3d}{len(products):3d}\n"
        return head + "".join(blocks), ""

    # ------------------------------------------------------------ CDXML
    def cdxmlfile(self) -> tuple[str, str]:
        """生成 ChemDraw XML（CDXML）：结构 + 反应箭头 + 箭头上的文字标注。

        为什么不用 RXN：MDL RXN 只存反应物 / 产物，反应箭头和箭头上的
        试剂、条件文字一律丢失，ChemDraw 打开后是裸结构，试剂只能手敲。
        CDXML 是 ChemDraw 自己的 XML，箭头、文字、中文缩写都能带过去。

        元素层级（照 ChemDraw 26 自己写出的文件照抄，这是关键）：
            <page>          页面级：BoundingBox
              <fragment>    只放 <n> 原子与 <b> 键
              <t>           独立文字（试剂/条件）在 **page 级**，不在 fragment 里
              <arrow>       箭头也在 **page 级**
        箭头用 Head3D / Tail3D 表示端点（不是 B/E——B/E 是 <line> 的属性，
        写在 <arrow> 上会让 CDXMLParser 建不出对象，ChemDraw 直接抛
        「Assertion document != nullptr failed in CDXMLParser.cpp」）。
        """
        import xml.etree.ElementTree as ET

        xs = ([a["x"] for a in self.atoms] + [l["x"] for l in self.labels]
              + [v for r in self.arrows for v in (r["x1"], r["x2"])])
        ys = ([a["y"] for a in self.atoms] + [l["y"] for l in self.labels]
              + [v for r in self.arrows for v in (r["y1"], r["y2"])])
        if not xs:
            return "", "画布是空的，没什么可导出"
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)

        lens = []
        for b in self.bonds:
            p, q = self.atom(b["a"]), self.atom(b["b"])
            if p and q:
                lens.append(math.hypot(p["x"] - q["x"], p["y"] - q["y"]))
        # 以实际键长换算，让 ChemDraw 里键长就是标准的 14.4 pt
        scale = 14.4 / (sum(lens) / len(lens)) if lens else 0.379

        def pos(x, y):
            return f"{(x - x0) * scale:.2f} {(y1 - y) * scale:.2f}"

        def pt(x, y):
            return ((x - x0) * scale, (y1 - y) * scale)

        # 页面尺寸按内容自适应，至少留 72 pt 边距（ChemDraw 默认 540×720）
        px1, py1 = pt(x1, y0)
        page_w = max(540.0, px1 + 72.0)
        page_h = max(360.0, py1 + 72.0)

        rattrs = dict(CDXML_ROOT_ATTRS)
        rattrs["CreationProgram"] = "ELN 22"
        rattrs["Name"] = self.title or "ELN drawing"
        rattrs["BondLength"] = "14.4"
        rattrs["BoundingBox"] = "0 0 %.2f %.2f" % (page_w, page_h)
        root = ET.Element("CDXML", rattrs)
        # ---- 文档级颜色表与字体表：ChemDraw 解析 <t> 的 font/color 索引时
        #      要在这两张表里查，缺了会让 CDXMLParser 建不出文档（同一个断言）
        ct = ET.SubElement(root, "colortable")
        for r, g, b in ((1, 1, 1), (0, 0, 0), (1, 0, 0), (1, 1, 0),
                        (0, 1, 0), (0, 1, 1), (0, 0, 1), (1, 0, 1)):
            ET.SubElement(ct, "color", {"r": str(r), "g": str(g), "b": str(b)})
        ft = ET.SubElement(root, "fonttable")
        ET.SubElement(ft, "font", {"id": "3", "charset": "iso-8859-1",
                                   "name": "Arial"})
        page = ET.SubElement(root, "page", {
            "id": "1",
            "BoundingBox": "0 0 %.2f %.2f" % (page_w, page_h),
            # 这四项看着无关，但少了它们 ChemDraw 解析 <arrow> 时会建不出
            # 页面文档，直接抛 "document != nullptr" 断言（实测逐项排除过）
            "HeaderPosition": "36",
            "FooterPosition": "36",
            "PrintTrimMarks": "yes",
            "HeightPages": "1",
            "WidthPages": "1"})

        z = [1]

        def nz():
            z[0] += 1
            return str(z[0])

        # ---- 结构：按连通片段各建一个 <fragment>（ChemDraw 自己也是这么分的，
        #      反应式的反应物/产物要靠 fragment id 引用）
        groups = self.fragments()
        node_to_frag: dict[int, str] = {}
        frag_cx: dict[str, float] = {}
        for f_i, group in enumerate(groups):
            fid = str(20000 + f_i)
            frag = ET.SubElement(page, "fragment", {"id": fid})
            idmap: dict[int, str] = {}
            xs_f = []
            for aid in group:
                a = self.atom(aid)
                if not a:
                    continue
                node_to_frag[aid] = fid
                xs_f.append(a["x"])
                cid = str(10 + len(node_to_frag) - 1)
                idmap[aid] = cid
                attrs = {"id": cid, "p": pos(a["x"], a["y"]), "Z": nz(),
                         "Element": str(_atomic_number(a["e"]))}
                ch = int(a.get("charge") or 0)
                iso = int(a.get("isotope") or 0)
                if ch:
                    attrs["Charge"] = str(ch)
                if iso:
                    attrs["Isotope"] = str(iso)
                node = ET.SubElement(frag, "n", attrs)
                lab = (a.get("label") or "").strip()
                if lab:                       # OBz / CO2Et 之类的缩写基团
                    t = ET.SubElement(node, "t")
                    ET.SubElement(t, "s").text = lab
            frag_cx[fid] = (sum(xs_f) / len(xs_f)) if xs_f else 0.0
            for j, b in enumerate(self.bonds):
                if b["a"] in idmap and b["b"] in idmap:
                    ET.SubElement(frag, "b",
                                  {"id": str(100 + j), "Z": nz(),
                                   "B": idmap[b["a"]], "E": idmap[b["b"]],
                                   "Order": str(b.get("o") or 1)})

        # ---- 独立文字：page 级（ChemDraw 就是这么放的）
        label_ids: dict[int, str] = {}
        for k, l in enumerate(self.labels):
            text = str(l.get("text", ""))
            x, y = pt(l["x"], l["y"])
            tid = str(30000 + k)
            label_ids[id(l)] = tid
            # 粗估外框：中文按 12 pt/字，西文按 7 pt/字；仅作缓存提示
            width = 12.0 * sum(1.3 if ord(c) > 0x2E80 else 1.0 for c in text)
            bb = "%.2f %.2f %.2f %.2f" % (x, y, x + max(width, 12.0), y + 13.0)
            t = ET.SubElement(page, "t", {"id": tid, "p": "%.2f %.2f"
                                          % (x, y), "BoundingBox": bb,
                                          "Z": nz(), "LineHeight": "auto"})
            ET.SubElement(t, "s", {"font": "3", "size": "10", "color": "0"}
                          ).text = text

        # ---- 箭头：必须挂在 <scheme><step ReactionStepArrows="箭头id"> 下面，
        #      否则 ChemDraw 会为这条孤立箭头建不出对象（断言就出在这里）
        for m, r in enumerate(self.arrows):
            bx, by = pt(r["x1"], r["y1"])
            ex, ey = pt(r["x2"], r["y2"])
            cx, cy = (bx + ex) / 2.0, (by + ey) / 2.0
            mx, my = bx + 2 * (ex - bx), by + 2 * (ey - by)   # 主轴延长
            d = math.hypot(ex - bx, ey - by) or 1.0
            ux, uy = -(ey - by) / d, (ex - bx) / d            # 垂直单位向量

            aid = str(40000 + m)
            mid_x = (r["x1"] + r["x2"]) / 2.0
            left = [fid for fid, fx in frag_cx.items() if fx < mid_x]
            right = [fid for fid, fx in frag_cx.items() if fx >= mid_x]
            top_y = min(r["y1"], r["y2"]) - 8
            bot_y = max(r["y1"], r["y2"]) + 8
            above = [label_ids[id(l)] for l in self.labels
                     if l["y"] < top_y and r["x1"] - 80 <= l["x"] <= r["x2"] + 80]
            below = [label_ids[id(l)] for l in self.labels
                     if l["y"] > bot_y and r["x1"] - 80 <= l["x"] <= r["x2"] + 80]

            step_attrs = {"id": str(60000 + m), "ReactionStepArrows": aid}
            if left:
                step_attrs["ReactionStepReactants"] = " ".join(left)
            if right:
                step_attrs["ReactionStepProducts"] = " ".join(right)
            if above:
                step_attrs["ReactionStepObjectsAboveArrow"] = " ".join(above)
            if below:
                step_attrs["ReactionStepObjectsBelowArrow"] = " ".join(below)
            # 有结构才建 scheme：空的 <step>（没有反应物/产物）反而会让
            # ChemDraw 建不出对象；「只画了一根箭头」的图就不要 scheme
            if left or right:
                scheme = ET.SubElement(page, "scheme", {"id": str(50000 + m)})
                ET.SubElement(scheme, "step", step_attrs)

            ET.SubElement(page, "arrow", {
                "id": aid,
                "BoundingBox": "%.2f %.2f %.2f %.2f" % (min(bx, ex), min(by, ey),
                                                        max(bx, ex), max(by, ey)),
                "Z": nz(),
                "FillType": "None",
                "ArrowheadHead": "Full",
                "ArrowheadType": "Solid",
                "HeadSize": "1000",
                "ArrowheadCenterSize": "875",
                "ArrowheadWidth": "250",
                "Head3D": "%.2f %.2f 0" % (ex, ey),
                "Tail3D": "%.2f %.2f 0" % (bx, by),
                "Center3D": "%.2f %.2f 0" % (cx, cy),
                "MajorAxisEnd3D": "%.2f %.2f 0" % (mx, my),
                "MinorAxisEnd3D": "%.2f %.2f 0" % (cx + ux * d, cy + uy * d),
            })

        head = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE CDXML SYSTEM '
                '"https://static.chemistry.revvitycloud.com/cdxml/CDXML.dtd">\n')
        return head + ET.tostring(root, encoding="unicode"), ""

    # ------------------------------------------------------------ 载入
    def from_cdxml(self, data: dict, width=None, height=None, pad=46) -> bool:
        """把 CDXML 解析结果（原子 / 键 / 箭头 / 文字）按原布局放回画布。

        和 from_mol 的区别：这里**不重算二维坐标**，直接用文件里的位置，
        这样反应箭头和试剂文字才能和结构保持原来的相对位置。

        取景（两点都踩过坑）：
        - 画布尺寸要传真实像素值。以前写死 620×400，窗口一放大就整张缩成
          一小团，元素符号互相压住。
        - 包围盒以**结构**为准，离结构很远的东西（比如残留一根停在原点的
          箭头）不参与取景，否则它把高度撑到几百 pt，整张图被压扁。
          这类孤立对象也一并跳过，数量记在 ``self.skipped_objects``，
          由调用方提示用户。
        """
        atoms = data.get("atoms") or []
        bonds = data.get("bonds") or []
        arrows = data.get("arrows") or []
        labels = data.get("labels") or []
        self.skipped_objects = 0

        if width is None or height is None:
            width = 900 if width is None else width
            height = 620 if height is None else height

        aps = [a["p"] for a in atoms if a.get("p")]
        if aps:
            axs = [p[0] for p in aps]
            ays = [p[1] for p in aps]
            ax0, ax1, ay0, ay1 = min(axs), max(axs), min(ays), max(ays)
            # 结构外扩 0.75 倍长边：贴着的箭头 / 条件文字仍在范围内，
            # 跑飞的对象（残留在原点的箭头之类）直接跳过
            margin = 0.75 * max(ax1 - ax0, ay1 - ay0, 24.0)

            def near(p):
                return (ax0 - margin <= p[0] <= ax1 + margin
                        and ay0 - margin <= p[1] <= ay1 + margin)

            keep_arrows = []
            for r in arrows:
                if near((r["x1"], r["y1"])) or near((r["x2"], r["y2"])):
                    keep_arrows.append(r)
                else:
                    self.skipped_objects += 1
            keep_labels = []
            for l in labels:
                if near((l["x"], l["y"])):
                    keep_labels.append(l)
                else:
                    self.skipped_objects += 1
            arrows, labels = keep_arrows, keep_labels
            pts = list(aps)
            for r in arrows:
                pts.append((r["x1"], r["y1"]))
                pts.append((r["x2"], r["y2"]))
            for l in labels:
                pts.append((l["x"], l["y"]))
        else:
            # 只有箭头 / 文字的图（没有结构）：全部参与取景
            pts = [(r["x1"], r["y1"]) for r in arrows]
            pts += [(r["x2"], r["y2"]) for r in arrows]
            pts += [(l["x"], l["y"]) for l in labels]
        if not pts:
            return False

        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        w = max(x1 - x0, 1e-6)
        h = max(y1 - y0, 1e-6)
        # 画板里手画的苯环半径 46 px，对应 ChemDraw 的标准键长 14.4 pt，
        # 所以自然比例是 46/14.4 ≈ 3.19 px/pt；放不下才等比缩小
        natural = 46.0 / 14.4
        scale = min(natural, (width - 2 * pad) / w, (height - 2 * pad) / h)
        scale = max(scale, 1e-3)
        # 居中，而不是永远贴左上角
        ox = max(pad, (width - w * scale) / 2.0)
        oy = max(pad, (height - h * scale) / 2.0)

        def X(x):
            return ox + (x - x0) * scale

        def Y(y):
            return oy + (y1 - y) * scale         # CDXML 的 y 轴朝上，画布朝下

        self.atoms, self.bonds = [], []
        self.labels, self.arrows = [], []
        self._next, self._next_lid, self._next_aid = 1, 1, 1

        idmap = {}
        for a in atoms:
            p = a.get("p") or (x0, y0)
            nid = self.add_atom(a.get("sym") or "C", X(p[0]), Y(p[1]),
                                charge=int(a.get("chg") or 0),
                                isotope=int(a.get("iso") or 0))
            idmap[str(a.get("id"))] = nid
        for b in bonds:
            i = idmap.get(str(b.get("B")))
            j = idmap.get(str(b.get("E")))
            if i is None or j is None:
                continue
            try:
                order = int(round(float(b.get("order") or 1)))
            except (TypeError, ValueError):
                order = 1
            self.add_bond(i, j, max(1, min(3, order)))
        for l in labels:
            self.add_label(X(l["x"]), Y(l["y"]), l.get("text", ""))
        for r in arrows:
            self.add_arrow(X(r["x1"]), Y(r["y1"]), X(r["x2"]), Y(r["y2"]))
        return True

    def from_mol(self, mol, ox=140, oy=240, scale=38.0) -> bool:
        """把一个 RDKit Mol 的原子/键追加到图上（坐标平移到 ox, oy）。"""
        try:
            m = Chem.Mol(mol)
            Chem.Kekulize(m, clearAromaticFlags=True)   # 芳香键落成明确的单/双键
        except Exception:
            m = Chem.Mol(mol)
        try:
            AllChem.Compute2DCoords(m)
        except Exception:
            return False
        conf = m.GetConformer()
        start = self._next
        for i, atom in enumerate(m.GetAtoms()):
            p = conf.GetAtomPosition(i)
            self.add_atom(atom.GetSymbol(), ox + p.x * scale, oy - p.y * scale)
        for b in m.GetBonds():
            order = {Chem.BondType.SINGLE: 1, Chem.BondType.DOUBLE: 2,
                     Chem.BondType.TRIPLE: 3}.get(b.GetBondType(), 1)
            self.add_bond(start + b.GetBeginAtomIdx(), start + b.GetEndAtomIdx(), order)
        return True

    def from_smiles(self, smiles: str, ox=140, oy=240) -> bool:
        mol = Chem.MolFromSmiles(smiles or "")
        return self.from_mol(mol, ox, oy) if mol is not None else False

    def from_rxn(self, rxn) -> bool:
        """读回 .rxn：反应物排在左，产物排在右，中间补一根箭头。"""
        reactants, products = list(rxn.GetReactants()), list(rxn.GetProducts())
        self.atoms, self.bonds, self.labels, self.arrows = [], [], [], []
        self._next = 1
        self._next_lid = self._next_aid = 1
        self._next = 1
        self.mode = "scheme"
        x = 100
        for mol in reactants:
            self.from_mol(mol, x + 90, 250, 34.0)
            x += 190
        ax1 = x + 20
        x += 90
        for mol in products:
            self.from_mol(mol, x + 90, 250, 34.0)
            x += 190
        self.add_arrow(ax1, 250, ax1 + 70, 250)
        return True

    # ------------------------------------------------------------ 示例
    def new_reaction_canvas(self):
        """空白反应式画布：先摆一根居中的反应箭头，其他都留空。"""
        self.mode = "scheme"
        self.atoms, self.bonds, self.labels, self.arrows, self.roles = [], [], [], [], {}
        self._next = 1
        self.add_arrow(380.0, 250.0, 520.0, 250.0)

    def example_benzene(self):
        self.atoms, self.bonds, self.labels, self.arrows = [], [], [], []
        self._next, self.mode = 1, "structure"
        self.add_ring(300, 240, aromatic=True)
        self.add_label(248, 320, "苯环（点「生成 SMILES」看结果）")

    def example_reaction(self):
        self.atoms, self.bonds, self.labels, self.arrows = [], [], [], []
        self._next, self.mode = 1, "scheme"
        self.from_smiles("O=Cc1ccccc1", 150, 230)
        self.from_smiles("O=C(O)c1ccccc1", 520, 230)
        self.add_arrow(320, 230, 450, 230)
        self.add_label(340, 188, "KMnO4, H2O")
        self.add_label(340, 278, "室温 2 h, 88%")
        self.title = "苯甲醛氧化制苯甲酸"

    # ------------------------------------------------------------ 出图
    def bounds(self, pad: float = 40.0) -> tuple[float, float, float, float]:
        """内容包围盒（世界坐标），空图返回默认画布范围。"""
        xs, ys = [], []
        for a in self.atoms:
            xs.append(a["x"])
            ys.append(a["y"])
        for l in self.labels:
            xs.append(l["x"])
            ys.append(l["y"])
        for r in self.arrows:
            xs += [r["x1"], r["x2"]]
            ys += [r["y1"], r["y2"]]
        if not xs:
            return (0.0, 0.0, float(CANVAS_W), float(CANVAS_H))
        return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)

    def render_png(self, width: int = 720, height: int = 520,
                   grid: bool = False, show_h: bool = False) -> Image.Image:
        """按内容包围盒等比缩放重绘，返回 RGB 图（缩略图/导出共用）。"""
        x0, y0, x1, y1 = self.bounds(36.0)
        bw, bh = max(1.0, x1 - x0), max(1.0, y1 - y0)
        sc = min(width / bw, height / bh)
        ox = (width - bw * sc) / 2 - x0 * sc
        oy = (height - bh * sc) / 2 - y0 * sc
        im = Image.new("RGB", (width, height), "white")
        d = ImageDraw.Draw(im)
        P = lambda x, y: (x * sc + ox, y * sc + oy)

        if grid:
            step = GRID_STEP * 2
            gx = math.floor(x0 / step) * step
            while gx <= x1:
                px, _ = P(gx, 0)
                d.line((px, 0, px, height), fill=GRID, width=1)
                gx += step
            gy = math.floor(y0 / step) * step
            while gy <= y1:
                _, py = P(0, gy)
                d.line((0, py, width, py), fill=GRID, width=1)
                gy += step

        lw = max(1, int(round(2.0 * sc)))
        for b in self.bonds:
            p, q = self.atom(b["a"]), self.atom(b["b"])
            if not p or not q:
                continue
            x1s, y1s = P(p["x"], p["y"])
            x2s, y2s = P(q["x"], q["y"])
            dx, dy = x2s - x1s, y2s - y1s
            n = math.hypot(dx, dy) or 1
            nx, ny = -dy / n, dx / n
            off = 4.6 * sc
            order = int(b["o"])
            shifts = [0] if order == 1 else ([-off / 2, off / 2] if order == 2
                                             else [-off, 0, off])
            trim = 7 * sc
            for s in shifts:
                d.line((x1s + dx / n * trim + nx * s, y1s + dy / n * trim + ny * s,
                        x2s - dx / n * trim + nx * s, y2s - dy / n * trim + ny * s),
                       fill=BOND, width=lw)

        fnt = _font(max(11, int(15 * sc)))

        def text_size(t):
            bb = fnt.getbbox(t)
            return bb[2] - bb[0], bb[3] - bb[1]

        # 先给缩写基团铺白底，避免键穿过文字
        for a in self.atoms:
            t = self.atom_display(a)
            if not self.atom_shows_text(a):
                continue
            x, y = P(a["x"], a["y"])
            tw, th = text_size(t)
            d.rectangle((x - tw / 2 - 3 * sc, y - th / 2 - 3 * sc,
                         x + tw / 2 + 3 * sc, y + th / 2 + 3 * sc), fill="white")

        for a in self.atoms:
            x, y = P(a["x"], a["y"])
            t = self.atom_display(a)
            if not self.atom_shows_text(a):
                r = max(2, int(2.4 * sc))
                d.ellipse((x - r, y - r, x + r, y + r), fill="#9aa5b1")
            else:
                col = INK if self.is_abbrev(a) else ELEMENT_COLORS.get(a["e"], INK)
                d.text((x, y), t, font=fnt, fill=col, anchor="mm")

        if show_h:
            fnt_h = _font(max(10, int(13 * sc)))
            for h in self.hydrogen_overlays():
                x, y = P(h["x"], h["y"])
                px, py = P(h["px"], h["py"])
                dx, dy = x - px, y - py
                n = math.hypot(dx, dy) or 1
                d.line((px + dx / n * 7 * sc, py + dy / n * 7 * sc,
                        x - dx / n * 9 * sc, y - dy / n * 9 * sc),
                       fill="#b6c0cc", width=max(1, int(1.4 * sc)))
                d.text((x, y), "H", font=fnt_h,
                       fill=ELEMENT_COLORS["H"], anchor="mm")

        for l in self.labels:
            x, y = P(l["x"], l["y"])
            d.text((x, y), l["text"], font=fnt, fill=DIM, anchor="mm")

        for arr in self.arrows:
            x1s, y1s = P(arr["x1"], arr["y1"])
            x2s, y2s = P(arr["x2"], arr["y2"])
            d.line((x1s, y1s, x2s, y2s), fill=ACCENT, width=max(1, int(2.4 * sc)))
            ang = math.atan2(y2s - y1s, x2s - x1s)
            wing = 11 * sc
            d.polygon([(x2s, y2s),
                       (x2s - wing * math.cos(ang - 0.5), y2s - wing * math.sin(ang - 0.5)),
                       (x2s - wing * math.cos(ang + 0.5), y2s - wing * math.sin(ang + 0.5))],
                      fill=ACCENT)
        return im


# ---------------------------------------------------------------- 画板窗口

class DrawWindow:
    """绘制窗口。owner_type/owner_id 决定这张图挂在哪条记录下。"""

    def __init__(self, app_root, store, owner_type: str, owner_id: int | None,
                 drawing=None, on_saved=None, on_smiles=None, initial_smiles=""):
        self.store = store
        self.owner_type = owner_type
        self.owner_id = owner_id
        self.drawing = drawing
        self.on_saved = on_saved
        self.on_smiles = on_smiles
        self.tool = ""                 # 默认不选工具，点画布不会凭空加碳原子
        self.tool_buttons: dict = {}   # 工具名 -> (按钮, 原底色, 原字色)
        self.show_h = False            # 「显示 H」只改画布渲染，不写进图数据
        self.show_tips = tk.BooleanVar(value=False)   # 用法提示默认隐藏
        self.tip_items: list = []      # [(控件, pack 参数)]
        self._pending = None
        self._drag = None
        self._selected = None
        self._sel_box = None            # 选择框（世界坐标）
        self._sel_atoms: set[int] = set()
        self._sel_labels: set[int] = set()    # 选中的文字标注
        self._sel_arrows: set[int] = set()    # 选中的箭头
        self._sel_candidate = None      # 按下时命中的对象 (kind, id)，区分「点一下」和「拖框」
        self._just_added = None         # 上一次点击刚加的原子（双击时撤掉）
        self._undo: list[str] = []
        self._img = None
        self.zoom = 1.0                 # 缩放比例
        self.vx, self.vy = 0.0, 0.0     # 视口左上角对应的世界坐标
        self._pan = None                # 平移起点
        self._editor = None             # 原子文字编辑框
        self._box = None                # 框选删除的矩形（世界坐标）
        self._fnt_cache: dict[int, tkfont.Font] = {}

        if drawing is not None and drawing["data"]:
            self.sketch = Sketch.from_json(drawing["data"])
        else:
            self.sketch = Sketch(mode="scheme" if owner_type == "reaction"
                                 else "structure")
            if initial_smiles:
                self.sketch.from_smiles(initial_smiles, 200, 240)
            elif owner_type == "reaction":
                self.sketch.new_reaction_canvas()

        self.win = tk.Toplevel(app_root)
        self.win.title("绘制区 · " + ("结构式" if self.sketch.mode == "structure"
                                      else "反应式"))
        self.win.geometry("1320x820")
        self.win.minsize(920, 720)
        self.win.minsize(1080, 620)
        self.win.configure(bg="#f4f6f9")
        self.win.transient(app_root)
        self._build()
        self._refresh_preview()
        self.win.bind("<Escape>", lambda e: self.win.destroy())
        self.win.bind("<Control-z>", lambda e: self.undo())
        self.win.bind("<Delete>", lambda e: self.delete_selected())
        self.win.after(160, self._initial_view)

    def _initial_view(self):
        """打开时把已有内容摆到视口中间；空图或只有箭头时按 1:1。"""
        if self.sketch.atoms or self.sketch.labels:
            self.zoom_fit()
            return
        self.zoom = 1.0
        w = max(1, self.canvas.winfo_width())
        h = max(1, self.canvas.winfo_height())
        arr = self.sketch.main_arrow()
        if arr:
            self.vx = (arr["x1"] + arr["x2"]) / 2 - w / 2
            self.vy = (arr["y1"] + arr["y2"]) / 2 - h / 2
        else:
            self.vx = self.vy = 0.0
        self.redraw()

    # ------------------------------------------------------------ 布局
    def _build(self):
        top = tk.Frame(self.win, bg="#f4f6f9")
        top.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(top, text="绘制区", bg="#f4f6f9", fg=INK,
                 font=(UI, 13, "bold")).pack(side="left")
        self.mode_var = tk.StringVar(value=("反应式" if self.sketch.mode == "scheme"
                                            else "结构式"))
        ttk.Combobox(top, textvariable=self.mode_var, width=8, state="readonly",
                     values=["结构式", "反应式"], font=(UI, 9)).pack(side="left", padx=10)
        self.mode_var.trace_add("write", lambda *a: self.on_mode())
        tk.Label(top, text="标题", bg="#f4f6f9", fg=DIM,
                 font=(UI, 9)).pack(side="left", padx=(12, 4))
        self.title_var = tk.StringVar(value=self.sketch.title)
        tk.Entry(top, textvariable=self.title_var, width=34, font=(UI, 10),
                 bd=1, relief="solid").pack(side="left", ipady=3)

        tk.Button(top, text="载入示例", command=self.load_example, relief="flat",
                  bd=0, bg="#e8eef7", fg=ACCENT, font=(UI, 9), padx=10,
                  cursor="hand2").pack(side="right", padx=3)
        tk.Button(top, text="清空全部", command=self.clear, relief="flat", bd=0,
                  bg="#e8eef7", fg=ACCENT, font=(UI, 9), padx=10,
                  cursor="hand2").pack(side="right", padx=3)

        body = tk.Frame(self.win, bg="#f4f6f9")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # 左：工具
        tools = tk.Frame(body, bg="#ffffff", highlightthickness=1,
                         highlightbackground="#dde3ea", width=146)
        tools.pack(side="left", fill="y", padx=(0, 8))
        tools.pack_propagate(False)
        tk.Label(tools, text="工具", bg="#ffffff", fg=DIM,
                 font=(UI, 9, "bold")).pack(anchor="w", padx=8, pady=(5, 2))

        def tbtn(text, tool, col="#eef2f8"):
            b = tk.Button(tools, text=text, command=lambda: self.set_tool(tool),
                          relief="flat", bd=0, bg=col, fg=INK, font=(UI, 9),
                          width=15, pady=1, cursor="hand2")
            b.pack(padx=6, pady=1)
            self.tool_buttons[tool] = (b, col, INK)

        tbtn("选择 / 拖动", "select", "#e3ecfa")
        tip1 = tk.Label(tools, text="拖 = 框选 · Ctrl+拖 = 移动原子 · 点 = 选中",
                        bg="#ffffff", fg=DIM, font=(UI, 8),
                        justify="left", anchor="w")
        tip1.bind("<Configure>", lambda e, w=tip1: w.configure(
            wraplength=max(80, w.winfo_width() - 4)))
        self._register_tip(tip1, tools, anchor="w", padx=8, fill="x")
        tk.Label(tools, text="原子", bg="#ffffff", fg=DIM,
                 font=(UI, 8)).pack(anchor="w", padx=8, pady=(4, 0))
        for row in (ELEMENTS[:5], ELEMENTS[5:]):
            r = tk.Frame(tools, bg="#ffffff")
            r.pack(fill="x", padx=4, pady=(1, 0))
            for e in row:
                key = "atom:" + e
                b = tk.Button(r, text=e, width=3,
                              command=lambda x=e: self.set_tool("atom:" + x),
                              relief="flat", bd=0, bg="#f2f5f9", fg=INK,
                              font=(UI, 9), cursor="hand2", pady=0)
                b.pack(side="left", padx=1, pady=0)
                self.tool_buttons[key] = (b, "#f2f5f9", INK)
        tk.Label(tools, text="显示", bg="#ffffff", fg=DIM,
                 font=(UI, 8)).pack(anchor="w", padx=8, pady=(4, 0))
        self.btn_show_h = tk.Button(
            tools, text="显示 H", command=self.toggle_show_h,
            relief="flat", bd=0, bg="#f2f5f9", fg=INK, font=(UI, 9),
            width=15, pady=1, cursor="hand2")
        self.btn_show_h.pack(padx=6, pady=1)
        tbtn("缩写基团…", "abbrev", "#f1ecfb")
        tk.Label(tools, text="键 / 模板", bg="#ffffff", fg=DIM,
                 font=(UI, 8)).pack(anchor="w", padx=8, pady=(4, 0))
        for text, tool in (("单键 / 升级", "bond:1"), ("双键", "bond:2"),
                           ("三键", "bond:3"), ("苯环", "ring:arom"),
                           ("环己烷", "ring:sat")):
            tbtn(text, tool)
        tk.Label(tools, text="反应角色", bg="#ffffff", fg=DIM,
                 font=(UI, 8)).pack(anchor="w", padx=8, pady=(4, 0))
        for row in ((("反应物", ROLE_REACTANT), ("产物", ROLE_PRODUCT)),
                    (("催化剂", ROLE_CATALYST), ("溶剂", ROLE_SOLVENT))):
            r = tk.Frame(tools, bg="#ffffff")
            r.pack(fill="x", padx=4)
            for text, role in row:
                key = "role:" + role
                b = tk.Button(r, text=text, width=6,
                              command=lambda x=role: self.set_tool("role:" + x),
                              relief="flat", bd=0, bg=ROLE_COLORS[role], fg="white",
                              font=(UI, 9), cursor="hand2", pady=0)
                b.pack(side="left", padx=1, pady=0)
                self.tool_buttons[key] = (b, ROLE_COLORS[role], "white")
        r2 = tk.Frame(tools, bg="#ffffff")
        r2.pack(fill="x", padx=4)
        tk.Button(r2, text="清角色", width=6, command=self.clear_roles,
                  relief="flat", bd=0, bg="#f2f5f9", fg=INK, font=(UI, 9),
                  cursor="hand2").pack(side="left", padx=1, pady=1)
        tk.Button(r2, text="整理", width=6, command=self.do_layout,
                  relief="flat", bd=0, bg="#e8f4ec", fg=GREEN, font=(UI, 9),
                  cursor="hand2").pack(side="left", padx=1, pady=1)

        # 「标注」标题右边一个小 ? ，点开才显示双击改文字的举例。
        # 这行举例原来常驻，在窄工具栏里会被切掉，且大多数时候用不上。
        tk.Label(tools, text="标注", bg="#ffffff", fg=DIM,
                 font=(UI, 8)).pack(anchor="w", padx=8, pady=(4, 0))
        self.atom_hint = tk.Label(
            tools, text="双击原子可改文字：N+ / 13C / OBz / CO2Et",
            bg="#ffffff", fg=DIM, font=(UI, 8), justify="left", anchor="w")
        self.atom_hint.bind("<Configure>", lambda e, w=self.atom_hint: w.configure(
            wraplength=max(80, w.winfo_width() - 4)))
        self._register_tip(self.atom_hint, tools, anchor="w", padx=8, fill="x")
        for text, tool in (("文字", "label"), ("反应箭头", "arrow")):
            tbtn(text, tool, "#eef2f8")
        for text, tool in (("橡皮（点删）", "erase"), ("框选删除", "box")):
            tbtn(text, tool, "#fdeeee")

        # 中：画布
        mid = tk.Frame(body, bg="#ffffff", highlightthickness=1,
                       highlightbackground="#dde3ea")
        mid.pack(side="left", fill="both", expand=True)

        zbar = tk.Frame(mid, bg="#ffffff")
        zbar.pack(fill="x", padx=8, pady=(6, 0))
        tk.Label(zbar, text="缩放", bg="#ffffff", fg=DIM,
                 font=(UI, 8)).pack(side="left")
        tk.Button(zbar, text="−", width=2, command=lambda: self.zoom_step(1 / 1.25),
                  relief="flat", bd=0, bg="#f2f5f9", fg=INK, cursor="hand2",
                  font=(UI, 9)).pack(side="left", padx=(4, 1))
        self.zoom_lbl = tk.Label(zbar, text="100%", bg="#ffffff", fg=INK,
                                 font=(UI, 9), width=6)
        self.zoom_lbl.pack(side="left")
        tk.Button(zbar, text="+", width=2, command=lambda: self.zoom_step(1.25),
                  relief="flat", bd=0, bg="#f2f5f9", fg=INK, cursor="hand2",
                  font=(UI, 9)).pack(side="left", padx=(1, 6))
        tk.Button(zbar, text="1:1", command=self.zoom_reset, relief="flat", bd=0,
                  bg="#f2f5f9", fg=INK, font=(UI, 8), padx=6,
                  cursor="hand2").pack(side="left")
        tk.Button(zbar, text="适应窗口", command=self.zoom_fit, relief="flat",
                  bd=0, bg="#f2f5f9", fg=INK, font=(UI, 8), padx=6,
                  cursor="hand2").pack(side="left", padx=4)
        tk.Button(zbar, text="撤销 Ctrl+Z", command=self.undo, relief="flat",
                  bd=0, bg="#e8f4ec", fg=GREEN, font=(UI, 8), padx=6,
                  cursor="hand2").pack(side="left", padx=(8, 0))
        ztip = tk.Label(zbar, text="Ctrl+滚轮缩放 · 中键拖动平移", bg="#ffffff",
                        fg=DIM, font=(UI, 8))
        self._register_tip(ztip, zbar, side="right")

        self.canvas = tk.Canvas(mid, bg="white", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=6, pady=6)
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-2>", self.on_pan_start)
        self.canvas.bind("<B2-Motion>", self.on_pan_move)
        self.canvas.bind("<Button-3>", lambda e: self.cancel_pending())
        self.canvas.bind("<Double-Button-1>", self.on_double)
        self.canvas.bind("<MouseWheel>", self.on_wheel)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.hint = tk.Label(mid, text="", bg="#ffffff", fg=DIM,
                             font=(UI, 8), anchor="w")
        self.hint.pack(fill="x", padx=8, pady=(0, 4))

        # 右：属性
        side = tk.Frame(body, bg="#ffffff", highlightthickness=1,
                        highlightbackground="#dde3ea", width=300)
        side.pack(side="right", fill="y", padx=(8, 0))
        side.pack_propagate(False)

        def hint(parent, text, size=8):
            """编辑器说明：按面板宽度换行；默认收起，随「▸ 用法提示」展开。"""
            lab = tk.Label(parent, text=text, bg="#ffffff", fg=DIM,
                           font=(UI, size), justify="left", anchor="w")
            lab.bind("<Configure>", lambda e, w=lab: w.configure(
                wraplength=max(80, w.winfo_width() - 4)))
            self._register_tip(lab, parent, anchor="w", padx=10, fill="x")
            return lab

        # 生成结果（SMILES 框 + 绘制详情）按要求整块隐藏：
        # 控件仍然创建（代码里 _update_smiles_box / _refresh_detail 还要用），
        # 只是外层 res 容器不 pack，所以界面上不出现。
        res = tk.Frame(side, bg="#ffffff")
        tk.Label(res, text="生成结果", bg="#ffffff", fg=INK,
                 font=(UI, 10, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
        tk.Label(res, text="SMILES / 反应 SMILES", bg="#ffffff", fg=DIM,
                 font=(UI, 8)).pack(anchor="w", padx=10)
        # 3 行够看清一个 SMILES；再长就滚动，别把下面的按钮挤出去
        self.smi = tk.Text(res, height=3, wrap="char", bg="#f7f9fc", fg=INK,
                           font=(MONO, 9), bd=1, relief="solid", padx=6, pady=5)
        self.smi.pack(fill="x", padx=10, pady=(2, 4))

        # 绘制详情（角色 / 片段 / 试剂条件）默认收起，点一下才展开
        self.detail_bar = tk.Frame(res, bg="#ffffff")
        self.detail_bar.pack(anchor="w", fill="x", padx=10)
        self.detail_open = tk.BooleanVar(value=False)
        self.detail_btn = tk.Button(
            self.detail_bar, text="▸ 绘制详情", command=self._toggle_detail,
            relief="flat", bd=0, bg="#ffffff", fg="#7a8798",
            font=(UI, 8), cursor="hand2", anchor="w", padx=0)
        self.detail_btn.pack(anchor="w")
        self.props = tk.Label(res, text="", bg="#ffffff", fg=DIM,
                              font=(UI, 8), justify="left", anchor="w")
        self.props.pack(anchor="w", fill="x", padx=10)
        self.props.bind("<Configure>", lambda e, w=self.props: w.configure(
            wraplength=max(80, w.winfo_width() - 4)))
        self._detail_text = ""

        # Ketcher 入口已移到主窗口工具栏（电子效应之后），这里不再重复露出。
        tk.Label(side, text="ChemDraw 交换", bg="#ffffff", fg=INK,
                 font=(UI, 10, "bold")).pack(anchor="w", padx=10, pady=(14, 4))
        hint(side, "反应式导出 CDXML（含箭头与试剂文字）。改稿默认存回 edited 目录，"
                   "点「读回」取回结构。")
        tk.Button(side, text="用 ChemDraw 编辑（CDXML）", command=self.open_chemdraw,
                  relief="flat", bd=0, bg="#e8eef7", fg=ACCENT,
                  font=(UI, 9), cursor="hand2").pack(fill="x", padx=10, pady=(8, 2))
        tk.Button(side, text="用 ChemDraw 编辑（RXN 兼容）",
                  command=self.open_chemdraw_rxn,
                  relief="flat", bd=0, bg="#f2f5f9", fg=INK,
                  font=(UI, 9), cursor="hand2").pack(fill="x", padx=10, pady=2)
        tk.Button(side, text="读回 ChemDraw 文件", command=self.read_chemdraw,
                  relief="flat", bd=0, bg="#e8f4ec", fg=GREEN,
                  font=(UI, 9), cursor="hand2").pack(fill="x", padx=10, pady=2)
        tk.Button(side, text="打开交换文件夹", command=self.open_exchange_folder,
                  relief="flat", bd=0, bg="#f2f5f9", fg=DIM,
                  font=(UI, 8), cursor="hand2").pack(fill="x", padx=10, pady=2)
        tk.Button(side, text="载入 SMILES", command=self.load_smiles,
                  relief="flat", bd=0, bg="#f2f5f9", fg=INK,
                  font=(UI, 9), cursor="hand2").pack(fill="x", padx=10, pady=(8, 2))
        tk.Button(side, text="导出 PNG", command=self.export_png, relief="flat",
                  bd=0, bg="#f2f5f9", fg=INK, font=(UI, 9),
                  cursor="hand2").pack(fill="x", padx=10, pady=2)

        # 底栏
        bottom = tk.Frame(self.win, bg="#f4f6f9")
        bottom.pack(fill="x", padx=12, pady=(0, 10))
        self.tip_btn = tk.Button(bottom, text="▸ 用法提示", command=self._toggle_tips,
                                 relief="flat", bd=0, bg="#eef1f5", fg="#7a8798",
                                 font=(UI, 8), cursor="hand2", padx=6)
        self.tip_btn.pack(side="left")
        tip3 = tk.Label(bottom,
                        text="左键操作 · 双击原子改文字/电荷 · 拖=框选 Ctrl+拖=移动 · "
                             "「整理」按角色摆位 · Ctrl+滚轮缩放 · Ctrl+Z 撤销",
                        bg="#f4f6f9", fg=DIM, font=(UI, 8),
                        justify="left", anchor="w")
        self._register_tip(tip3, bottom, side="left", padx=(8, 0))
        tk.Button(bottom, text="取消", command=self.win.destroy, relief="flat",
                  bd=0, bg="#eef1f5", fg=INK, font=(UI, 10), padx=16,
                  pady=6, cursor="hand2").pack(side="right", padx=(6, 0))
        save_text = "应用到表单" if self.owner_id is None else "保存到记录"
        tk.Button(bottom, text=save_text, command=self.save, relief="flat",
                  bd=0, bg=ACCENT, fg="white", font=(UI, 10, "bold"),
                  padx=20, pady=6, cursor="hand2").pack(side="right")
        self._finalize_tips()
        self.redraw()

    # ------------------------------------------------------------ 视图
    def w2s(self, x, y):
        """世界坐标 -> 屏幕坐标"""
        return ((x - self.vx) * self.zoom, (y - self.vy) * self.zoom)

    def s2w(self, x, y):
        """屏幕坐标 -> 世界坐标"""
        return (x / self.zoom + self.vx, y / self.zoom + self.vy)

    def zoom_step(self, factor, cx=None, cy=None):
        old = self.zoom
        new = max(0.15, min(8.0, old * factor))
        if abs(new - old) < 1e-6:
            return
        if cx is None:
            cx = max(1, self.canvas.winfo_width()) / 2
            cy = max(1, self.canvas.winfo_height()) / 2
        wx, wy = self.s2w(cx, cy)
        self.zoom = new
        # 让缩放锚点在屏幕上保持不动
        self.vx = wx - cx / new
        self.vy = wy - cy / new
        self.redraw()

    def zoom_reset(self):
        self.zoom = 1.0
        self.redraw()

    def zoom_fit(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1 or h <= 1:            # 窗口还没布局完，等一帧再来
            self.win.after(120, self.zoom_fit)
            return
        x0, y0, x1, y1 = self.sketch.bounds(40)
        bw, bh = max(1.0, x1 - x0), max(1.0, y1 - y0)
        # 只有箭头时别把一根线放大到满屏
        cap = 4.0 if (self.sketch.atoms or self.sketch.labels) else 1.2
        self.zoom = max(0.15, min(cap, min(w / bw, h / bh) * 0.92))
        self.vx = (x0 + x1) / 2 - w / (2 * self.zoom)
        self.vy = (y0 + y1) / 2 - h / (2 * self.zoom)
        self.redraw()

    def on_pan_start(self, event):
        self._pan = (event.x, event.y, self.vx, self.vy)
        self.canvas.configure(cursor="fleur")

    def on_pan_move(self, event):
        if not self._pan:
            return
        sx, sy, vx0, vy0 = self._pan
        self.vx = vx0 - (event.x - sx) / self.zoom
        self.vy = vy0 - (event.y - sy) / self.zoom
        self.redraw()

    def on_release(self, event):
        if self.tool == "box" and self._box:
            box = self._box
            self._box = None
            self.erase_box(box)
            return
        if self._is_select() and self._sel_box:
            self._finish_sel_box()
            return
        self._drag = None
        if self._pan:
            self._pan = None
            self.canvas.configure(cursor="")

    def _finish_sel_box(self):
        """松开鼠标：把框内的原子设为选中，之后可整体拖动。"""
        x0, y0, x1, y1 = self._sel_box
        self._sel_box = None
        self._drag = None
        xa, xb = (x0, x1) if x0 <= x1 else (x1, x0)
        ya, yb = (y0, y1) if y0 <= y1 else (y1, y0)
        if (xb - xa) < 4 and (yb - ya) < 4:
            # 只是点了一下：点中对象 = 选中它（按下时已记下），点空白 = 取消选择
            if self._sel_candidate is None:
                self._sel_atoms.clear()
                self._sel_labels.clear()
                self._sel_arrows.clear()
                self._selected = None
        else:
            self._sel_atoms = {a["id"] for a in self.sketch.atoms
                               if xa <= a["x"] <= xb and ya <= a["y"] <= yb}
            self._sel_labels = {l.get("id") for l in self.sketch.labels
                                if xa <= l["x"] <= xb and ya <= l["y"] <= yb}
            self._sel_arrows = {arr.get("id") for arr in self.sketch.arrows
                                if self._arrow_in_box(arr, xa, ya, xb, yb)}
            self._selected = (next(iter(self._sel_atoms))
                              if len(self._sel_atoms) == 1 else None)
        self._sel_candidate = None
        self.redraw()

    @staticmethod
    def _arrow_in_box(arr, xa, ya, xb, yb) -> bool:
        """箭头的端点或中点落在框内就算选中。"""
        pts = [(arr["x1"], arr["y1"]), (arr["x2"], arr["y2"]),
               ((arr["x1"] + arr["x2"]) / 2, (arr["y1"] + arr["y2"]) / 2)]
        return any(xa <= px <= xb and ya <= py <= yb for px, py in pts)

    def on_wheel(self, event):
        step = 80
        if event.state & 0x0004:            # Ctrl：缩放
            self.zoom_step(1.15 if event.delta > 0 else 1 / 1.15,
                           event.x, event.y)
        elif event.state & 0x0001:          # Shift：横向平移
            self.vx -= (step if event.delta > 0 else -step) / self.zoom
            self.redraw()
        else:                               # 纵向平移
            self.vy -= (step if event.delta > 0 else -step) / self.zoom
            self.redraw()

    # ------------------------------------------------------------ 双击改文字
    def on_double(self, event):
        if self._just_added is not None:
            # 双击时 tkinter 会先发一次 Button-1，元素工具下会多加一个原子，撤掉
            self.sketch.remove_atom(self._just_added)
            if self._undo:
                self._undo.pop()
            self._just_added = None
        wx, wy = self.s2w(event.x, event.y)
        a = self.sketch.nearest_atom(wx, wy, 26 / self.zoom)
        if a is not None:
            self.edit_atom(a)
            return
        for l in self.sketch.labels:          # 双击文字标注 = 改内容
            if self.sketch.label_hit(l, wx, wy, 48 / self.zoom):
                self.edit_label(l)
                return

    def edit_label(self, l):
        """双击文字标注：就地改内容。"""
        self._close_editor()
        x, y = self.w2s(l["x"], l["y"])
        var = tk.StringVar(value=l["text"])
        ent = tk.Entry(self.canvas, textvariable=var, font=(UI, 11),
                       justify="center", bd=1, relief="solid",
                       bg="#fffdf0", fg=INK)
        ent.place(x=x - 90, y=y - 13, width=180, height=26)
        ent.focus_set()
        ent.select_range(0, "end")

        def commit(_=None):
            if not self._editor:
                return "break"
            text = var.get()
            self._close_editor()
            if text.strip():
                self._push_undo()
                l["text"] = text.strip()
                self.redraw()
                self._refresh_preview()
            return "break"

        def cancel(_=None):
            self._close_editor()
            return "break"

        ent.bind("<Return>", commit)
        ent.bind("<Escape>", cancel)
        ent.bind("<FocusOut>", commit)
        self._editor = (ent, commit, cancel)

    def edit_atom(self, a):
        """在原子位置弹出输入框，像 ChemDraw 那样直接改原子/基团文字。"""
        self._close_editor()
        x, y = self.w2s(a["x"], a["y"])
        cur = self.sketch.atom_display(a) or a["e"]
        var = tk.StringVar(value=cur)
        ent = tk.Entry(self.canvas, textvariable=var, font=(UI, 11),
                       justify="center", bd=1, relief="solid",
                       bg="#fffdf0", fg=INK)
        ent.place(x=x - 62, y=y - 13, width=124, height=26)
        ent.focus_set()
        ent.select_range(0, "end")

        def commit(_=None):
            if not self._editor:
                return "break"
            text = var.get()
            self._close_editor()
            self.apply_atom_text(a, text)
            return "break"

        def cancel(_=None):
            self._close_editor()
            return "break"

        ent.bind("<Return>", commit)
        ent.bind("<Escape>", cancel)
        ent.bind("<FocusOut>", commit)
        self._editor = (ent, commit, cancel)

    def _close_editor(self):
        if not self._editor:
            return
        ent = self._editor[0]
        self._editor = None
        try:
            ent.destroy()
        except Exception:
            pass

    def apply_atom_text(self, a, text: str):
        """把输入框里的写法落到原子上：元素 / 缩写 / 电荷 / 同位素。"""
        self._push_undo()
        e, lab, charge, iso = parse_atom_attrs(text)
        a["e"] = e
        if lab:
            a["label"] = lab
        else:
            a.pop("label", None)
        if charge:
            a["charge"] = charge
        else:
            a.pop("charge", None)
        if iso:
            a["isotope"] = iso
        else:
            a.pop("isotope", None)
        self.redraw()
        self._refresh_preview()

    # ------------------------------------------------------------ 工具
    def _is_select(self) -> bool:
        """未选工具（""）和「选择 / 拖动」行为一致：只选中，不新建。"""
        return self.tool in ("", "select")

    def set_tool(self, tool):
        if tool == "undo":
            self.undo()
            return
        self.tool = tool
        self._pending = None
        self._sync_tool_buttons()
        self.redraw()

    def _sync_tool_buttons(self):
        """高亮当前工具；未选工具时所有按钮都是原色。"""
        for key, (btn, bg, fg) in self.tool_buttons.items():
            on = bool(self.tool) and key == self.tool
            btn.configure(bg=TOOL_ACTIVE_BG if on else bg,
                          fg="#ffffff" if on else fg)

    def _push_undo(self):
        self._undo.append(self.sketch.to_json())
        if len(self._undo) > 40:
            self._undo.pop(0)

    def undo(self):
        if not self._undo:
            return
        self.sketch = Sketch.from_json(self._undo.pop())
        self._pending = self._selected = None
        self._sel_atoms.clear()
        self._sel_labels.clear()
        self._sel_arrows.clear()
        self._sel_box = None
        self.redraw()
        self._refresh_preview()

    def on_mode(self):
        self.sketch.mode = "scheme" if self.mode_var.get() == "反应式" else "structure"
        self._refresh_preview()

    def clear(self):
        """一键清除：清掉全部原子、键、文字、箭头与角色标记（可 Ctrl+Z 撤销）。"""
        if not (self.sketch.atoms or self.sketch.labels or self.sketch.arrows):
            return
        self._push_undo()
        self.sketch.clear_all()
        self._selected = self._pending = None
        self._sel_atoms.clear()
        self._sel_labels.clear()
        self._sel_arrows.clear()
        self._sel_box = None
        self.redraw()
        self._refresh_preview()

    def load_example(self):
        self._push_undo()
        if self.sketch.mode == "scheme":
            self.sketch.example_reaction()
            self.title_var.set(self.sketch.title)
        else:
            self.sketch.example_benzene()
        self.redraw()
        self._refresh_preview()

    def load_smiles(self):
        text = simpledialog.askstring("载入结构", "粘贴 SMILES：", parent=self.win)
        if not text:
            return
        self._push_undo()
        if not self.sketch.from_smiles(text.strip(), 200, 240):
            messagebox.showwarning("解析不了", "这个 SMILES 读不进来。", parent=self.win)
            self._undo.pop()
            return
        self.redraw()
        self._refresh_preview()

    def cancel_pending(self):
        self._pending = None
        self._box = None
        self._sel_box = None
        self.tool = ""
        self._sync_tool_buttons()
        self._selected = None
        self._sel_atoms.clear()
        self._sel_labels.clear()
        self._sel_arrows.clear()
        self.redraw()

    def clear_roles(self):
        if not self.sketch.roles:
            messagebox.showinfo("还没有角色", "先用左栏的「反应物 / 产物 / 催化剂 / 溶剂」"
                                            "按钮给片段打标记。", parent=self.win)
            return
        self._push_undo()
        self.sketch.roles.clear()
        self.redraw()
        self._refresh_preview()

    def do_layout(self):
        if not self.sketch.atoms:
            messagebox.showinfo("画布是空的", "先画点东西再整理。", parent=self.win)
            return
        self._push_undo()
        n = self.sketch.layout_reaction()
        if not n:
            self._undo.pop()
            messagebox.showinfo("没有可整理的片段", "画布上没有分子片段。", parent=self.win)
            return
        if self.sketch.mode == "scheme":
            self.mode_var.set("反应式")
        self.zoom_fit()
        self.redraw()
        self._refresh_preview()

    def delete_selected(self):
        ids = set(self._sel_atoms)
        if self._selected is not None:
            ids.add(self._selected)
        ids = {i for i in ids if self.sketch.atom(i)}
        lids = {i for i in self._sel_labels if self.sketch.label_by_id(i)}
        aids = {i for i in self._sel_arrows if self.sketch.arrow_by_id(i)}
        if not (ids or lids or aids):
            return
        self._push_undo()
        for aid in ids:
            self.sketch.remove_atom(aid)
        if lids:
            self.sketch.labels = [l for l in self.sketch.labels
                                  if l.get("id") not in lids]
        if aids:
            self.sketch.arrows = [a for a in self.sketch.arrows
                                  if a.get("id") not in aids]
        self._selected = None
        self._sel_atoms.clear()
        self._sel_labels.clear()
        self._sel_arrows.clear()
        self.redraw()
        self._refresh_preview()

    def erase_box(self, box):
        """删除矩形范围内的原子（连带其键）、文字和箭头。"""
        x0, y0, x1, y1 = box
        if abs(x1 - x0) < 3 and abs(y1 - y0) < 3:   # 只是点了一下，不算框选
            if self._undo:
                self._undo.pop()
            self.redraw()
            return
        if not self.sketch.erase_rect(x0, y0, x1, y1):
            self.redraw()
            return
        alive = {a["id"] for a in self.sketch.atoms}
        self._sel_atoms &= alive
        if self._selected is not None and self._selected not in alive:
            self._selected = None
        self.redraw()
        self._refresh_preview()

    # ------------------------------------------------------------ 画布事件
    def _hit_object(self, x, y, near_r):
        """命中测试：返回 ('atom'|'label'|'arrow', id)，都没命中返回 None。"""
        a = self.sketch.nearest_atom(x, y, near_r)
        if a is not None:
            return ("atom", a["id"])
        lr = 48 / self.zoom
        for l in self.sketch.labels:
            if self.sketch.label_hit(l, x, y, lr):
                return ("label", l.get("id"))
        ar = 20 / self.zoom
        for arr in self.sketch.arrows:
            if self.sketch.arrow_hit(arr, x, y, ar):
                return ("arrow", arr.get("id"))
        return None

    def _select_only(self, hit):
        """点选一个对象：已经在选中集合里就保留整组，否则只选它。"""
        kind, oid = hit
        cur = {"atom": self._sel_atoms, "label": self._sel_labels,
               "arrow": self._sel_arrows}[kind]
        if oid not in cur:
            self._sel_atoms.clear()
            self._sel_labels.clear()
            self._sel_arrows.clear()
            cur.add(oid)
        self._selected = oid if kind == "atom" else None

    def _selected_snapshot(self):
        """记下当前选中的所有对象坐标，拖动时整体平移。"""
        snap = {"atoms": {}, "labels": {}, "arrows": {}}
        for i in self._sel_atoms:
            a = self.sketch.atom(i)
            if a:
                snap["atoms"][i] = (a["x"], a["y"])
        for i in self._sel_labels:
            l = self.sketch.label_by_id(i)
            if l:
                snap["labels"][i] = (l["x"], l["y"])
        for i in self._sel_arrows:
            arr = self.sketch.arrow_by_id(i)
            if arr:
                snap["arrows"][i] = (arr["x1"], arr["y1"], arr["x2"], arr["y2"])
        return snap

    def on_click(self, event):
        x, y = self.s2w(event.x, event.y)
        t = self.tool
        near_r = 22 / self.zoom
        ctrl = bool(event.state & 0x0004)      # 按住 Ctrl 时拖 = 移动原子
        self._just_added = None

        if t == "select" or not t:
            hit = self._hit_object(x, y, near_r)
            self._drag = None
            self._sel_candidate = None
            if hit is not None and ctrl:
                # Ctrl + 拖 = 移动对象（原来的手势保留在 Ctrl 上）
                self._select_only(hit)
                self._drag = {"start": (x, y), "objects": self._selected_snapshot()}
            else:
                # 默认手势：拖 = 框选（从对象身上起手也行）；点一下 = 选中它
                self._sel_box = (x, y, x, y)
                if hit is not None:
                    self._sel_candidate = hit
                    self._select_only(hit)
                else:
                    self._sel_atoms.clear()
                    self._sel_labels.clear()
                    self._sel_arrows.clear()
                    self._selected = None
        elif t.startswith("atom:"):
            near = self.sketch.nearest_atom(x, y, near_r)
            if near is None:
                gx = round(x / GRID_STEP) * GRID_STEP
                gy = round(y / GRID_STEP) * GRID_STEP
                e = t.split(":", 1)[1]
                self._push_undo()
                self._just_added = self.sketch.add_atom(e, gx, gy)
        elif t == "abbrev":
            text = simpledialog.askstring(
                "缩写基团", "输入基团文字（如 OBz、CH2OBz、Ph、TBS）：",
                parent=self.win)
            if text and text.strip():
                e, lab, ch, iso = parse_atom_attrs(text)
                gx = round(x / GRID_STEP) * GRID_STEP
                gy = round(y / GRID_STEP) * GRID_STEP
                self._push_undo()
                self._just_added = self.sketch.add_atom(e, gx, gy, lab, ch, iso)
        elif t == "box":
            self._push_undo()
            self._box = (x, y, x, y)      # 起点，拖拽时更新终点
        elif t.startswith("role:"):
            a = self.sketch.nearest_atom(x, y, near_r)
            if a is None:
                return
            ids = self.sketch.fragment_at(a["id"])
            role = t.split(":", 1)[1]
            self._push_undo()
            # 点已有同样角色的片段表示取消
            self.sketch.set_role(
                ids, "" if self.sketch.fragment_role(ids) == role else role)
            self.sketch.mode = "scheme"
            self.mode_var.set("反应式")
        elif t.startswith("bond:"):
            a = self.sketch.nearest_atom(x, y, near_r)
            if a is None:
                return
            if self._pending is None:
                self._pending = a["id"]
            else:
                self._push_undo()
                self.sketch.add_bond(self._pending, a["id"],
                                     int(t.split(":", 1)[1]))
                self._pending = None
        elif t.startswith("ring:"):
            self._push_undo()
            self.sketch.add_ring(round(x / GRID_STEP) * GRID_STEP,
                                 round(y / GRID_STEP) * GRID_STEP,
                                 aromatic=(t == "ring:arom"))
        elif t == "label":
            text = simpledialog.askstring("文字标注", "写点什么（试剂 / 条件 / 产率）：",
                                          parent=self.win)
            if text and text.strip():
                self._push_undo()
                self.sketch.add_label(x, y, text.strip())
        elif t == "arrow":
            if self._pending is None:
                self._pending = (x, y)
            else:
                x1, y1 = self._pending
                self._push_undo()
                self.sketch.add_arrow(x1, y1, x, y)
                self._pending = None
                self.sketch.mode = "scheme"
                self.mode_var.set("反应式")
        elif t == "erase":
            a = self.sketch.nearest_atom(x, y, near_r)
            if a:
                self._push_undo()
                self.sketch.remove_atom(a["id"])
            else:
                b = self.sketch.nearest_bond(x, y)
                if b:
                    self.sketch.bonds.remove(b)
                else:
                    self.sketch.labels = [l for l in self.sketch.labels
                                          if math.hypot(l["x"] - x, l["y"] - y) > 22]
                    self.sketch.arrows = [r for r in self.sketch.arrows
                                          if math.hypot((r["x1"] + r["x2"]) / 2 - x,
                                                        (r["y1"] + r["y2"]) / 2 - y) > 45]
        self.redraw()
        self._refresh_preview()

    def on_drag(self, event):
        if self.tool == "box" and self._box:
            x0, y0 = self._box[0], self._box[1]
            wx, wy = self.s2w(event.x, event.y)
            self._box = (x0, y0, wx, wy)
            self.redraw()
            return
        if self._is_select():
            wx, wy = self.s2w(event.x, event.y)
            if self._drag:                 # Ctrl + 拖 = 移动对象
                dx = wx - self._drag["start"][0]
                dy = wy - self._drag["start"][1]
                # 位移整体吸附到网格，保持选中对象之间的相对位置
                gx = round(dx / GRID_STEP) * GRID_STEP
                gy = round(dy / GRID_STEP) * GRID_STEP
                objs = self._drag["objects"]
                for aid, (ox, oy) in objs["atoms"].items():
                    a = self.sketch.atom(aid)
                    if a:
                        a["x"] = ox + gx
                        a["y"] = oy + gy
                for lid, (ox, oy) in objs["labels"].items():
                    l = self.sketch.label_by_id(lid)
                    if l:
                        l["x"] = ox + gx
                        l["y"] = oy + gy
                for aid, (x1, y1, x2, y2) in objs["arrows"].items():
                    arr = self.sketch.arrow_by_id(aid)
                    if arr:
                        arr["x1"], arr["y1"] = x1 + gx, y1 + gy
                        arr["x2"], arr["y2"] = x2 + gx, y2 + gy
                self.redraw()
                return
            if self._sel_box:              # 拖 = 框选
                self._sel_box = (self._sel_box[0], self._sel_box[1], wx, wy)
                self.redraw()
            return

    # ------------------------------------------------------------ 绘制
    def toggle_show_h(self):
        """切换「显示 H」：只改画布渲染，不动 sketch 数据与数据库。

        关闭时回到骨架式；开启时按 RDKit 价态补画隐式氢，可随时切回。
        """
        self.show_h = not self.show_h
        self.btn_show_h.configure(
            text="隐藏 H" if self.show_h else "显示 H",
            bg="#e3f3ea" if self.show_h else "#f2f5f9",
            fg=GREEN if self.show_h else INK)
        self.redraw()

    def _fnt(self, size: int) -> tkfont.Font:
        f = self._fnt_cache.get(size)
        if f is None:
            f = tkfont.Font(family=UI, size=size, weight="bold")
            self._fnt_cache[size] = f
        return f

    def redraw(self):
        c = self.canvas
        c.delete("all")
        vw = max(1, c.winfo_width())
        vh = max(1, c.winfo_height())
        z = self.zoom

        # 网格：间距随缩放自适应，始终铺满视口（视口可平移到任意位置，即无限画布）
        step = GRID_STEP * 2.0
        while step * z < 16:
            step *= 2
        while step * z > 140:
            step /= 2
        wx0, wy0 = self.s2w(0, 0)
        wx1, wy1 = self.s2w(vw, vh)
        gx = math.floor(wx0 / step) * step
        while gx <= wx1:
            sx = (gx - self.vx) * z
            c.create_line(sx, 0, sx, vh, fill=GRID)
            gx += step
        gy = math.floor(wy0 / step) * step
        while gy <= wy1:
            sy = (gy - self.vy) * z
            c.create_line(0, sy, vw, sy, fill=GRID)
            gy += step

        def S(x, y):
            return ((x - self.vx) * z, (y - self.vy) * z)

        # 键
        lw = max(1, int(round(2 * z)))
        trim = 9 * z
        for b in self.sketch.bonds:
            p, q = self.sketch.atom(b["a"]), self.sketch.atom(b["b"])
            if not p or not q:
                continue
            x1, y1 = S(p["x"], p["y"])
            x2, y2 = S(q["x"], q["y"])
            dx, dy = x2 - x1, y2 - y1
            n = math.hypot(dx, dy) or 1
            nx, ny = -dy / n, dx / n
            off = 5 * z
            order = int(b["o"])
            shifts = [0] if order == 1 else (
                [-off / 2, off / 2] if order == 2 else [-off, 0, off])
            for s in shifts:
                c.create_line(x1 + dx / n * trim + nx * s,
                              y1 + dy / n * trim + ny * s,
                              x2 - dx / n * trim + nx * s,
                              y2 - dy / n * trim + ny * s,
                              fill=BOND, width=lw)

        # 原子文字
        fs = max(7, int(round(12 * z)))
        fnt = self._fnt(fs)
        # 先铺白底，键就不会穿过缩写文字
        for a in self.sketch.atoms:
            t = self.sketch.atom_display(a)
            if not self.sketch.atom_shows_text(a):
                continue
            x, y = S(a["x"], a["y"])
            tw, th = fnt.measure(t), fnt.metrics("linespace")
            c.create_rectangle(x - tw / 2 - 2, y - th / 2,
                               x + tw / 2 + 2, y + th / 2,
                               fill="white", outline="")
        for a in self.sketch.atoms:
            x, y = S(a["x"], a["y"])
            t = self.sketch.atom_display(a)
            if not self.sketch.atom_shows_text(a):
                r = max(2, 3 * z)
                c.create_oval(x - r, y - r, x + r, y + r,
                              fill="#9aa5b1", outline="")
            else:
                col = INK if self.sketch.is_abbrev(a) else ELEMENT_COLORS.get(a["e"], INK)
                c.create_text(x, y, text=t, font=(UI, fs, "bold"), fill=col)

        if self.show_h:
            fs_h = max(7, int(round(11 * z)))
            for h in self.sketch.hydrogen_overlays():
                x, y = S(h["x"], h["y"])
                px, py = S(h["px"], h["py"])
                dx, dy = x - px, y - py
                n = math.hypot(dx, dy) or 1
                c.create_line(px + dx / n * 7 * z, py + dy / n * 7 * z,
                              x - dx / n * 9 * z, y - dy / n * 9 * z,
                              fill="#b6c0cc", width=max(1, int(round(1.4 * z))))
                c.create_rectangle(x - 8 * z, y - 7 * z, x + 8 * z, y + 7 * z,
                                   fill="white", outline="")
                c.create_text(x, y, text="H", font=(UI, fs_h, "bold"),
                              fill=ELEMENT_COLORS["H"])

        for l in self.sketch.labels:
            x, y = S(l["x"], l["y"])
            picked = l.get("id") in self._sel_labels
            c.create_text(x, y, text=l["text"],
                          font=(UI, max(7, int(round(10 * z)))),
                          fill=ACCENT if picked else DIM)
            if picked:                       # 选中的文字描一圈蓝框
                lf = self._fnt(max(7, int(round(10 * z))))
                tw, th = lf.measure(l["text"]), lf.metrics("linespace")
                c.create_rectangle(x - tw / 2 - 3, y - th / 2,
                                   x + tw / 2 + 3, y + th / 2,
                                   outline=ACCENT, dash=(3, 2), width=1)

        for arr in self.sketch.arrows:
            x1, y1 = S(arr["x1"], arr["y1"])
            x2, y2 = S(arr["x2"], arr["y2"])
            picked = arr.get("id") in self._sel_arrows
            c.create_line(x1, y1, x2, y2, fill=ACCENT,
                          width=max(1, int(round((4 if picked else 3) * z))),
                          arrow=tk.LAST, arrowshape=(12 * z, 14 * z, 5 * z))
            if picked:                       # 选中的箭头加一个虚线框
                c.create_rectangle(min(x1, x2) - 4, min(y1, y2) - 4,
                                   max(x1, x2) + 4, max(y1, y2) + 4,
                                   outline=ACCENT, dash=(3, 2), width=1)

        # 角色标记（虚线框 + 角标）
        if self.sketch.roles:
            groups = self.sketch.reaction_groups()
            for role in ROLE_ORDER:
                for ids in groups.get(role, []):
                    bb = self.sketch._frag_bbox(ids)
                    if not bb:
                        continue
                    pad = 12
                    x1, y1 = S(bb[0] - pad, bb[1] - pad)
                    x2, y2 = S(bb[2] + pad, bb[3] + pad)
                    x2 = max(x2, x1 + 26 * z)
                    y2 = max(y2, y1 + 26 * z)
                    c.create_rectangle(x1, y1, x2, y2, outline=ROLE_COLORS[role],
                                       dash=(4, 3), width=1)
                    c.create_text(x1 + 2, y1 - 2, text=ROLE_BADGES[role],
                                  anchor="sw", fill=ROLE_COLORS[role],
                                  font=(UI, max(7, int(9 * z))))

        # 选中 / 待连接标记
        sel = set(self._sel_atoms)
        if self._selected is not None:
            sel.add(self._selected)
        sel = {i for i in sel if self.sketch.atom(i)}
        for aid in sel:
            a = self.sketch.atom(aid)
            x, y = S(a["x"], a["y"])
            r = max(5, 11 * z)
            c.create_oval(x - r, y - r, x + r, y + r, outline=ACCENT, width=2)
        if len(sel) > 1:            # 多选时给整体加个虚线框
            xs = [self.sketch.atom(i)["x"] for i in sel]
            ys = [self.sketch.atom(i)["y"] for i in sel]
            bx1, by1 = S(min(xs), min(ys))
            bx2, by2 = S(max(xs), max(ys))
            pad = 12 * z
            c.create_rectangle(bx1 - pad, by1 - pad, bx2 + pad, by2 + pad,
                               outline=ACCENT, dash=(4, 3), width=1)
        if isinstance(self._pending, int):
            a = self.sketch.atom(self._pending)
            if a:
                x, y = S(a["x"], a["y"])
                r = max(6, 14 * z)
                c.create_oval(x - r, y - r, x + r, y + r,
                              outline="#e08b12", width=2)
        elif isinstance(self._pending, tuple):
            x, y = S(*self._pending)
            c.create_oval(x - 4, y - 4, x + 4, y + 4, outline=RED, width=2)

        # 框选删除的实时矩形
        if self._box:
            bx0, by0 = S(self._box[0], self._box[1])
            bx1, by1 = S(self._box[2], self._box[3])
            c.create_rectangle(bx0, by0, bx1, by1, outline=RED, dash=(5, 3),
                               width=1, fill="#f7dcdc", stipple="gray25")

        # 选择框（蓝）——松手后框内原子被选中，可整体拖动
        if self._sel_box:
            bx0, by0 = S(self._sel_box[0], self._sel_box[1])
            bx1, by1 = S(self._sel_box[2], self._sel_box[3])
            c.create_rectangle(bx0, by0, bx1, by1, outline=ACCENT, dash=(4, 3),
                               width=1, fill="#dce9fb", stipple="gray25")

        self.zoom_lbl.configure(text=f"{int(round(self.zoom * 100))}%")
        ab = self.sketch.abbrev_count()
        self.hint.configure(
            text=f"当前工具：{tool_title(self.tool)}    原子 {len(self.sketch.atoms)}  "
                 f"键 {len(self.sketch.bonds)}  箭头 {len(self.sketch.arrows)}"
                 + (f"  缩写 {ab}" if ab else "")
                 + (f"  角色 {len(self.sketch.roles)}" if self.sketch.roles else "")
                 + ("    ·  双击原子可改文字" if self.show_tips.get() else ""))

    # ------------------------------------------------------------ 预览
    def _refresh_preview(self):
        smi, err = self.sketch.smiles()
        self.smi.configure(state="normal")
        self.smi.delete("1.0", "end")
        self.smi.insert("1.0", smi or ("（还没画出可解析的结构）" if not err else err))
        self.smi.configure(state="disabled")
        # 高度跟着内容走：1–3 行，长 SMILES 才占满，短的不留空白。
        # 窗口刚建立时 Text 宽度还没定，displaylines 会把短文本算成 3 行，
        # 所以先用字符数兜底：一行大约放 36 个等宽字符。
        text = smi or ("（还没画出可解析的结构）" if not err else err)
        if len(text) <= 36:
            n = 1
        else:
            try:
                self.smi.configure(height=1)
                self.smi.update_idletasks()
                got = self.smi.count("1.0", "end-1c", "displaylines")
                n = int(got[0]) if got else 1
            except Exception:                # noqa: BLE001
                n = 1
        self.smi.configure(height=max(1, min(3, n)))

        lines = []
        ab = self.sketch.abbrev_count()
        if ab:
            lines.append(f"缩写基团 {ab} 个（按 * 处理，不展开）")
        if self.sketch.roles:
            g = self.sketch.reaction_groups()
            tag = [f"{ROLE_NAMES[r]} {len(g[r])}" for r in ROLE_ORDER if g[r]]
            if tag:
                lines.append("角色：" + "  ".join(tag))
        if self.sketch.mode == "structure" and smi and ">>" not in smi:
            mol = Chem.MolFromSmiles(smi)
            if mol is not None:
                note = "（不含缩写部分）" if ab else ""
                lines.append(f"分子式  {rdMolDescriptors.CalcMolFormula(mol)}{note}")
                lines.append(f"分子量  {Descriptors.MolWt(mol):.2f}{note}")
        elif self.sketch.mode == "scheme":
            left, right, agents = self.sketch.split_scheme()
            lines.append(f"反应物片段 {len(left)}   产物片段 {len(right)}")
            if agents:
                lines.append("试剂/条件：" + "、".join(agents[:2]))
        if err:
            lines.append("提示：" + err)
        # 详情默认收起：SMILES 才是常用信息，角色/片段/试剂按下才展开
        self._detail_text = "\n".join(lines)
        if self._detail_text.strip():
            self.detail_btn.configure(state="normal", fg="#7a8798")
        else:
            self.detail_btn.configure(state="disabled", fg="#c3ccd6")
        self._render_detail()

    def _render_detail(self):
        """收起时把标签整个摘掉：空 Label 仍占一行高度，会留一条空白。"""
        txt = self._detail_text if self.detail_open.get() else ""
        if txt.strip():
            self.props.configure(text=txt)
            if not self.props.winfo_manager():
                self.props.pack(anchor="w", fill="x", padx=10,
                                after=self.detail_bar)
        else:
            self.props.configure(text="")
            if self.props.winfo_manager():
                self.props.pack_forget()

    def _toggle_detail(self):
        self.detail_open.set(not self.detail_open.get())
        self.detail_btn.configure(
            text="▾ 绘制详情" if self.detail_open.get() else "▸ 绘制详情")
        self._render_detail()

    def _register_tip(self, widget, parent, **pack_kw):
        """登记一条可折叠提示，记住它在父容器里的原始位置。

        不套一层 Frame：Tk 里 Frame 的子控件 pack_forget 之后，Frame 的高度
        不会自己缩回去，会留下一条空白，收起时按钮「弹不回来」。
        直接挂父容器、用 pack(before=...) 定位，显隐才完全对称。
        """
        kids = parent.winfo_children()
        idx = kids.index(widget) if widget in kids else len(kids) - 1
        self.tip_items.append({"w": widget, "parent": parent, "idx": idx,
                               "pack": pack_kw, "before": None})

    def _finalize_tips(self):
        """界面搭完后，把每条提示的「插回到谁前面」定下来。"""
        for it in self.tip_items:
            kids = it["parent"].winfo_children()
            for k in kids[it["idx"] + 1:]:
                # 其它提示默认没 pack，跳过；找到第一个真正显示的控件
                if k is it["w"] or not k.winfo_manager():
                    continue
                it["before"] = k
                break

    def _toggle_tips(self):
        """底栏「▸ 用法提示」：一次控制全部六处说明文字。"""
        show = not self.show_tips.get()
        self.show_tips.set(show)
        for it in self.tip_items:
            w = it["w"]
            if show:
                if not w.winfo_manager():
                    kw = dict(it["pack"])
                    b = it["before"]
                    if b is not None and b.winfo_manager():
                        kw["before"] = b
                    w.pack(**kw)
            elif w.winfo_manager():
                w.pack_forget()
        self.tip_btn.configure(text="▾ 用法提示" if show else "▸ 用法提示",
                               bg="#e8eef7" if show else "#eef1f5",
                               fg=ACCENT if show else "#7a8798")
        self.redraw()                  # 状态行的提示后缀跟着变

    # ------------------------------------------------------------ 操作
    def save(self):
        smi, err = self.sketch.smiles()
        if not smi:
            messagebox.showwarning("还画不了", err or "先画几个原子再保存。",
                                  parent=self.win)
            return
        self.sketch.title = self.title_var.get().strip()
        data = self.sketch.to_json()
        did = None
        # owner_id=None 表示「只借用画板回填表单」，不往库里写孤儿记录
        if self.owner_id is not None:
            try:
                if self.drawing is not None:
                    self.store.update_drawing(self.drawing["id"],
                                              title=self.sketch.title,
                                              kind=self.sketch.mode, data=data, smiles=smi)
                    did = self.drawing["id"]
                else:
                    did = self.store.add_drawing(self.owner_type, self.owner_id,
                                                 title=self.sketch.title,
                                                 kind=self.sketch.mode,
                                                 data=data, smiles=smi)
            except Exception as e:
                messagebox.showerror("保存失败", str(e), parent=self.win)
                return
        if self.on_smiles:
            self.on_smiles(smi)
        if self.on_saved:
            self.on_saved(did)
        self.win.destroy()

    def export_png(self):
        path = filedialog.asksaveasfilename(parent=self.win, defaultextension=".png",
                                            filetypes=[("PNG", "*.png")],
                                            initialfile="ELN-绘制.png")
        if not path:
            return
        self.sketch.render_png(1440, 1040, show_h=self.show_h).save(path)
        messagebox.showinfo("导出完成", f"图片已保存到\n{path}", parent=self.win)

    def open_ketcher(self):
        """把当前图交给 Ketcher（浏览器里的专业画板）编辑，改完回写画板。"""
        import ketcherwin
        if not ketcherwin.is_built():
            messagebox.showwarning(
                "Ketcher 还没构建",
                "找不到 vendor\\ketcher-app\\dist。\n\n"
                "在项目目录双击 tools\\build_ketcher.bat 构建一次即可"
                "（需要 Node.js，约 1–2 分钟；构建产物随程序一起用，之后不用联网）。",
                parent=self.win)
            return
        if self.sketch.mode == "scheme":
            text, err = self.sketch.cdxmlfile()
        else:
            text, err = self.sketch.molfile()
        if err:
            messagebox.showwarning("导不出去", err, parent=self.win)
            return
        if not ketcherwin.open_editor(self.win, text, self._apply_ketcher):
            messagebox.showerror("打不开 Ketcher",
                                 "没能启动浏览器窗口。", parent=self.win)

    def _apply_ketcher(self, payload):
        """Ketcher 回写结果 → 画板。payload 见 ketcherwin.open_editor。"""
        if not payload or not payload.get("saved"):
            if payload and payload.get("timeout"):
                messagebox.showinfo("已超时", "等了太久没收到 Ketcher 的回写，"
                                    "画板保持原样。", parent=self.win)
            return
        d = payload.get("data") or {}
        cdxml = (d.get("cdxml") or "").strip()
        rxn = (d.get("rxn") or "").strip()
        mol = (d.get("mol") or "").strip()
        smi = (d.get("smiles") or "").strip()
        try:
            if cdxml:
                # CDXML 能带走箭头和试剂文字，优先用
                from structure import parse_cdxml_full
                data = parse_cdxml_full(text=cdxml)
                if data.get("error"):
                    raise ValueError(data["error"])
                if not (data["atoms"] or data["arrows"] or data["labels"]):
                    raise ValueError("Ketcher 回写的内容是空的")
                self._push_undo()
                cw = self.canvas.winfo_width()
                ch = self.canvas.winfo_height()
                if cw <= 120 or ch <= 120:
                    cw, ch = 900, 620
                if not self.sketch.from_cdxml(data, width=cw, height=ch):
                    raise ValueError("文件里没有可定位的对象")
                self.mode_var.set("反应式" if self.sketch.arrows else "结构式")
            elif rxn:
                from rdkit.Chem import rdChemReactions
                r = rdChemReactions.ReactionFromRxnBlock(rxn)
                if r is None:
                    raise ValueError("RXN 解析不了")
                self._push_undo()
                self.sketch.from_rxn(r)
                self.mode_var.set("反应式")
            elif mol:
                m = Chem.MolFromMolBlock(mol, removeHs=False, sanitize=True)
                if m is None:
                    raise ValueError("MOL 解析不了")
                self._push_undo()
                self.sketch.atoms, self.sketch.bonds = [], []
                self.sketch.labels, self.sketch.arrows = [], []
                self.sketch._next = 1
                self.sketch.from_mol(m, 220, 240)
                self.mode_var.set("结构式")
            elif smi:
                self._push_undo()
                self.sketch.from_smiles(smi, 220, 240)
                self.mode_var.set("结构式")
            else:
                raise ValueError("Ketcher 没有返回任何结构")
        except Exception as e:                       # noqa: BLE001
            messagebox.showerror("读回失败", str(e), parent=self.win)
            return
        self.zoom_fit()
        self._refresh_preview()
        messagebox.showinfo("已回写",
                            "Ketcher 里的结构已经放回画板。\n\n"
                            "确认无误后点「保存到记录」。",
                            parent=self.win)

    def open_chemdraw(self):
        """写 CDXML（反应式）/ MOL（结构式），交给 ChemDraw 打开。不碰 COM。"""
        folder = handoff_dir(create=True)
        if self.sketch.mode == "scheme":
            text, err = self.sketch.cdxmlfile()
            ext = ".cdxml"
        else:
            text, err = self.sketch.molfile()
            ext = ".mol"
        if err:
            messagebox.showwarning("导不出去", err, parent=self.win)
            return
        path = os.path.join(folder, "ELN-drawing" + ext)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:
            if os.path.exists(CHEMDRAW_EXE):
                subprocess.Popen([CHEMDRAW_EXE, path])
            elif sys.platform == "win32":
                os.startfile(path)              # noqa: S606
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("打不开", f"{e}\n\n文件已写好：{path}", parent=self.win)
            return
        if ext == ".cdxml":
            tip = ("反应箭头和箭头上的试剂 / 条件文字都一起带过去了。\n\n"
                   "改完直接按 Ctrl+S（另存默认就在这个目录，直接覆盖原文件即可），\n"
                   "然后回来点「读回 ChemDraw 文件」。\n\n"
                   f"交换目录：{folder}")
        else:
            tip = ("改完按 Ctrl+S 存回同一目录（或另存为 MOL / CDXML），\n"
                   "然后回来点「读回 ChemDraw 文件」。\n\n"
                   f"交换目录：{folder}")
        messagebox.showinfo("已交给 ChemDraw", f"文件：{path}\n\n{tip}",
                            parent=self.win)

    def open_chemdraw_rxn(self):
        """兼容路径：只写 MDL RXN（只有反应物/产物，不含箭头与文字）。"""
        folder = handoff_dir(create=True)
        text, err = self.sketch.rxnfile()
        if err:
            messagebox.showwarning("导不出去", err, parent=self.win)
            return
        path = os.path.join(folder, "ELN-drawing.rxn")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:
            if os.path.exists(CHEMDRAW_EXE):
                subprocess.Popen([CHEMDRAW_EXE, path])
            elif sys.platform == "win32":
                os.startfile(path)              # noqa: S606
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("打不开", f"{e}\n\n文件已写好：{path}", parent=self.win)
            return
        messagebox.showinfo(
            "已交给 ChemDraw",
            f"文件：{path}\n\nRXN 不含反应箭头和箭头上的文字，\n"
            "试剂条件要在 ChemDraw 里自己补。\n"
            "改完另存为 .rxn 或 .mol，回来点「读回 ChemDraw 文件」。",
            parent=self.win)

    def open_exchange_folder(self):
        """在资源管理器里打开默认交换目录（目录不在就自动建）。"""
        folder = handoff_dir(create=True)
        try:
            if sys.platform == "win32":
                os.startfile(folder)            # noqa: S606
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:                   # noqa: BLE001
            messagebox.showerror("打不开文件夹", f"{e}\n\n目录：{folder}",
                                 parent=self.win)

    def read_chemdraw(self):
        # 默认打开交换目录（而不是整个附件目录）：导出件、改好的文件都在那里，
        # 不会误选到 attachments/chemdraw/ 下那份只有箭头的原始导出件
        folder = handoff_dir()
        if not os.path.isdir(folder):
            folder = exchange_dir() if os.path.isdir(exchange_dir()) else None
        newest = ""
        if folder:
            try:
                cands = [os.path.join(folder, n) for n in os.listdir(folder)
                         if n.lower().endswith((".cdxml", ".mol", ".rxn"))]
            except OSError:
                cands = []
            if cands:
                newest = os.path.basename(max(cands, key=os.path.getmtime))
        path = filedialog.askopenfilename(
            parent=self.win, title="选择 ChemDraw 改完存回的文件",
            initialdir=folder, initialfile=newest,
            filetypes=[("ChemDraw / MDL 文件", "*.cdxml *.mol *.rxn"),
                       ("所有文件", "*.*")])
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".rxn":
                from rdkit.Chem import rdChemReactions
                rxn = rdChemReactions.ReactionFromRxnFile(path)
                if rxn is None:
                    raise ValueError("反应文件解析不了")
                self._push_undo()
                self.sketch.from_rxn(rxn)
                self.mode_var.set("反应式")
            elif ext == ".cdxml":
                from structure import parse_cdxml_full
                data = parse_cdxml_full(path)
                if data.get("error"):
                    raise ValueError(data["error"])
                if not (data["atoms"] or data["arrows"] or data["labels"]):
                    raise ValueError("文件里没有可读回的内容")
                self._push_undo()
                # 取景用真实画布尺寸，否则写死的小尺寸会把整张图压成一小团
                cw = self.canvas.winfo_width()
                ch = self.canvas.winfo_height()
                if cw <= 120 or ch <= 120:          # 窗口还没布局完
                    cw, ch = 900, 620
                if not self.sketch.from_cdxml(data, width=cw, height=ch):
                    raise ValueError("文件里没有可定位的对象")
                skipped = getattr(self.sketch, "skipped_objects", 0)
                self.mode_var.set("反应式" if self.sketch.arrows else "结构式")
                parts = []
                # 这里数的是**实际读进画板**的对象，不是文件里的总数——
                # 被跳过的孤立对象不该再出现在「已读回」里
                if self.sketch.atoms:
                    parts.append(f"{len(self.sketch.atoms)} 个原子")
                if self.sketch.bonds:
                    parts.append(f"{len(self.sketch.bonds)} 根键")
                if self.sketch.arrows:
                    parts.append(f"{len(self.sketch.arrows)} 支箭头")
                if self.sketch.labels:
                    parts.append(f"{len(self.sketch.labels)} 段文字")
                msg = "已读回：" + "、".join(parts) + "。\n\n位置按文件原样还原。"
                if skipped:
                    msg += (f"\n\n另有 {skipped} 个对象离结构太远，已跳过"
                            "（多半是早先残留的孤立箭头 / 文字）。")
                msg += "\n\n文件：" + path
                if not data["atoms"]:
                    # 最常见的情况：选的是旧的那份原始导出件，
                    # 而改过的结构被 ChemDraw 另存到了别处
                    msg += ("\n\n注意：这份文件里没有任何原子，只有箭头 / 文字。"
                            "\n如果你刚在 ChemDraw 里画或改过结构，请改从默认交换目录读取："
                            f"\n{handoff_dir(create=True)}")
                if data["notes"]:
                    msg += "\n\n" + "\n".join(data["notes"][:3])
                messagebox.showinfo("读回完成", msg, parent=self.win)
            else:
                mol = Chem.MolFromMolFile(path, removeHs=False)
                if mol is None:
                    raise ValueError("molfile 解析不了")
                self._push_undo()
                self.sketch.atoms, self.sketch.bonds = [], []
                self.sketch.labels, self.sketch.arrows = [], []
                self.sketch._next = 1
                self.sketch.from_mol(mol, 220, 240)
                self.mode_var.set("结构式")
        except Exception as e:
            messagebox.showerror("读回失败", str(e), parent=self.win)
            return
        self.zoom_fit()                 # 读回后先适应窗口，别让用户自己找图
        self._refresh_preview()
        self._refresh_preview()


def open_drawpad(app_root, store, owner_type, owner_id, **kw) -> DrawWindow:
    """统一入口，GUI / 对话框都用这个。"""
    import keyfix
    keyfix.install()          # 修 Text 吞字符（'-' 被报成 keysym Insert）
    return DrawWindow(app_root, store, owner_type, owner_id, **kw)
