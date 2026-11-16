# -*- coding: utf-8 -*-
"""基团电子效应引擎 —— 已完整并入 ELN，纯本地，无外部项目依赖。

原独立判断器项目的 engine.py / groups.py / hybrid.py / structure.py /
ext.py 已完整迁到本目录，ELN 直接 import，不再按路径动态加载，
也不再有独立启动入口。

化学口径：基团表里的 σ 值是「取代基连在苯环上、以 H 为零点」的相对值，
所以 scan_molecule() 切出来的是取代基片段（带 * 连接点），只认表内精确命中，
不用推断值冒充文献值。

对外接口
--------
    available() -> (bool, str)          引擎是否可用 / 状态说明
    engine()                            惰性加载判断引擎
    analyze(query)                      基团名 / 别名 / 片段 SMILES → (报告, 错误)
    catalog()                           45 个基团的目录
    scan_molecule(smiles)               完整分子 → 命中的取代基列表
    hybrid_text(smiles)                 全分子杂化清单
    report_text(rec, width)             报告渲染成文本

    file_result(path)                   ChemDraw / MDL 结构文件 → 检出取代基
    clipboard_result()                  ChemDraw 复制的结构（剪贴板）
    from_smiles(smiles)                 绘制区 / 手动输入 SMILES → 同一条分析链
    mol_result(mol)                     已有 RDKit mol → 同一条分析链
    selection_result(mol, picked)       图上点选的原子 → 一条判定结果
    item_report(item, res)              检出项 / 点选项 → 右侧报告文字
    item_brief(item)                    检出项 → 左栏 (名称, σp, 总效应)
    babel_status()                      Open Babel 是否可用（.cdx 依赖它）
"""
from __future__ import annotations

import os

from rdkit import Chem

HERE = os.path.dirname(os.path.abspath(__file__))

_ENGINE = None
_HYBRID = None
_GROUPS = None
_STRUCTURE = None


def engine_dir() -> str:
    """引擎目录就是 ELN 自己：不再有外部判断器目录。"""
    return HERE


def available() -> tuple[bool, str]:
    """引擎是否可用。

    源码环境看三个 .py 在不在；打包（PyInstaller）环境里模块被压进 PYZ，
    磁盘上没有 .py 文件，所以改为看模块能否导入。
    """
    need = ("engine", "groups", "hybrid")
    missing = []
    for name in need:
        try:
            __import__(name)
        except Exception:
            missing.append(name + ".py")
    if missing:
        return False, f"ELN 内置效应引擎缺文件：{'、'.join(missing)}"
    return True, HERE


def engine():
    """惰性加载本地的 engine 模块。"""
    global _ENGINE, _HYBRID, _GROUPS
    if _ENGINE is not None:
        return _ENGINE
    ok, msg = available()
    if not ok:
        raise RuntimeError(msg)
    import groups as _groups_mod
    import hybrid as _hybrid_mod
    import engine as _engine_mod
    _GROUPS, _HYBRID, _ENGINE = _groups_mod, _hybrid_mod, _engine_mod
    return _ENGINE


def catalog() -> list[dict]:
    """基团目录：名称、σ、方向、定位效应。不给移动端算杂化，保持轻量。"""
    e = engine()
    rows = []
    for g in _GROUPS.GROUPS:
        cls, _ = e.total_effect(g)
        rows.append({
            "key": g["key"], "name": g["zh"], "en": g["en"],
            "smiles": g.get("smiles", ""), "sp": g.get("sp"),
            "sm": g.get("sm"), "ind": g.get("ind"), "mes": g.get("mes"),
            "cls": cls, "aromatic": g.get("aromatic", "—"),
            "conf": g.get("conf", ""),
        })
    return rows


def analyze(query: str) -> tuple[dict | None, str]:
    """基团名 / 英文 / 缩写 / 带 * 的片段 SMILES → (报告 dict, 错误信息)。"""
    return engine().analyze(query)


def analyze_fragment(smiles: str):
    """带 * 连接点的片段 → 报告（只接受表内精确命中或结构推断）。"""
    return engine().analyze_fragment(smiles)


