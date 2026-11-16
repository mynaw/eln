# -*- coding: utf-8 -*-
"""
判断引擎：输入一个基团（中文名 / 英文名 / 缩写 / SMILES），
输出「总体吸电子还是给电子」以及背后的诱导效应、共轭效应拆解。

三层判断：
  1. 查表：40 个常见基团的文献 σ 值 + 人工标注的 I/M 性质（最可靠）
  2. 结构推断：未收录的基团，用 RDKit 按杂化、孤对、共轭、电荷判方向（定性）
  3. 情境换算：σp / σp+ / σm 的区别，告诉你结论在不同反应里会不会翻转
"""

from __future__ import annotations

import difflib
import re
import unicodedata

from groups import GROUPS

# ---------------------------------------------------------------- 基础工具

MAG = {0: "无", 1: "弱", 2: "中等", 3: "强", 4: "极强"}


def norm(s: str) -> str:
    """统一大小写、全角、空格、各种减号。"""
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = (s.replace("—", "-").replace("–", "-").replace("－", "-")
          .replace("−", "-").replace("＋", "+"))
    return re.sub(r"\s+", "", s).lower()


def signed(v) -> str:
    return f"+{v:.2f}" if v > 0 else f"{v:.2f}"


# ---------------------------------------------------------------- 别名索引

_INDEX: dict[str, dict] = {}
_CONFLICT: list[str] = []


def _register(key: str, g: dict):
    k = norm(key)
    if not k:
        return
    old = _INDEX.get(k)
    if old is not None and old is not g:
        _CONFLICT.append(f"{k}: {old['key']} / {g['key']}")
        return
    _INDEX[k] = g


for _g in GROUPS:
    for _k in [_g["key"], _g["zh"], _g["en"], *_g.get("alias", [])]:
        _register(_k, _g)
    # 再登记去掉首尾连字符的形式（-NO2、-OH 这类写法）
    for _k in [_g["key"], _g["zh"], _g["en"], *_g.get("alias", [])]:
        _kk = norm(_k).strip("-")
        if _kk:
            _register(_kk, _g)


# ---------------------------------------------------------------- 查表

def lookup(query: str) -> dict | None:
    """按名称查表，返回基团 dict；找不到返回 None。"""
    raw = str(query or "").strip()
    q = norm(raw)
    if q in _INDEX:
        return _INDEX[q]
    q2 = q.strip("-()[],")
    if q2 in _INDEX:
        return _INDEX[q2]
    # "对甲氧基" "间硝基" 之类的位置前缀
    for pre in ("对", "间", "邻", "o-", "m-", "p-"):
        if q2.startswith(pre) and norm(q2[len(pre):]) in _INDEX:
            return _INDEX[norm(q2[len(pre):])]
    # SMILES 写法：必须用原始大小写（Cl / c 芳香碳 大小写有意义），先按骨架比对，
    # 命中就给出文献值，而不是走推断
    if "*" in raw:
        return lookup_smiles(raw)
    return None


_KEY_CACHE: dict[str, str] = {}


def probe_key(smiles: str) -> str:
    """把 * 换成苯环后算 InChIKey。

    ChemDraw 画的硝基是 N(=O)=O，表里存的是 [N+](=O)[O-]，两者 SMILES 不同
    但 InChI 归一后是同一个东西。苯甲酸 / 苯甲酸根之类也能这样对上。
    """
    Chem = _try_rdkit()
    if Chem is None or "*" not in smiles:
        return ""
    if smiles in _KEY_CACHE:
        return _KEY_CACHE[smiles]
    key = ""
    try:
        m = Chem.MolFromSmiles(smiles.replace("*", "c1ccccc1", 1))
        if m is not None:
            key = Chem.MolToInchiKey(m)
    except Exception:
        key = ""
    _KEY_CACHE[smiles] = key
    return key


def lookup_smiles(smiles: str) -> dict | None:
    """把 SMILES 规范化后与表内基团的骨架比对（*OC 与 CO* 视为同一个）。"""
    Chem = _try_rdkit()
    if Chem is None:
        return None
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return None
    target = Chem.MolToSmiles(m)
    for g in GROUPS:
        if "_canon" not in g:
            mg = Chem.MolFromSmiles(g["smiles"]) if g.get("smiles") else None
            g["_canon"] = Chem.MolToSmiles(mg) if mg else ""
        if g["_canon"] and g["_canon"] == target:
            return g

    # 骨架写法不同但化学上是同一个基团（硝基的两种画法最常见）
    tk = probe_key(smiles)
    if not tk:
        return None
    for g in GROUPS:
        if not g.get("smiles"):
            continue
        if probe_key(g["smiles"]) == tk:
            return g
    return None


