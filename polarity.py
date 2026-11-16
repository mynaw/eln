# -*- coding: utf-8 -*-
"""极性变化解析：比较两个结构的 2D 极性描述符，给出变化量 + 成因/后果解读。

只依赖 RDKit（ELN 自带），纯函数、不联网、不碰数据库，方便复用与自检。

口径说明
--------
* logP 是 **中性分子** 的 Crippen 估算辛醇/水分配系数；酸碱化合物在缓冲液里
  应以 logD(pH) 为准，本模块会在检测到可电离基团时明确提示。
* TPSA 是 2D 拓扑极性表面积，不含构象屏蔽、分子内氢键与正式电荷贡献。
* 官能团计数用 SMARTS，彼此会重叠（羧酸同时含羰基与羟基），只作趋势参考。
"""
from __future__ import annotations

from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, Lipinski, rdMolDescriptors

RDLogger.DisableLog("rdApp.*")

KEYS = ("logp", "tpsa", "hbd", "hba")
LABELS = {
    "logp": "logP (Crippen)",
    "tpsa": "TPSA (Å²)",
    "hbd": "HBD 氢键供体",
    "hba": "HBA 氢键受体",
}

# (名称, SMARTS, 化学含义)
GROUPS = (
    ("羧酸", "[CX3](=O)[OX2H1]", "强极性且可电离；pH 升高后以羧酸根存在"),
    ("羧酸根", "[CX3](=O)[O-]", "带负电，水溶性显著增大"),
    ("磺酸/磺酰", "[SX4](=O)(=O)", "强极性，常以阴离子存在"),
    ("胺/氨基", "[NX3;H1,H2;!$(N=*)]", "碱性，酸性条件下质子化成铵盐"),
    ("羟基", "[OX2H]", "同时是氢键供体和受体"),
    ("酰胺", "[NX3][CX3](=O)", "强偶极、HBD/HBA 兼有"),
    ("硝基", "[N+](=O)[O-]", "大偶极、强吸电子"),
    ("腈", "[CX2]#[NX1]", "强偶极、HBA"),
    ("醛/酮羰基", "[CX3]=[OX1]", "HBA、有偶极但无 HBD"),
    ("酯", "[CX3](=O)[OX2][#6]", "HBA，无 HBD"),
    ("醚", "[OD2]([#6])[#6]", "HBA"),
    ("卤素", "[F,Cl,Br,I]", "弱极性，通常提高脂溶性"),
)

IONIZABLE = {"羧酸", "羧酸根", "磺酸/磺酰", "胺/氨基"}


def descriptors(smiles: str) -> dict:
    """单个结构的极性描述符。失败返回 {'error': ...}。"""
    text = (smiles or "").strip()
    if not text:
        return {"error": "SMILES 为空"}
    mol = Chem.MolFromSmiles(text)
    if mol is None:
        return {"error": f"SMILES 解析不了：{text[:40]}"}
    try:
        return {
            "smiles": Chem.MolToSmiles(mol),
            "formula": rdMolDescriptors.CalcMolFormula(mol),
            "mw": round(Descriptors.MolWt(mol), 2),
            "logp": round(Descriptors.MolLogP(mol), 2),
            "tpsa": round(rdMolDescriptors.CalcTPSA(mol), 2),
            "hbd": int(Lipinski.NumHDonors(mol)),
            "hba": int(Lipinski.NumHAcceptors(mol)),
        }
    except Exception as e:
        return {"error": f"描述符计算失败：{e}"}


def group_counts(smiles: str) -> dict:
    """常见极性/可电离基团的 SMARTS 计数（会重叠，只作趋势参考）。"""
    mol = Chem.MolFromSmiles((smiles or "").strip() or "")
    if mol is None:
        return {}
    out = {}
    for name, smarts, _ in GROUPS:
        try:
            q = Chem.MolFromSmarts(smarts)
            n = len(mol.GetSubstructMatches(q)) if q is not None else 0
        except Exception:
            continue
        if n:
            out[name] = n
    return out


def _score(d: dict) -> int:
    """把四个 Δ 折成一个方向分数：正 = 极性上升。"""
    s = 0
    t = d["tpsa"]
    if t >= 20:
        s += 2
    elif t >= 8:
        s += 1
    elif t <= -20:
        s -= 2
    elif t <= -8:
        s -= 1
    if d["hbd"] >= 1:
        s += 1
    elif d["hbd"] <= -1:
        s -= 1
    if d["hba"] >= 2:
        s += 1
    elif d["hba"] <= -2:
        s -= 1
    if d["logp"] <= -1.0:
        s += 1
    elif d["logp"] >= 1.0:
        s -= 1
    return s


def _verdict(s: int) -> str:
    if s >= 3:
        return "极性明显上升"
    if s == 2:
        return "极性上升"
    if s == 1:
        return "极性略上升"
    if s == 0:
        return "极性基本不变"
    if s == -1:
        return "极性略下降"
    if s == -2:
        return "极性下降"
    return "极性明显下降"


def compare(before: str, after: str) -> dict:
    """比较两个结构，返回描述符、Δ、官能团变化与解析文本。"""
    a, b = descriptors(before), descriptors(after)
    if "error" in a or "error" in b:
        return {"error": a.get("error") or b.get("error")}
    d = {k: round(b[k] - a[k], 2) for k in KEYS}
    s = _score(d)
    ga, gb = group_counts(a["smiles"]), group_counts(b["smiles"])
    changed = []
    for name in sorted(set(ga) | set(gb), key=lambda x: -abs(gb.get(x, 0) - ga.get(x, 0))):
        diff = gb.get(name, 0) - ga.get(name, 0)
        if diff:
            changed.append((name, ga.get(name, 0), gb.get(name, 0), diff))
    return {
        "a": a, "b": b, "delta": d, "score": s,
        "verdict": _verdict(s), "groups": changed,
        "ionizable": bool((set(ga) | set(gb)) & IONIZABLE),
        "lines": _analysis(a, b, d, s, changed,
                           bool((set(ga) | set(gb)) & IONIZABLE)),
    }


