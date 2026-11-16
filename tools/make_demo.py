#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成一份演示数据库（不含任何真实实验数据）。

用法：
    python tools/make_demo.py                    # 写到 demo/eln_demo.db
    python tools/make_demo.py --out x.db         # 指定位置

生成内容：4 个药剂、1 条反应（含组成表）、1 张结构式、1 张反应式。
演示库只在仓库里作为样例，程序运行时用的是根目录的 eln.db（互不影响）。
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import chem                      # noqa: E402
import drawpad                   # noqa: E402
import store as store_mod        # noqa: E402
from rdkit import Chem           # noqa: E402
from rdkit.Chem import rdDepictor  # noqa: E402

SAMPLES = [
    ("BZ-01", "苯甲醛", "100-52-7", "O=Cc1ccccc1",
     2.5, "g", "99%", "液体", "4℃ 冰箱 A 层"),
    ("BZ-02", "苯甲酸", "65-85-0", "O=C(O)c1ccccc1",
     1.8, "g", "99.5%", "固体", "干燥器"),
    ("BZ-03", "苯甲醇", "100-51-6", "OCc1ccccc1",
     5.0, "mL", "98%", "液体", "试剂柜 2 层"),
    ("EA-01", "乙酸乙酯", "141-78-6", "CCOC(C)=O",
     500, "mL", "AR", "液体", "通风橱"),
]


def mol_to_sketch(smiles: str, dx: float = 0.0, scale: float = 46.0,
                  sketch: drawpad.Sketch | None = None) -> drawpad.Sketch:
    """把一个分子按 2D 坐标铺进草图（原子/键），返回草图。"""
    mol = Chem.MolFromSmiles(smiles)
    # 必须先 Kekulé 化：否则芳香键是 1.5 阶，转成整数键序会把苯环画成环己烷
    Chem.Kekulize(mol, clearAromaticFlags=True)
    rdDepictor.Compute2DCoords(mol)
    conf = mol.GetConformer()
    s = sketch or drawpad.Sketch(mode="structure")
    idmap = {}
    for atom in mol.GetAtoms():
        p = conf.GetAtomPosition(atom.GetIdx())
        idmap[atom.GetIdx()] = s.add_atom(atom.GetSymbol(),
                                          p.x * scale + dx, -p.y * scale + 150)
    for bond in mol.GetBonds():
        s.add_bond(idmap[bond.GetBeginAtomIdx()], idmap[bond.GetEndAtomIdx()],
                   order=int(bond.GetBondTypeAsDouble()))
    return s


def build(db_path: str, attach_dir: str) -> None:
    for p in (db_path,):
        if os.path.exists(p):
            os.remove(p)
    st = store_mod.Store(db_path, attach_dir)

    ids = {}
    for code, name, cas, smi, amount, unit, purity, state, loc in SAMPLES:
        info = chem.analyze(smi)
        ids[name] = st.add_sample(
            code=code, name=name, cas=cas, smiles=info["smiles"],
            molfile=info["molfile"], formula=info["formula"], mw=info["mw"],
            amount=amount, unit=unit, purity=purity, state=state,
            location=loc, note="演示数据，可直接删改。")

    # ---- 反应：苯甲醛氧化制苯甲酸
    rid = st.add_reaction(
        code="R-01",
        title="苯甲醛氧化制苯甲酸",
        conditions="O2（空气），催化量醋酸钴，乙酸为溶剂，40 ℃",
        procedure="1. 苯甲醛 2.5 g 溶于 20 mL 乙酸；\n"
                  "2. 加入醋酸钴 5 mg，40 ℃ 通空气反应 4 h；\n"
                  "3. 冷却，加水析出，抽滤，乙醇重结晶。",
        yield_pct=86.0,
        note="演示数据。")
    st.add_component(rid, sample_id=ids["苯甲醛"], role="反应物",
                     equivalents=1.0, amount=2.5, unit="g")
    st.add_component(rid, sample_id=ids["苯甲酸"], role="产物",
                     equivalents=1.0, amount=2.6, unit="g")
    st.add_component(rid, sample_id=ids["乙酸乙酯"], role="溶剂",
                     equivalents=None, amount=20, unit="mL")

    # ---- 结构式绘制（苯甲酸）
    sk = mol_to_sketch("O=C(O)c1ccccc1")
    sk.title = "苯甲酸"
    st.add_drawing("sample", ids["苯甲酸"], title="苯甲酸结构式",
                   kind="structure", data=sk.to_json(), smiles="O=C(O)c1ccccc1")

    # ---- 反应式绘制（苯甲醛 → 苯甲酸）
    sch = drawpad.Sketch(mode="scheme", title="苯甲醛氧化")
    mol_to_sketch("O=Cc1ccccc1", dx=0, sketch=sch)
    mol_to_sketch("O=C(O)c1ccccc1", dx=380, sketch=sch)
    sch.add_arrow(175, 150, 330, 150)
    sch.add_label(200, 118, "O2, Co(OAc)2")
    st.add_drawing("reaction", rid, title="苯甲醛氧化制苯甲酸",
                   kind="scheme", data=sch.to_json(), smiles="O=Cc1ccccc1>>O=C(O)c1ccccc1")

    try:                                  # 顺带灌一份示例笔记
        st._seed_notebook()
    except Exception:
        pass
    st.close() if hasattr(st, "close") else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "demo", "eln_demo.db"))
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    build(out, os.path.join(os.path.dirname(out), "attachments"))
    print("已生成演示库：", out, "%.0f KB" % (os.path.getsize(out) / 1024))
    print("查看：python cli.py --db", os.path.relpath(out, ROOT), "stats")


if __name__ == "__main__":
    main()