def analyze_fragment(smiles: str) -> dict | None:
    """直接拿一个带 * 的片段（多来自文件里的结构）出报告。"""
    g = lookup_smiles(smiles) or infer_from_smiles(smiles)
    return report(g) if g else None


def suggest(query: str, n: int = 3) -> list[str]:
    """查不到时给相近的名字。"""
    q = norm(query)
    table = {norm(g["zh"]): g["zh"] for g in GROUPS}
    for g in GROUPS:
        table.setdefault(norm(g["key"]), g["zh"])
    hits = difflib.get_close_matches(q, list(table), n=n, cutoff=0.45)
    out = []
    for h in hits:
        if table[h] not in out:
            out.append(table[h])
    return out


# ---------------------------------------------------------------- 判断逻辑

def level_of(value: float | None) -> tuple[str, str]:
    """σp 数值 → (类别, 强度说明)。阈值见 README。"""
    if value is None:
        return "待定", ""
    v = value
    if v <= -0.40:
        return "强给电子", f"σp = {signed(v)}，明显低于 0"
    if v <= -0.10:
        return "给电子", f"σp = {signed(v)}，低于 0"
    if v < 0.10:
        return "近中性", f"σp = {signed(v)}，接近 0"
    if v < 0.40:
        return "吸电子", f"σp = {signed(v)}，高于 0"
    return "强吸电子", f"σp = {signed(v)}，明显高于 0"


def dominant(g: dict) -> tuple[str, int]:
    """哪个效应说了算，返回 (说法, 方向符号：+1 给电子 / -1 吸电子 / 0 抵消)。"""
    i, m = abs(g["ind"]), abs(g["mes"])
    if i == 0 and m == 0:
        return "两者皆无（只靠 σ 键极化，影响极小）", 0
    if m > i:
        sign = 1 if g["mes"] > 0 else -1
        return (f"共轭主导（M {m} 强于 I {i}）", sign)
    if i > m:
        sign = 1 if g["ind"] > 0 else -1
        return (f"诱导主导（I {i} 强于 M {m}）", sign)
    # 强度相同：看方向是否一致
    if g["ind"] * g["mes"] > 0:
        sign = 1 if g["mes"] > 0 else -1
        return (f"两者同向叠加（I、M 都是{'+' if sign > 0 else '-'}），强度相当", sign)
    if g["ind"] == 0:
        return "只有单一效应", (1 if g["mes"] > 0 else -1)
    return "两个效应强度相当、方向相反", 0


def total_effect(g: dict) -> tuple[str, float | None]:
    """总体效应：优先 σp，其次 σm，都没有就按主导效应定性。"""
    v = g["sp"] if g["sp"] is not None else g["sm"]
    if v is not None:
        return level_of(v)[0], v
    _, sign = dominant(g)
    if sign > 0:
        return "给电子", None
    if sign < 0:
        return "吸电子", None
    return "近中性", None


def consistency(g: dict) -> str:
    """用 I/M 推出来的方向去校验 σp，暴露"方向相反"的基团。

    注意两套符号：本文件的 ind/mes 用 + 表示给电子；
    σp 则是数值越大越吸电子。这里统一换算成"吸电子 = 正"。
    """
    dom_text, sign = dominant(g)
    v = g["sp"]
    if v is None:
        return "无 σ 值，仅按机理定性"
    sv = 1 if v > 0.10 else (-1 if v < -0.10 else 0)  # +1 = 吸电子
    if sv == 0:
        return "σp 落在 ±0.10 内：两种效应基本抵消，实测接近中性"
    if sign == 0:
        return "机理上两个效应相互抵消，净方向由实测 σp 决定"
    predict_absorb = sign < 0  # sign>0 是给电子
    if predict_absorb == (sv > 0):
        return "机理推断与 σp 方向一致"
    return "机理推断与 σp 方向相反，说明这个位置上次要效应占了上风"


def describe_I(g: dict) -> str:
    v = g["ind"]
    if v == 0:
        return "无明显诱导"
    return f"{MAG[min(abs(v), 4)]}{'吸电子' if v < 0 else '给电子'}（{'-I' if v < 0 else '+I'}）"