def fragment_candidates(smiles: str, max_atoms: int = 14) -> list[dict]:
    """完整分子 → 切断每条非环单键后「较小一侧」的取代基片段。

    每条键只取重原子数较少的一段：芳香取代体系里这一段就是取代基，
    另一段是母体。带电的单原子碎片（硝酰氧、羧酸根里的氧）不算独立取代基。
    """
    mol = Chem.MolFromSmiles(smiles or "")
    if mol is None:
        return []
    n0 = mol.GetNumAtoms()
    out: dict[str, dict] = {}
    for bond in mol.GetBonds():
        if bond.IsInRing() or bond.GetBondTypeAsDouble() != 1.0:
            continue
        if min(bond.GetBeginAtom().GetAtomicNum(),
               bond.GetEndAtom().GetAtomicNum()) <= 1:
            continue
        try:
            cut = Chem.FragmentOnBonds(mol, [bond.GetIdx()], addDummies=True,
                                       dummyLabels=[(0, 0)])
            mapping: list = []
            parts = Chem.GetMolFrags(cut, asMols=True, sanitizeFrags=True,
                                     fragsMolAtomMapping=mapping)
        except Exception:
            continue
        cands = []
        for frag, ids in zip(parts, mapping):
            orig = frozenset(i for i in ids if i < n0
                             and mol.GetAtomWithIdx(i).GetAtomicNum() > 1)
            if not (1 <= len(orig) <= max_atoms):
                continue
            if not any(a.GetAtomicNum() == 0 for a in frag.GetAtoms()):
                continue
            if len(orig) == 1:
                only = mol.GetAtomWithIdx(next(iter(orig)))
                if only.GetFormalCharge():
                    continue
            cands.append((len(orig), frag, orig))
        if not cands:
            continue
        _, frag, orig = min(cands, key=lambda x: (x[0], Chem.MolToSmiles(x[1])))
        for atom in frag.GetAtoms():
            if atom.GetAtomicNum() == 0:
                atom.SetIsotope(0)
                atom.SetAtomMapNum(0)
        try:
            smi = Chem.MolToSmiles(frag)
        except Exception:
            continue
        if smi not in out:
            out[smi] = {"fragment": smi, "atoms": orig}
    return list(out.values())


def scan_molecule(smiles: str) -> list[dict]:
    """完整分子里有哪些表内基团。返回按取代基大小排序的命中列表。

    只保留表内精确命中（不把「推断」当成文献值）；被更大基团包含的碎片
    （羧基里的羟基、硝基里的氧）与同 key 的重复项会被丢掉。
    """
    if not smiles:
        return []
    found = []
    for cand in fragment_candidates(smiles):
        try:
            rec = analyze_fragment(cand["fragment"])
        except Exception:
            continue
        if not rec or rec.get("key") == "*INFERRED":
            continue
        found.append({**cand, "rec": rec})
    found.sort(key=lambda h: (-len(h["atoms"]), h["rec"]["key"]))
    kept = []
    for hit in found:
        if any(hit["atoms"] <= k["atoms"] for k in kept):
            continue
        if any(k["rec"]["key"] == hit["rec"]["key"] for k in kept):
            continue
        kept.append(hit)
    return kept


def hybrid_text(smiles: str, width: int = 62) -> str:
    """整分子的杂化清单（用判断器的 hybrid 模块算）。"""
    engine()                      # 确保 hybrid 模块已加载
    mol = Chem.MolFromSmiles(smiles or "")
    if mol is None:
        return "SMILES 解析失败，无法给出杂化轨道。"
    try:
        return _HYBRID.format_mol(mol, width=width)
    except Exception as e:
        return f"杂化分析失败：{e}"


def report_text(rec: dict, width: int = 62) -> str:
    return engine().format_report(rec, width=width)


# 原 open_standalone() 已移除：判断器完全并入 ELN，不再有独立程序入口。


def summarize(hits: list[dict]) -> str:
    """一句话概括扫描结果，给状态栏用。"""
    if not hits:
        return "未命中表内基团"
    names = [h["rec"]["name"] for h in hits[:4]]
    more = f" 等 {len(hits)} 个" if len(hits) > 4 else ""
    return "、".join(names) + more


# ---------------------------------------------------------------- 结构文件 / 绘制 / 点选
# 原独立判断器的两大能力：解析 ChemDraw 文件（.cdx/.cdxml/.mol/…）、
# 在结构图上点选原子判定基团。引擎 structure.py 已完整并入 ELN，
# 这里做一层薄封装，界面只认这几个函数，不直接碰底层模块。

