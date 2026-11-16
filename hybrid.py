# -*- coding: utf-8 -*-
"""
判断原子的杂化轨道（sp / sp2 / sp3 …），并给出推理过程。

判断用的是课本那套，不是黑箱：

    立体数（VSEPR 空间构型数）= σ 键数 + 孤对电子数
        2 → sp      直线形        180°
        3 → sp2     平面三角形    120°
        4 → sp3     四面体        109.5°
        5 → sp3d    三角双锥
        6 → sp3d2   正八面体

孤对电子数由价电子算：
    孤对 = (价电子数 - 形式电荷 - 成键电子数) / 2

然后再叠两条化学上必须知道的修正：

1. **芳香原子**一律按 sp2 处理——环上每个原子拿出一个 p 轨道形成离域 π，
   哪怕 VSEPR 算出来是别的。环是五元环且杂原子带孤对时（吡咯 / 呋喃 / 噻吩型），
   那对孤对是进 p 轨道参与 6π 的；六元环的杂原子（吡啶型）孤对留在 sp2 轨道、朝环外。
2. **共轭重杂化**：按 σ + 孤对算出 sp3、但孤对紧挨着 π 体系（羰基、芳环、双键）的原子，
   实际上会向 sp2 靠拢（酰胺 N、苯酚 O、酯 O 都是这一类）。程序照实说"按 VSEPR 是 sp3，
   因共轭按 sp2 处理"，而不是硬改一个数糊弄过去。

对外接口
--------
analyze_atom(mol, idx)          RDKit 分子里的某个原子 → dict
analyze_smiles(smiles)          片段 SMILES（可带 * 连接点）→ 连接原子 + 片段内所有原子
analyze_mol(mol)                整个分子里每个重原子各判一次
brief(h) / describe(h)          一行 / 多行文本
report_lines(h, width)          GUI 用：连接原子 + 片段内其它原子

没有 RDKit 时全部返回 None，调用方跳过即可（和 engine 的写法保持一致）。
"""
from __future__ import annotations

# 常见元素的价电子数（只覆盖有机化学里会遇到的；表里没有的交给 RDKit 兜底）
VALENCE = {
    1: 1, 5: 3, 6: 4, 7: 5, 8: 6, 9: 7,
    14: 4, 15: 5, 16: 6, 17: 7,
    32: 4, 33: 5, 34: 6, 35: 7,
    52: 6, 53: 7,
}

STERIC = {2: "sp", 3: "sp2", 4: "sp3", 5: "sp3d", 6: "sp3d2"}

# 杂化 → (电子对空间构型, 标准键角, 剩下的 p 轨道数)
HYBRID_INFO = {
    "s":     ("—", "—", 0),
    "sp":    ("直线形", "180°", 2),
    "sp2":   ("平面三角形", "120°", 1),
    "sp3":   ("四面体", "109.5°", 0),
    "sp3d":  ("三角双锥", "90° / 120°", 1),
    "sp3d2": ("正八面体", "90°", 2),
}

# 杂化 + σ 键数 → (实际键角, 分子形状)
# 注意：形状由「连了几个原子」决定，不是由孤对数决定——所以按 σ 索引。
SHAPE = {
    "sp":    {2: (180.0, "直线形")},
    "sp2":   {3: (120.0, "平面三角形"), 2: (118.0, "V 形（角形）")},
    "sp3":   {4: (109.5, "正四面体形"), 3: (107.0, "三角锥形"), 2: (104.5, "V 形（角形）")},
    "sp3d":  {5: (None, "三角双锥形"), 4: (None, "变形四面体"), 3: (None, "T 形")},
    "sp3d2": {6: (None, "正八面体形"), 5: (None, "四方锥形"), 4: (None, "平面正方形")},
}


def _chem():
    try:
        from rdkit import Chem, RDLogger
        RDLogger.DisableLog("rdApp.*")
        return Chem
    except Exception:
        return None


# ---------------------------------------------------------------- 底层计数

def _lone_pairs(atom):
    """孤对电子数 = (价电子 - 形式电荷 - 成键电子 - 未成对电子) / 2。"""
    ve = VALENCE.get(atom.GetAtomicNum())
    if ve is None:
        return None
    bonded = sum(b.GetBondTypeAsDouble() for b in atom.GetBonds())
    bonded += atom.GetTotalNumHs()          # SMILES 里的隐式 H 不生成键，要单独加
    # 单电子不是孤对：甲基自由基 [CH3] 要按 3 个 σ + 0 对算，才是平面 sp2
    raw = (ve - atom.GetFormalCharge() - bonded - atom.GetNumRadicalElectrons()) / 2.0
    if raw <= 0.01:
        return 0
    return int(raw + 0.5)                   # 共振体系会算出 0.5 这种半整数，就近取整