def describe_M(g: dict) -> str:
    v = g["mes"]
    if v == 0:
        return "无共轭"
    return f"{MAG[min(abs(v), 4)]}{'吸电子' if v < 0 else '给电子'}（{'-M' if v < 0 else '+M'}）"


# ---------------------------------------------------------------- 报告

TIP_AROMATIC = ("以上 σ 值是「基团连在苯环上、以 H 为 0」测得的。"
                "换到脂肪族（如卤代烷反应）只剩诱导效应，强弱顺序会变。")


def _hybrid_of(smiles: str):
    """基团连接原子 + 片段内各原子的杂化（判不了就返回 None，界面跳过这一节）。"""
    if not smiles:
        return None
    try:
        import hybrid
        return hybrid.analyze_smiles(smiles)
    except Exception:
        return None


def report(g: dict) -> dict:
    """生成结构化结论，CLI 和 GUI 共用。"""
    cls, sp = total_effect(g)
    dom_text, _ = dominant(g)
    rec = {
        "key": g["key"],
        "name": g["zh"],
        "en": g["en"],
        "smiles": g.get("smiles", ""),
        "cls": cls,
        "sp": g["sp"],
        "sm": g["sm"],
        "sp_plus": g.get("sp_plus"),
        "ind": describe_I(g),
        "mes": describe_M(g),
        "dominant": dom_text,
        "aromatic": g.get("aromatic", "—"),
        "hybrid": _hybrid_of(g.get("smiles", "")),
        "note": g.get("note", ""),
        "conf": g.get("conf", ""),
        "check": consistency(g),
        "tips": [],
    }
    if g.get("sp_plus") is not None and g.get("mes", 0) > 0:
        rec["tips"].append(
            f"亲电取代时别只看 σp：σp+ = {signed(g['sp_plus'])}，"
            f"实际给电子能力比 σp 显示的更强（苯胺类能快到百万倍就是这个原因）。")
    if abs(g["ind"]) and abs(g["mes"]) and g["ind"] * g["mes"] < 0:
        rec["tips"].append("诱导和共轭方向相反，属于「双面基团」：换一个反应位置或条件，净方向可能翻转。")
    if g.get("conf") == "定性":
        rec["tips"].append("该基团的 σ 值强烈依赖质子化状态（pH），本表未给数值。")
    if g.get("conf") == "近似":
        rec["tips"].append("σ 值在不同文献间有出入，这里取常见值，趋势可靠、数值仅供比较。")
    rec["tips"].append(TIP_AROMATIC)
    return rec


def hybrid_lines(rec: dict, width: int = 60) -> list[str]:
    """报告里「杂化」那一节。没有 RDKit 或判不出来就返回空列表，不影响其余输出。"""
    hy = rec.get("hybrid") or {}
    a = hy.get("attach")
    if not a:
        return []
    tag = "（共轭重杂化）" if a.get("rehybrid") else ""
    rows = [f"杂化    {a['symbol']} {a['hybrid']} · {a['geometry']} · {a['angle']}{tag}"]
    try:
        import hybrid as hb
        ptxt = hb.p_text(a)
    except Exception:
        ptxt = ""
    if ptxt:
        rows.extend(_wrap(ptxt, "        ", width).split("\n"))
    return rows


def format_report(rec: dict, width: int = 60) -> str:
    line = "-" * width
    out = [
        f"基团    {rec['name']}   [{rec['en']}]",
        f"结构    {rec['smiles']}",
        line,
        f"总效应  {rec['cls']}",
        f"        比参比 H  {'大' if (rec['sp'] or 0) > 0 else ('小' if (rec['sp'] or 0) < 0 else '持平')}"
        f" {abs(rec['sp']):.2f}" if rec["sp"] is not None else "        无文献 σ 值，按机理定性",
        f"数据    σm = {signed(rec['sm']) if rec['sm'] is not None else '—'}    "
        f"σp = {signed(rec['sp']) if rec['sp'] is not None else '—'}    "
        f"σp+ = {signed(rec['sp_plus']) if rec['sp_plus'] is not None else '—'}",
        line,
        f"诱导    {rec['ind']}",
        f"共轭    {rec['mes']}",
        *hybrid_lines(rec, width),
        f"主导    {rec['dominant']}",
        f"校验    {rec['check']}",
        line,
        f"芳环    {rec['aromatic']}",
    ]
    if rec["note"]:
        out.append(f"说明    {rec['note']}")
    if rec["conf"]:
        out.append(f"可信度  {rec['conf']}")
    if rec["tips"]:
        out.append(line)
        for t in rec["tips"]:
            out.append(_wrap(t, "提示    ", width))
    return "\n".join(out)