def structure_module():
    """惰性加载内置 structure 模块（ChemDraw / MDL 解析 + 取代基检出）。"""
    global _STRUCTURE
    if _STRUCTURE is None:
        import structure
        _STRUCTURE = structure
    return _STRUCTURE


def file_result(path: str) -> dict:
    """读结构文件 → 检出环上取代基并逐个判定。失败抛 FileError / OSError。"""
    return structure_module().analyze_file(path)


def clipboard_result() -> dict:
    """读 ChemDraw 复制到剪贴板的结构（CF_TEXT / 内嵌 CDX）。"""
    return structure_module().analyze_clipboard()


def mol_result(mol, name: str = "绘制结构", notes=None,
               file: str = "绘制结构") -> dict:
    """已有 RDKit mol → 与文件完全相同的分析链。"""
    return structure_module().analyze_mol(mol, name=name, notes=notes, file=file)


def from_smiles(smiles: str, name: str = "结构", notes=None) -> dict:
    """绘制区 / 手动输入的 SMILES → 分析链。"""
    mol = Chem.MolFromSmiles(smiles or "")
    if mol is None:
        raise ValueError("这个 SMILES 解析不了，检查画的结构有没有断开或化合价不对。")
    return mol_result(mol, name=name, notes=notes, file=name)


def selection_result(mol, picked) -> dict:
    """用户在结构图上点选的一坨原子 → 一条可判定的 item。"""
    return structure_module().analyze_selection(mol, sorted(picked))


def supported_formats() -> tuple[str, ...]:
    return structure_module().SUPPORTED


def babel_status() -> str:
    try:
        v = structure_module().obabel_version()
    except Exception as e:
        return f"Open Babel 检测失败：{e}"
    return ("Open Babel 已就绪" if v != "未安装"
            else "未装 Open Babel（.cdx/.mol2/.rxn 读不了）")


def _sp(v) -> str:
    return "—" if v is None else (f"+{v:.2f}" if v > 0 else f"{v:.2f}")


def item_brief(item: dict) -> tuple[str, str, str]:
    """左栏一行：名称、σp、总效应。桥连 / 判不出来的项也要有可读的一行。"""
    no = item.get("no", 1)
    if item.get("bridge"):
        return (f"{no}. 自定义片段", "—", "桥连（定性）")
    rec = item.get("rec")
    if not rec:
        return (f"{no}. {item.get('frag', '')}", "—", "无法判定")
    return (f"{no}. {rec['name']}", _sp(rec.get("sp")), rec["cls"])


def item_report(item: dict, res: dict | None = None, width: int = 64) -> str:
    """把自动检出项 / 用户点选项渲染成右侧文本框里的报告。

    普通项沿用引擎的完整 σ 报告，末尾补上它所在的文件、环系、相对位置；
    桥连片段没有 Hammett σ，改列逐连接点的定性判断。
    """
    st = structure_module()
    line = "-" * width
    if item.get("bridge"):
        out = ["自定义片段（两端连在母体上）",
               f"结构    {item.get('frag', '')}", "",
               "说明    桥连基团 · Hammett σ 只对单价基团有定义，这里不给数值",
               line, ""]
        out += st.bridge_text(item, "    ", width)
        return "\n".join(out)

    rec = item.get("rec")
    if not rec:
        return ("这个片段判不出来\n\n"
                f"结构    {item.get('frag', '')}\n\n"
                f"原因    {item.get('err') or '未收录且无法按结构推断'}\n\n"
                "可以在结构图上只圈出环外那一块，再点「判定这块」。")

    text = report_text(rec, width=width)
    src = rec.get("src") or {}
    extra: list[str] = []
    if res:
        extra.append(f"文件    {res.get('file', '')}  ·  {res.get('fmt', '')}")
    if src.get("ring_name"):
        extra.append(f"环系    {src['ring_name']}  ·  {src.get('mode', '')}")
    pos = st.position_note(src)
    if pos:
        extra.append(f"相对位置    {pos}")
    notes = list((res or {}).get("notes") or [])
    if extra or notes:
        text += "\n" + line + "\n所在结构\n"
        for row in extra:
            text += "    " + row + "\n"
        for n in notes:
            text += "    · " + n + "\n"
    return text.rstrip()