def _has_pi_neighbor(atom):
    """旁边有没有能共轭的 π 体系（芳环 / 双键 / 叁键）。"""
    for b in atom.GetBonds():
        other = b.GetOtherAtom(atom)
        if other.GetAtomicNum() == 0:
            continue
        if other.GetIsAromatic():
            return True
        for ob in other.GetBonds():
            if ob.GetBondTypeAsDouble() > 1.5:
                if ob.GetOtherAtom(other).GetIdx() != atom.GetIdx():
                    return True
    return False


def _has_dummy_neighbor(atom):
    """这个原子是不是直接连在片段连接点 * 上。"""
    return any(b.GetOtherAtom(atom).GetAtomicNum() == 0 for b in atom.GetBonds())


def _aromatic_ring_size(mol, idx):
    for ring in mol.GetRingInfo().AtomRings():
        if idx in ring:
            return len(ring)
    return 0


def _shape_of(hybrid, sigma, aromatic=False, rehybrid=False, ring_size=0):
    """分子形状 + 实际键角。芳香环里、共轭重杂化的原子要特殊说法。"""
    if aromatic:
        return "平面（环内）", ("≈108°（五元环）" if ring_size == 5 else "≈120°")
    if sigma <= 1:
        return "端基原子", "—"
    if rehybrid:
        if sigma >= 3:
            return "三角锥形（共轭后压平）", "107°–120°"
        return "V 形（角形，比醚更开）", "≈118°"
    table = SHAPE.get(hybrid) or {}
    got = table.get(sigma)
    if not got:
        return HYBRID_INFO.get(hybrid, ("—",))[0], "—"
    angle, name = got
    return name, ("—" if angle is None else f"{angle:g}°")


# ---------------------------------------------------------------- 单个原子

def analyze_atom(mol, idx: int, parent_pi: bool = False) -> dict | None:
    """判断 mol 里 idx 号原子的杂化。返回 None 表示判不了（如 * 原子）。

    parent_pi=True 表示「这个原子通过 * 连到的母体按芳环算」——
    片段 SMILES 里 * 只是个占位符，看不出母体有没有 π，
    但 σ 值本来就是「连在苯环上」测的，所以默认按会共轭处理。
    """
    atom = mol.GetAtomWithIdx(idx)
    z = atom.GetAtomicNum()
    if z == 0:
        return None

    sym = atom.GetSymbol()
    charge = atom.GetFormalCharge()
    radical = atom.GetNumRadicalElectrons()

    if z == 1:
        return {
            "idx": idx, "symbol": "H", "charge": charge, "radical": 0,
            "hybrid": "s", "vsepr": "—", "geometry": "球形", "angle": "—",
            "sigma": 1, "lone": 0, "steric": 1, "p_left": 0,
            "aromatic": False, "rehybrid": False,
            "why": ["氢只有 1 个 1s 电子，直接拿 1s 成键，谈不上杂化"],
            "note": "", "rdkit": "",
        }

    sigma = atom.GetDegree() + atom.GetTotalNumHs()
    if sigma == 0:                          # 孤立原子 / 只有多重度的原子，谈杂化没意义
        return {
            "idx": idx, "symbol": sym, "charge": charge, "radical": radical,
            "hybrid": "—", "vsepr": "—", "geometry": "孤立原子（没有成键）", "angle": "—",
            "sigma": 0, "lone": 0, "steric": 0, "p_left": 0,
            "aromatic": False, "rehybrid": False,
            "why": ["这个原子没有和任何原子成键，没有 σ 骨架可谈，也就无所谓杂化"],
            "note": "", "rdkit": str(atom.GetHybridization()).lower(),
        }
    lone = _lone_pairs(atom)
    if lone is None:                        # 表外元素：退回 RDKit 的判断
        rd = str(atom.GetHybridization()).lower().replace("hybridization.", "")
        return {
            "idx": idx, "symbol": sym, "charge": charge, "radical": radical,
            "hybrid": rd, "vsepr": HYBRID_INFO.get(rd, ("—",))[0],
            "geometry": "—", "angle": "—", "sigma": sigma, "lone": 0,
            "steric": sigma, "p_left": HYBRID_INFO.get(rd, ("", "", 0))[2],
            "aromatic": atom.GetIsAromatic(), "rehybrid": False,
            "why": [f"{sym} 不在内置价电子表里，用 RDKit 的拓扑判断兜底"],
            "note": "", "rdkit": rd,
        }

    aromatic = atom.GetIsAromatic()
    ring_size = _aromatic_ring_size(mol, idx) if aromatic else 0
    rehybrid = False
    why: list[str] = []
    note = ""

    if aromatic:
        hybrid = "sp2"
        why.append("在芳环里：每个环原子留一个 p 轨道形成离域 π，所以是 sp2")
        size = ring_size
        if lone and size == 5:
            note = ("五元芳环上的杂原子（吡咯 / 呋喃 / 噻吩型）：这对孤对在 p 轨道上，"
                    "正是它凑够 6π 电子，属于「参与共轭」的孤对。")
        elif lone:
            note = ("六元芳环上的杂原子（吡啶型）：孤对在 sp2 轨道上、朝环外，"
                    "不参与环内 π（所以吡啶的 N 是碱，吡咯的 N 不是）。")
    else:
        steric = sigma + lone
        hybrid = STERIC.get(steric, "")
        if not hybrid:
            rd = str(atom.GetHybridization()).lower().replace("hybridization.", "")
            hybrid = rd or "sp3"
        why.append(f"{sigma} 个 σ 键 + {lone} 对孤对 = {steric} 个电子对，对应 {hybrid}")

        # 共轭重杂化：sp3 但有孤对、且挨着 π 体系
        via_parent = parent_pi and _has_dummy_neighbor(atom)
        if hybrid == "sp3" and lone >= 1 and (_has_pi_neighbor(atom) or via_parent):
            hybrid = "sp2"
            rehybrid = True
            if via_parent and not _has_pi_neighbor(atom):
                why.append("这对孤对会与母体（σ 值语境默认是苯环）的 π 体系共轭，"
                           "所以实际按 sp2 处理——这正是 +M 给电子的来源")
            else:
                why.append("按 σ + 孤对只算到 sp3，但这对孤对紧挨着 π 体系、要参与共轭，"
                           "实际按 sp2 处理（几何上会变平，键角介于 109.5° 和 120° 之间）")

    if radical and not rehybrid:
        why.append(f"带 {radical} 个未成对电子，自由基中心的杂化会受它影响，这里是按 σ 骨架算的")

    geometry, angle = _shape_of(hybrid, sigma, aromatic, rehybrid, ring_size)
    p_left = HYBRID_INFO.get(hybrid, ("", "", 0))[2]

    if sym in ("F", "Cl", "Br", "I") and sigma == 1:
        note = (note + " " if note else "") + \
               "卤素端基通常说「用 p 轨道成键」，教学中常不讨论它的杂化。"

    return {
        "idx": idx, "symbol": sym, "charge": charge, "radical": radical,
        "hybrid": hybrid,
        "vsepr": HYBRID_INFO.get(hybrid, ("—",))[0],
        "geometry": geometry, "angle": angle,
        "sigma": sigma, "lone": lone, "steric": sigma + lone,
        "p_left": p_left, "aromatic": aromatic, "rehybrid": rehybrid,
        "why": why, "note": note,
        "rdkit": str(atom.GetHybridization()).lower().replace("hybridization.", ""),
    }