def _wrap(text: str, prefix: str, width: int) -> str:
    """按显示宽度折行，中文算 2 列。"""
    def w(ch: str) -> int:
        return 2 if unicodedata.east_asian_width(ch) in "WF" else 1

    out, cur, used = [], prefix, sum(w(c) for c in prefix)
    indent = " " * sum(w(c) for c in prefix)
    NO_LEAD = "。，、；：）》」』”%！？·）"
    for ch in text:
        if used + w(ch) > width and ch not in NO_LEAD:
            out.append(cur)
            cur, used = indent, len(indent)
        cur += ch
        used += w(ch)
    out.append(cur)
    return "\n".join(out)


# ---------------------------------------------------------------- RDKit 推断

def _try_rdkit():
    try:
        from rdkit import Chem, RDLogger
        RDLogger.DisableLog("rdApp.*")  # 用户输入非法 SMILES 时不要刷一屏红字
        return Chem
    except Exception:
        return None


def infer_from_smiles(smiles: str) -> dict | None:
    """数据库里没有的基团：按结构规则推断方向。返回伪 group dict。"""
    Chem = _try_rdkit()
    if Chem is None:
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None

    dummy = next((a for a in mol.GetAtoms() if a.GetAtomicNum() == 0), None)
    if dummy is None or not dummy.GetNeighbors():
        return None
    a = dummy.GetNeighbors()[0]

    sym = a.GetSymbol()
    charge = a.GetFormalCharge()
    reasons: list[str] = []
    ind = 0
    mes = 0

    # ---- 诱导效应 ----
    if charge > 0:
        ind = -3
        reasons.append(f"连接原子 {sym} 带正电荷，强 -I")
    elif charge < 0:
        ind = 1
        reasons.append(f"连接原子 {sym} 带负电荷，+I（推电子）")
    elif sym in ("F",):
        ind = -3
        reasons.append("直接连 F，最强 -I")
    elif sym in ("O", "N", "Cl"):
        ind = -2
        reasons.append(f"{sym} 电负性明显高于碳，-I")
    elif sym in ("S",):
        n_double_o = sum(1 for b in a.GetBonds()
                         if b.GetBondTypeAsDouble() >= 2 and b.GetOtherAtom(a).GetSymbol() == "O")
        ind = -3 if n_double_o else -1
        reasons.append(f"S 连着 {n_double_o} 个 S=O" if n_double_o else "S 电负性略高于碳，弱 -I")
        if n_double_o:
            reasons.append("磺酰基型 S 是强 -I")
    elif sym in ("Br", "I", "Se"):
        ind = -1
        reasons.append(f"{sym} 电负性略高于碳，弱 -I")
    elif sym in ("Si",):
        ind = 1
        reasons.append("Si 电负性低于碳，+I")
    elif sym == "C":
        nb = [b.GetOtherAtom(a).GetSymbol() for b in a.GetBonds()]
        n_het = sum(1 for s in nb if s in ("O", "N", "F", "Cl", "Br", "I", "S"))
        if n_het:
            ind = -min(3, n_het)
            reasons.append(f"碳上连着 {n_het} 个杂原子，-I")
        elif a.GetHybridization().name != "SP3":
            ind = -1
            reasons.append("sp²/sp 碳比 sp³ 碳更吸电子，弱 -I")
        else:
            ind = 1
            reasons.append("饱和碳（烷基），靠 +I 供电子")
    elif sym in ("H",):
        ind = 0
        reasons.append("就是氢，参比零点")

    # ---- 共轭效应 ----
    pi_accept = False
    for b in a.GetBonds():
        if b.GetBondTypeAsDouble() >= 2:
            other = b.GetOtherAtom(a)
            if other.GetSymbol() in ("O", "N", "S"):
                pi_accept = True
            if other.GetSymbol() == "C" and other.GetHybridization().name in ("SP", "SP2"):
                pi_accept = True
    if sym == "S":
        n_double_o = sum(1 for b in a.GetBonds()
                         if b.GetBondTypeAsDouble() >= 2 and b.GetOtherAtom(a).GetSymbol() == "O")
        if n_double_o >= 1:
            pi_accept = True

    has_lone_pair = sym in ("N", "O", "S", "P", "F", "Cl", "Br", "I", "Se") and charge <= 0
    # 判断孤对是否被别的基团占用（酰胺、酯的氧会打折）
    if sym == "N" and any(b.GetOtherAtom(a).GetSymbol() in ("C", "S") and
                          any(x.GetBondTypeAsDouble() >= 2 and x.GetOtherAtom(b.GetOtherAtom(a)).GetSymbol() == "O"
                              for x in b.GetOtherAtom(a).GetBonds()) for b in a.GetBonds()):
        has_lone_pair = "weak"

    if pi_accept:
        mes = -2
        reasons.append("含 C=O / C=N / S=O / 三键这类可接受电子的 π 键，-M")
    elif has_lone_pair == "weak":
        mes = 1
        reasons.append("有孤对但被相邻羰基/磺酰基拉走一半，+M 很弱")
    elif has_lone_pair:
        mes = 2
        reasons.append(f"{sym} 上未共用电子对可与芳环共轭，+M")
    elif sym == "C" and a.GetHybridization().name != "SP3":
        mes = 1
        reasons.append("sp² 碳的 π 轨道可与环共轭，弱 +M")
    else:
        mes = 0
        reasons.append("没有可共轭的 π 键或孤对，无共轭效应")

    return dict(
        key="*INFERRED",
        zh="未收录基团 " + (smiles if len(smiles) <= 18 else smiles[:18] + "…"),
        en="inferred",
        alias=[],
        smiles=smiles,
        sm=None, sp=None, sp_plus=None,
        conf="推断",
        ind=max(-3, min(3, ind)),
        mes=max(-3, min(3, mes)),
        aromatic="未收录，无法给出定位效应",
        note="未在数据表中：以下由 RDKit 按原子性质推断（" + "；".join(reasons) + "）。仅定性，请与文献核对。",
    )


