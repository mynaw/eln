# -*- coding: utf-8 -*-
"""
化学计算：SMILES / molfile 进出，算分子式分子量，画结构式，做子结构检索。

全部走 RDKit，不联网。好处是快、离线可用；
代价是查不了中文名、CAS 和供应商——那是 PubChem 的活。
"""
from __future__ import annotations

import io

from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, rdDepictor, rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D

RDLogger.DisableLog("rdApp.*")

# 常见溶剂/试剂的简写，画反应式时用得上
ABBREV = {
    "THF": "C1CCOC1", "DCM": "ClCCl", "DMSO": "CS(C)=O", "DMF": "CN(C)C=O",
    "MeOH": "CO", "EtOH": "CCO", "EtOAc": "CCOC(C)=O", "ACN": "CC#N",
    "TFA": "OC(=O)C(F)(F)F", "TEA": "CCN(CC)CC", "DIPEA": "CCN(C(C)C)C(C)C",
    "Py": "c1ccncc1", "tBuOK": "CC(C)(C)[O-].[K+]", "NaH": "[Na+].[H-]",
}


def load(text: str):
    """SMILES / molfile / 简写，随便给一个，返回 RDKit Mol 或 None。"""
    if not text:
        return None
    text = text.strip()
    if text in ABBREV:
        text = ABBREV[text]

    if "\n" in text and ("V2000" in text or "V3000" in text):
        mol = Chem.MolFromMolBlock(text, sanitize=True, removeHs=False)
        if mol is not None:
            return mol

    mol = Chem.MolFromSmiles(text)
    if mol is not None:
        return mol

    # 最后试一次 InChI
    if text.startswith("InChI="):
        return Chem.MolFromInchi(text)
    return None


def analyze(text: str) -> dict:
    """从结构文本提取属性。失败返回 {"error": ...}。"""
    mol = load(text)
    if mol is None:
        return {"error": "这个结构解析不了，检查一下 SMILES 有没有写错"}

    try:
        rdDepictor.Compute2DCoords(mol)
    except Exception:
        pass

    try:
        formula = rdMolDescriptors.CalcMolFormula(mol)
    except Exception:
        formula = ""
    try:
        mw = Descriptors.MolWt(mol)
    except Exception:
        mw = 0.0

    return {
        "mol": mol,
        "smiles": Chem.MolToSmiles(mol),
        "formula": formula,
        "mw": round(float(mw), 3),
        "exact_mw": round(float(Descriptors.ExactMolWt(mol)), 4),
        "molfile": Chem.MolToMolBlock(mol),
        "inchi": Chem.MolToInchi(mol) if hasattr(Chem, "MolToInchi") else "",
        "rings": rdMolDescriptors.CalcNumRings(mol),
        "hbd": rdMolDescriptors.CalcNumHBD(mol),
        "hba": rdMolDescriptors.CalcNumHBA(mol),
        "tpsa": round(float(rdMolDescriptors.CalcTPSA(mol)), 2),
        "logp": round(float(Descriptors.MolLogP(mol)), 2),
    }


def mol_from_record(record) -> Chem.Mol | None:
    """从数据库行取结构：优先 molfile，退回 smiles。"""
    if record is None:
        return None
    block = record["molfile"] if "molfile" in record.keys() else None
    if block:
        mol = Chem.MolFromMolBlock(block, sanitize=True, removeHs=False)
        if mol is not None:
            return mol
    smi = record["smiles"] if "smiles" in record.keys() else None
    return Chem.MolFromSmiles(smi) if smi else None


def _prep_stereo(m):
    """补全立体信息：分配立体化学 + 按 2D 坐标补楔形/虚线键。

    这样即使分子来自 molfile（楔形信息缺失）或刚生成 2D 坐标，
    画出来也能用实楔/虚楔正确表达 R/S，并配合 addStereoAnnotation 标注 (R)/(S)。
    """
    try:
        Chem.AssignStereochemistry(m, cleanIt=True, force=True)
    except Exception:                      # noqa: BLE001
        pass
    try:
        Chem.WedgeMolBonds(m, m.GetConformer())
    except Exception:                      # noqa: BLE001
        pass
    return m


def render(mol, width: int = 300, height: int = 220, bg=(1, 1, 1, 0)):
    """画结构式，返回 PIL Image（RGBA）。失败返回 None。

    线宽与字号随画布等比缩放（RDKit 默认的 bondLineWidth=2 / maxFontSize=40
    是按小画布定的，画布一大线条和标签就细小得「不协调」）。
    """
    if mol is None:
        return None
    from PIL import Image

    try:
        m = Chem.Mol(mol)
        rdDepictor.Compute2DCoords(m)
        _prep_stereo(m)
        drawer = rdMolDraw2D.MolDraw2DCairo(int(width), int(height))
        opts = drawer.drawOptions()
        k = max(1.0, max(int(width), int(height)) / 460.0)
        opts.bondLineWidth = 2
        opts.scaleBondWidth = True          # 键线宽随分子比例缩放
        opts.minFontSize = int(6 * k)
        opts.maxFontSize = int(40 * k)
        opts.clearBackground = True
        opts.setBackgroundColour((1, 1, 1, 0))
        opts.padding = 0.08
        opts.addStereoAnnotation = True     # 手性碳/双键旁标 (R)/(S)/(E)/(Z)
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, m)
        drawer.FinishDrawing()
        png = drawer.GetDrawingText()
        return Image.open(io.BytesIO(png)).convert("RGBA")
    except Exception:
        return None