def analyze_mol(mol) -> list[dict]:
    out = []
    for atom in mol.GetAtoms():
        h = analyze_atom(mol, atom.GetIdx())
        if h:
            out.append(h)
    return out


# ---------------------------------------------------------------- 片段

def analyze_smiles(smiles: str) -> dict | None:
    """片段 SMILES（可带 * 连接点）→ 连接原子 + 片段内所有重原子。"""
    Chem = _chem()
    if Chem is None or not smiles:
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    # 不显式加氢：隐式 H 的数目已经算进 σ 键数里了，加氢反而会让编号对不上

    attach_idx = None
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() == 0 and atom.GetNeighbors():
            attach_idx = atom.GetNeighbors()[0].GetIdx()
            break

    atoms = []
    for a in mol.GetAtoms():
        if a.GetAtomicNum() == 0:
            continue
        # 连接原子默认按「母体是芳环」处理：σ 值就是在苯环上测的
        h = analyze_atom(mol, a.GetIdx(), parent_pi=(a.GetIdx() == attach_idx))
        if h:
            atoms.append(h)
    if not atoms:
        return None

    attach = next((h for h in atoms if h["idx"] == attach_idx), None)

    # 同类归并：元素 + 杂化 + 孤对数 → 几个
    buckets: dict[tuple, dict] = {}
    for h in atoms:
        if h["idx"] == attach_idx:
            continue
        key = (h["symbol"], h["hybrid"], h["lone"], h["aromatic"])
        b = buckets.get(key)
        if b is None:
            b = buckets[key] = {"symbol": h["symbol"], "hybrid": h["hybrid"],
                                "lone": h["lone"], "aromatic": h["aromatic"],
                                "count": 0, "p_left": h["p_left"]}
        b["count"] += 1

    return {"attach": attach, "atoms": atoms, "others": list(buckets.values()),
            "n_atoms": len(atoms)}


# ---------------------------------------------------------------- 文本