def _fmt(v) -> str:
    return f"{v:+.2f}" if isinstance(v, float) else f"{v:+d}"


def _analysis(a, b, d, score, changed, ionizable) -> list[str]:
    """生成「相关解析」：数据依据 → 成因 → 实验后果 → 局限。"""
    L: list[str] = []
    L.append(f"【结论】{_verdict(score)}（方向分 {score:+d}）")
    L.append("")
    L.append("【数据依据】")
    L.append(f"  {a['formula']} (M {a['mw']}) → {b['formula']} (M {b['mw']})")
    for k in KEYS:
        major = ((k == "tpsa" and abs(d["tpsa"]) >= 8)
                 or (k == "logp" and abs(d["logp"]) >= 1.0))
        mark = "   ← 主要变化" if major else ""
        L.append(f"  {LABELS[k]:<18} {a[k]:>8} → {b[k]:<8} Δ = {_fmt(d[k])}{mark}")
    L.append("")
    L.append("【成因解析】")
    reasons = []
    if abs(d["tpsa"]) >= 8:
        reasons.append(
            f"极性表面积{'增加' if d['tpsa'] > 0 else '减少'} {abs(d['tpsa']):.1f} Å²，"
            "通常来自极性杂原子/可电离基团的增删（O、N、S 及其氢键位点）。")
    if d["hbd"]:
        reasons.append(f"氢键供体 {a['hbd']} → {b['hbd']}："
                       f"{'多了 -OH/-NH/-COOH 之类可供氢的基团' if d['hbd'] > 0 else '可供氢的基团被取代或保护'}。")
    if d["hba"]:
        reasons.append(f"氢键受体 {a['hba']} → {b['hba']}："
                       f"{'多了羰基/醚/胺等受氢位点' if d['hba'] > 0 else '受氢位点减少'}。")
    if abs(d["logp"]) >= 0.4:
        reasons.append(f"Crippen logP {a['logp']} → {b['logp']}："
                       "亲脂性" + ("下降（更偏水相）" if d["logp"] < 0 else "上升（更偏有机相）") + "。")
    if not reasons:
        reasons.append("四个描述符变化都很小，骨架/取代基改变没有带来明显的极性重排。")
    for r in reasons:
        L.append("  · " + r)
    if changed:
        L.append("  官能团变化（SMARTS 计数，彼此会重叠，仅作趋势参考）：")
        for name, n0, n1, diff in changed[:6]:
            note = next((g[2] for g in GROUPS if g[0] == name), "")
            L.append(f"    - {name}：{n0} → {n1}（{diff:+d}）  {note}")
    else:
        L.append("  常见极性官能团的种类/数目没有明显变化（可能是骨架重排或异构）。")
    L.append("")
    L.append("【实验后果】")
    up = score > 0
    down = score < 0
    if not up and not down:
        L.append("  · 溶解度、分配与色谱行为预计与原来接近。")
        L.append("  · 但构象、分子内氢键、盐型与电离仍可能让实测出现差异，别只凭描述符下结论。")
    elif up:
        L.append("  · 水溶性 / 水相分配 ↑；用有机溶剂从水相萃取时回收率可能下降。")
        L.append("  · 反相 HPLC（C18）：保留变短、出峰提前。")
        L.append("  · 正相硅胶 TLC：吸附更强，同样展开剂下 Rf 变小、跑得更慢；"
                 "要把它推起来需提高洗脱剂极性（加大乙酸乙酯/甲醇比例）。")
        L.append("  · 正相柱层析：需要更强极性的洗脱体系，否则容易拖尾或留在柱上。")
    else:
        L.append("  · 脂溶性 ↑、水溶性 ↓；更容易被有机相萃出、水相损失减少。")
        L.append("  · 反相 HPLC（C18）：保留变长、出峰推后。")
        L.append("  · 正相硅胶 TLC：吸附变弱，Rf 变大、跑得更快；"
                 "必要时降低展开剂极性才能分开。")
        L.append("  · 正相柱层析：可用更弱极性的洗脱体系，出柱更早。")
    L.append("")
    L.append("【注意 / 局限】")
    if d["tpsa"] * d["logp"] < 0 and abs(d["tpsa"]) >= 8 and abs(d["logp"]) >= 0.05:
        L.append("  · TPSA 与 Crippen logP 给出的方向相反：这类情况多见于可电离基团或小分子，")
        L.append("    logP 的原子贡献法不可靠，判读以 TPSA / HBD 为主，")
        L.append("    并用 logD(pH) 或实测分配系数复核。")
    if ionizable:
        L.append("  · 检测到羧酸 / 羧酸根 / 磺酰 / 胺等可电离基团：logP 只描述中性形式，")
        L.append("    实际 pH 下的分配必须用 logD(pH)。pH 跨过 pKa 时极性可能完全不同，")
        L.append("    这里的结论只适用于中性分子之间的比较。")
    L.append("  · TPSA 是 2D 拓扑值，不计构象屏蔽、分子内氢键和正式电荷；"
             "Crippen logP 对可电离/两性离子也不准。")
    L.append("  · 单点结构比较不含盐型、溶剂、浓度与温度；结论用于判断趋势，"
             "具体条件以实测 Rf / RT / 溶解度为准。")
    return L


def format_report(res: dict) -> str:
    if "error" in res:
        return "无法比较：" + res["error"]
    return "\n".join(res["lines"])