def render_svg(mol, width: int = 300, height: int = 220) -> str | None:
    """画结构式的矢量版（SVG 文本），给 PDF / 打包导出内嵌用。失败返回 None。"""
    if mol is None:
        return None
    try:
        m = Chem.Mol(mol)
        rdDepictor.Compute2DCoords(m)
        _prep_stereo(m)
        drawer = rdMolDraw2D.MolDraw2DSVG(int(width), int(height))
        opts = drawer.drawOptions()
        k = max(1.0, max(int(width), int(height)) / 460.0)
        opts.bondLineWidth = 2
        opts.scaleBondWidth = True
        opts.minFontSize = int(6 * k)
        opts.maxFontSize = int(40 * k)
        opts.clearBackground = True
        opts.padding = 0.08
        opts.addStereoAnnotation = True     # 与位图版一致：标 (R)/(S)/(E)/(Z)
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, m)
        drawer.FinishDrawing()
        return drawer.GetDrawingText()
    except Exception:
        return None


def render_smiles_svg(text: str, width: int = 300, height: int = 220) -> str | None:
    mol = load(text)
    return render_svg(mol, width, height) if mol is not None else None


def render_smiles(text: str, width: int = 300, height: int = 220):
    mol = load(text)
    return render(mol, width, height) if mol is not None else None


def substructure_hits(query: str, records) -> list[int]:
    """在给定的 (id, molfile) 记录里找含该子结构的。

    query 可以写 SMARTS（比如 c1ccccc1 找苯环），也可以写 SMILES。
    """
    q = None
    for loader in (Chem.MolFromSmarts, Chem.MolFromSmiles):
        try:
            q = loader(query)
        except Exception:
            q = None
        if q is not None:
            break
    if q is None:
        return []

    hits = []
    for rec in records:
        block = rec["molfile"] if "molfile" in rec.keys() else None
        if not block:
            continue
        mol = Chem.MolFromMolBlock(block, sanitize=True, removeHs=False)
        if mol is None:
            continue
        try:
            if mol.HasSubstructMatch(q):
                hits.append(rec["id"])
        except Exception:
            continue
    return hits


def similarity_hits(query: str, records, threshold: float = 0.35) -> list[tuple[int, float]]:
    """Tanimoto 相似性检索，返回 [(id, 分数)]，从高到低。"""
    from rdkit.Chem import AllChem, DataStructs

    q = load(query)
    if q is None:
        return []
    qfp = AllChem.GetMorganFingerprintAsBitVect(q, 2, nBits=2048)

    out = []
    for rec in records:
        block = rec["molfile"] if "molfile" in rec.keys() else None
        if not block:
            continue
        mol = Chem.MolFromMolBlock(block, sanitize=True, removeHs=False)
        if mol is None:
            continue
        fp = AllChem.GetMorganFingerprintAsBitVect(mol, 2, nBits=2048)
        out.append((rec["id"], float(DataStructs.TanimotoSimilarity(qfp, fp))))
    out.sort(key=lambda x: -x[1])
    return [(i, round(s, 3)) for i, s in out if s >= threshold]


# ---------------------------------------------------------------- 导入导出

def read_sdf(path: str) -> list[dict]:
    """读 SDF，返回可以直接入库的字典列表。"""
    out = []
    try:
        supplier = Chem.SDMolSupplier(path, removeHs=False)
    except Exception:
        return out

    for mol in supplier:
        if mol is None:
            continue
        try:
            rdDepictor.Compute2DCoords(mol)
        except Exception:
            pass
        props = mol.GetPropsAsDict(includePrivate=False) if hasattr(mol, "GetPropsAsDict") else {}
        name = (mol.GetProp("_Name") if mol.HasProp("_Name") else "").strip()
        name = name or props.get("name") or props.get("Name") or ""
        try:
            formula = rdMolDescriptors.CalcMolFormula(mol)
            mw = round(float(Descriptors.MolWt(mol)), 3)
        except Exception:
            formula, mw = "", 0.0
        out.append({
            "name": name or Chem.MolToSmiles(mol)[:40],
            "smiles": Chem.MolToSmiles(mol),
            "molfile": Chem.MolToMolBlock(mol),
            "formula": formula,
            "mw": mw,
            "cas": props.get("CAS") or props.get("cas") or "",
            "note": props.get("note") or "",
        })
    return out


def write_sdf(path: str, rows) -> int:
    """把带 molfile 的记录写成 SDF，属性能带上名称和分子式。"""
    writer = Chem.SDWriter(path)
    n = 0
    for r in rows:
        block = r["molfile"] if "molfile" in r.keys() else None
        if not block:
            continue
        mol = Chem.MolFromMolBlock(block, sanitize=True, removeHs=False)
        if mol is None:
            continue
        mol.SetProp("_Name", r["name"] or "")
        for field in ("code", "cas", "formula", "smiles"):
            if field in r.keys() and r[field]:
                mol.SetProp(field, str(r[field]))
        writer.write(mol)
        n += 1
    writer.close()
    return n