def analyze(query: str) -> tuple[dict | None, str]:
    """对外主入口。返回 (报告 dict 或 None, 错误信息)。"""
    q = (query or "").strip()
    if not q:
        return None, "输入为空"
    g = lookup(q)
    if g is None and ("*" in q or re.search(r"[A-Za-z]\d?", q) and len(q) > 3):
        g = infer_from_smiles(q)
    if g is None:
        hint = suggest(q)
        msg = f"没查到「{q}」"
        if hint:
            msg += "，你是不是想找：" + "、".join(hint)
        msg += "\n  可以直接输入带连接点的 SMILES（如 *OC 表示甲氧基）来推断。"
        return None, msg
    return report(g), ""


# ---------------------------------------------------------------- 排行/对比

def ranked() -> list[dict]:
    """按 σp 从最给电子排到最吸电子。"""
    rows = [report(g) for g in GROUPS if g["sp"] is not None]
    return sorted(rows, key=lambda r: r["sp"])


def compare(a: str, b: str) -> str | None:
    ra, ea = analyze(a)
    rb, eb = analyze(b)
    if not ra or not rb:
        return None
    if ra["sp"] is None or rb["sp"] is None:
        return f"{ra['name']} 与 {rb['name']} 至少一个没有 σp 数值，只能定性比较。"
    d = ra["sp"] - rb["sp"]
    stronger = ra["name"] if d > 0 else rb["name"]
    weaker = rb["name"] if d > 0 else ra["name"]
    return (f"{ra['name']}(σp {signed(ra['sp'])}) 与 {rb['name']}(σp {signed(rb['sp'])}) 相比：\n"
            f"  {stronger} 更吸电子 {abs(d):.2f} 个 σ 单位。\n"
            f"  按 ρ=1 估算，反应速率相差约 {10 ** abs(d):.1f} 倍。")


if __name__ == "__main__":
    # 自检：跑通查表、推断、排序三条路径
    for q in ("甲氧基", "-NO2", "CF3", "Ph", "coo-", "*S(=O)(=O)N", "不存在的基团"):
        r, err = analyze(q)
        print("=" * 60)
        print("问:", q)
        print(format_report(r) if r else "  " + err)
    print("=" * 60)
    print("冲突检查:", _CONFLICT or "无")