def brief(h: dict | None) -> str:
    if not h:
        return "—"
    s = f"{h['hybrid']} · {h['geometry']}"
    if h["angle"] not in ("", "—"):
        s += f" · {h['angle']}"
    if h["rehybrid"]:
        s += "（共轭重杂化）"
    return s


def count_text(h: dict) -> str:
    """“4 个 σ 键 + 0 对孤对”"""
    bits = [f"{h['sigma']} 个 σ 键"]
    if h["lone"]:
        bits.append(f"{h['lone']} 对孤对")
    return " + ".join(bits)


def p_text(h: dict) -> str:
    if h["hybrid"] == "sp3":
        return "没有多余的 p 轨道，不能参与共轭"
    if h["hybrid"] == "sp2":
        if h.get("rehybrid"):
            return "孤对占着这 1 个 p 轨道，与旁边的 π 体系共轭"
        if h["aromatic"]:
            return "留 1 个 p 轨道（已经用在环内 π 上了）"
        if h["sigma"] <= 1:
            return "留 1 个 p 轨道，和对面那个原子组成 π 键"
        return "留 1 个 p 轨道，可参与 π 共轭"
    if h["hybrid"] == "sp":
        return "留 2 个互相垂直的 p 轨道，可形成两个 π"
    return "—"


def describe(h: dict, indent: str = "    ") -> list[str]:
    """多行详细说明（命令行 / 详情用）。"""
    out = [f"{h['symbol']}（{h['sigma']} 配位）  {brief(h)}",
           f"{indent}电子对    {count_text(h)} = {h['steric']}",
           f"{indent}p 轨道    {p_text(h)}"]
    for w in h["why"]:
        out.append(f"{indent}依据      {w}")
    if h["note"]:
        out.append(f"{indent}注意      {h['note']}")
    if h["charge"]:
        out.append(f"{indent}电荷      {h['charge']:+d}（已计入孤对计算）")
    return out


def _w(s: str) -> int:
    """显示宽度，中文算 2 列。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


LABEL_W = 12          # 「连接原子」「p 轨道」「片段内」统一占 12 列


def _wrap_value(value: str, label: str, width: int) -> list[str]:
    """把一行「标签 + 内容」折开，续行缩进到内容起点；优先在「 · 」「；」处断，不拆词。"""
    import re

    head = label + " " * max(2, LABEL_W - _w(label))
    indent = " " * _w(head)
    avail = max(10, width - _w(head))

    chunks: list[str] = []
    for part in re.split(r"(?<= · )|(?<=；)", value):
        if not part:
            continue
        cur = ""
        for ch in part:                      # 单块本身超宽时按字符硬折
            if _w(cur) + _w(ch) > avail and cur:
                chunks.append(cur)
                cur = ""
            cur += ch
        if cur:
            chunks.append(cur)

    lines, cur = [], head
    for ch in chunks:
        if _w(cur) - _w(head) + _w(ch) > avail and _w(cur) > _w(head):
            lines.append(cur.rstrip().rstrip("·").rstrip())
            cur = indent
        cur += ch
    lines.append(cur.rstrip().rstrip("·").rstrip())
    return lines


def report_lines(h: dict | None, width: int = 60) -> list[str]:
    """给 GUI 的紧凑版：连接原子 / 形状 / 电子对 / p 轨道，每项一行，窄面板也不会折碎。"""
    if not h or not h.get("attach"):
        return []
    a = h["attach"]
    tag = "（共轭重杂化）" if a.get("rehybrid") else ""
    lines = _wrap_value(f"{a['symbol']} · {a['hybrid']}{tag}", "连接原子", width)
    lines += _wrap_value(f"{a['geometry']} · {a['angle']}", "形状", width)
    lines += _wrap_value(count_text(a), "电子对", width)
    lines += _wrap_value(p_text(a), "p 轨道", width)

    others = h.get("others") or []
    if others:
        parts = []
        for b in others[:4]:
            seg = f"{b['symbol']} {b['hybrid']}"
            if b["count"] > 1:
                seg += f" ×{b['count']}"
            if b["lone"]:
                seg += f"（{b['lone']} 对孤对）"
            parts.append(seg)
        lines += _wrap_value("；".join(parts), "片段内", width)
        if len(others) > 4:
            lines += _wrap_value(f"另有 {len(others) - 4} 类原子", " ", width)
    return lines


def format_mol(mol, width: int = 60) -> str:
    """整分子的杂化清单（命令行 --hybrid 用）。"""
    items = analyze_mol(mol)
    if not items:
        return "判不出来。"
    lines = []
    for h in items:
        if h["symbol"] == "H":
            continue
        lines.append(f"{h['idx'] + 1:>3}  {h['symbol']:<2}  {brief(h)}"
                     f"   [{count_text(h)}]")
    return "\n".join(lines)
