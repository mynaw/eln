# -*- coding: utf-8 -*-
"""自检：数据库、化学计算、命令行、演示数据、交付文件全过一遍。

    python selfcheck.py

只往 D:/Temp/agent 写临时文件，不会改动项目里的 eln.db。
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from argparse import Namespace

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

OK = 0
BAD = 0


def check(cond, msg):
    global OK, BAD
    if cond:
        OK += 1
    else:
        BAD += 1
        print("  [失败]", msg)


def tmp_dir():
    base = os.path.join(tempfile.gettempdir(), "eln_selfcheck")
    try:
        os.makedirs(base, exist_ok=True)
        return base
    except Exception:
        return tempfile.gettempdir()


def main():
    print("1/10 依赖与模块 …")
    try:
        import rdkit
        from rdkit import Chem
        check(True, "")
        check(tuple(int(x) for x in rdkit.__version__.split(".")[:2]) >= (2022, 9),
              "RDKit 版本太旧")
    except Exception as e:
        print("  [失败] RDKit 不可用：", e)
        return 1
    try:
        from PIL import Image
        check(hasattr(Image, "open"), "Pillow 不可用")
    except Exception as e:
        check(False, f"Pillow 不可用：{e}")
    try:
        import tkinter            # noqa: F401
        check(True, "")
    except Exception as e:
        check(False, f"tkinter 不可用：{e}")

    import chem
    import cli
    import dialogs
    import drawpad
    import effects
    import effectswin
    import gui
    import helpwin
    import notebook
    import store
    for mod in (chem, cli, dialogs, drawpad, effects, effectswin,
                gui, helpwin, notebook, store):
        check(mod is not None, "模块导入失败")
    check(hasattr(store.Store, "reaction_ids_by_samples"),
          "缺少按药剂关联反应的查询（结构检索会串号）")
    check(hasattr(gui.App, "apply_column_widths"), "缺少列宽修复")
    check(callable(chem.analyze) and callable(chem.write_sdf), "chem 接口不全")

    print("2/10 数据库层 …")
    tmp = tmp_dir()
    db = os.path.join(tmp, "eln_selfcheck.db")
    for p in (db, db + "-bak.db"):
        if os.path.exists(p):
            os.remove(p)
    st = store.Store(db)
    tables = {r["name"] for r in st.q("SELECT name FROM sqlite_master WHERE type='table'")}
    check({"collections", "samples", "reactions", "reaction_components",
           "attachments"} <= tables, "数据表没建全")
    cid = st.add_collection("自检集合")
    check(any(r["name"] == "自检集合" for r in st.collections()), "集合没写进去")
    st.rename_collection(cid, "改名后的集合")
    check(st.one("SELECT name FROM collections WHERE id=?", (cid,))["name"] == "改名后的集合",
          "集合重命名失败")

    info = chem.analyze("c1ccccc1")
    sid_benzene = st.add_sample(name="苯", code="BZ-1", smiles=info["smiles"],
                                molfile=info["molfile"], formula=info["formula"],
                                mw=info["mw"], amount=1.0, unit="mL",
                                collection_id=cid)
    info2 = chem.analyze("CCOC(C)=O")
    sid_ester = st.add_sample(name="乙酸乙酯", smiles=info2["smiles"],
                              molfile=info2["molfile"], formula=info2["formula"],
                              mw=info2["mw"], collection_id=cid)
    check(st.sample(sid_benzene)["formula"] == "C6H6", "药剂分子式不对")
    check(len(st.samples(cid)) == 2, "按集合筛选药剂不对")
    check(len(st.samples(keyword="BZ-1")) == 1, "按关键词筛选药剂不对")
    st.update_sample(sid_benzene, amount=2.5)
    check(st.sample(sid_benzene)["amount"] == 2.5, "药剂更新失败")
    check(st.sample(sid_benzene)["updated"] is not None, "更新时间没写")

    rid = st.add_reaction(title="苯的硝化", code="RX-1", yield_pct=76.5,
                          procedure="混酸，50 ℃", collection_id=cid)
    st.add_component(rid, sample_id=sid_benzene, role="反应物",
                     equivalents=1.0, amount=1.0, unit="mL")
    st.add_component(rid, label="浓硝酸", role="试剂", equivalents=1.2)
    comp = st.components(rid)
    check(len(comp) == 2, "反应组成条数不对")
    check(comp[0]["s_name"] == "苯", "组成没有联到药剂名")
    check(comp[1]["s_name"] is None and comp[1]["label"] == "浓硝酸",
          "手写组成的名称不对")
    check(st.reaction_ids_by_samples({sid_benzene}) == {rid},
          "按药剂找关联反应失败")
    check(st.reaction_ids_by_samples({sid_ester}) == set(),
          "没参与反应的药剂不该被算进去")
    check(st.reaction_ids_by_samples(set()) == set(), "空集合应返回空")

    link = os.path.join(tmp, "eln_selfcheck_note.txt")
    with open(link, "w", encoding="utf-8") as fh:
        fh.write("selfcheck")
    aid = st.link_attachment("sample", sid_benzene, link, "文档", "笔记")
    check(len(st.attachments("sample", sid_benzene)) == 1, "附件没登记")
    st.delete_attachment(aid)
    check(len(st.attachments("sample", sid_benzene)) == 0, "附件没删掉")
    check(st.stats()["samples"] == 2, "stats 统计不对")
    check(os.path.exists(st.backup_to(db + "-bak.db")), "备份文件没生成")

    st.delete_reaction(rid)
    check(st.components(rid) == [], "删反应后组成没级联清掉")
    st.delete_sample(sid_ester)
    check(st.sample(sid_ester) is None, "删药剂失败")
    st.delete_collection(cid)
    check(all(r["id"] != cid for r in st.collections()), "删集合失败")
    st.close()

    print("3/10 化学计算 …")
    check(chem.load("CCO") is not None, "SMILES 解析失败")
    check(chem.load("THF") is not None, "溶剂简写没生效")
    if hasattr(Chem, "MolFromInchi"):
        check(chem.load("InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3") is not None,
              "InChI 解析失败")
    info = chem.analyze("c1ccccc1")
    check(info.get("formula") == "C6H6", f"苯的分子式算错了：{info.get('formula')}")
    check(abs(info["mw"] - 78.11) < 0.05, "苯的分子量算错了")
    check("V2000" in info["molfile"], "molfile 没生成")
    check(info["rings"] == 1, "环数算错了")
    check("error" in chem.analyze("这不是SMILES%%%"), "非法 SMILES 本该报错")
    img = chem.render(Chem.MolFromSmiles("c1ccccc1"), 200, 160)
    check(img is not None and img.size == (200, 160), "结构图渲染失败")
    check(chem.render_smiles("CCO") is not None, "SMILES 直接渲染失败")
    check(chem.render_smiles("%%%bad") is None, "非法结构本该不画图")

    # 用临时库剩下的苯药剂做结构检索（乙酸乙酯已删）
    st2 = store.Store(db)
    records = st2.all_molfiles()
    hits = chem.substructure_hits("c1ccccc1", records)
    check(sid_benzene in hits, "苯环子结构没命中苯")
    hits2 = chem.substructure_hits("[#6]=O", records)
    check(hits2 == [], "苯里不该有羰基")
    sim = chem.similarity_hits("c1ccccc1", records, 0.1)
    check(sim and sim[0][0] == sid_benzene and sim[0][1] > 0.9,
          "自相似的 Tanimoto 应该接近 1")
    check(all(sim[i][1] >= sim[i + 1][1] for i in range(len(sim) - 1)),
          "相似性结果没按分数降序")
    check(chem.substructure_hits("%%bad", records) == [], "非法 SMARTS 应返回空")
    st2.close()

    print("3b/10 组成双向实时计算 …")
    import stoich as st

    def R(cid, role, name, mw, eq=None, amount=None, unit="g", actual=None):
        return {"id": cid, "role": role, "s_name": name, "label": None,
                "s_mw": mw, "equivalents": eq, "amount": amount,
                "unit": unit, "actual": actual}

    rows = [R(1, "反应物", "苯甲醛", 106.12, 1.0, 5.0, "g"),
            R(2, "试剂", "NaClO2", 90.44, 1.2, 6.0, "g"),
            R(3, "催化剂", "TEMPO", 156.25, 0.05, None, "g"),
            R(4, "产物", "苯甲酸", 122.12, 1.0, None, "g"),
            R(5, "溶剂", "乙腈", 41.05, None, 20.0, "mL")]
    mmol1 = st.row_mmol(rows[0])
    check(abs(mmol1 - 47.116) < 0.05, f"苯甲醛摩尔量算错：{mmol1}")
    check(abs(st.row_mmol(rows[4]) or 0) == 0, "体积单位没有分子量不该算出摩尔量")

    # 改用量（双向之一）：其它行按当量反推所需用量
    ups, note = st.recalc([dict(r) for r in rows], 1, "amount")
    check(note == "", f"改用量重算不该报错：{note}")
    u2 = dict(ups).get(2)
    check(u2 and abs(u2["amount"] - mmol1 * 1.2 * 90.44 / 1000) < 0.01,
          f"NaClO2 所需量没按当量反推：{u2}")
    u3 = dict(ups).get(3)
    check(u3 and abs(u3["amount"] - round(mmol1 * 0.05 * 156.25 / 1000, 2)) < 0.005,
          f"TEMPO 所需量没按当量反推：{u3}")
    check(5 not in dict(ups), "溶剂不该被双向计算改写")

    # 用量填了、当量空着 → 逆算当量
    rows2 = rows + [R(6, "试剂", "NaH2PO2", 85.99, None, 2.0, "g")]
    ups2, _ = st.recalc([dict(r) for r in rows2], 1, "amount")
    eq6 = dict(ups2).get(6, {}).get("equivalents")
    check(eq6 and abs(eq6 - (2.0 / 85.99 * 1000) / mmol1) < 0.01,
          f"没填当量的行没被逆算出当量：{eq6}")

    # 改当量（双向之二）：按基准摩尔量直接算该行用量
    rows3 = [dict(r) for r in rows]
    rows3[1]["amount"] = None
    ups3, note3 = st.recalc(rows3, 2, "equiv")
    check(note3 == "", f"改当量重算不该报错：{note3}")
    a3 = ups3[0][1]["amount"]
    check(abs(a3 - mmol1 * 1.2 * 90.44 / 1000) < 0.01,
          f"改当量后没算出所需用量：{a3}")
    _, note4 = st.recalc([dict(r) for r in rows], 5, "equiv")
    check("溶剂" in note4, "改溶剂当量应该被拒绝")

    # 限量试剂与理论产量、实际产率
    lim = st.limiting_row([dict(r) for r in rows])
    check(lim and lim["id"] == 1, "限量试剂应该是苯甲醛")
    rep = st.yield_report([dict(r) for r in rows])
    check(len(rep["items"]) == 1, "产物报告应该只有苯甲酸一条")
    it = rep["items"][0]
    check(abs(it["theo_g"] - mmol1 * 122.12 / 1000) < 0.05,
          f"理论产量算错：{it['theo_g']}")
    check(it["pct"] is None, "没填实测不该有产率")
    rows4 = [dict(r) for r in rows]
    rows4[3]["actual"] = 4.6
    rep4 = st.yield_report(rows4)
    check(abs(rep4["pct"] - 79.9) < 1.0, f"实际产率算错：{rep4['pct']}")
    s = st.summary_text(rows4, rep4)
    check("基准" in s and "理论" in s and "%" in s, f"汇总行缺关键词：{s}")

    # 实测输入解析
    g, u, err = st.actual_to_g("500 mg")
    check(g == 0.5 and err == "", f"500 mg 应折成 0.5 g：{g} {err}")
    g2, _, err2 = st.actual_to_g("2 mL")
    check(g2 is None and err2, "体积单位该被拒绝")
    g3, _, _ = st.actual_to_g("")
    check(g3 is None, "空输入返回 None")

    # 数据库有 actual 列且能写
    st3 = store.Store(db)
    cols3 = {r["name"] for r in st3.q("PRAGMA table_info(reaction_components)")}
    check("actual" in cols3, "reaction_components 缺 actual 列")
    st3.close()

    print("3c/10 记录导出 PDF / DOCX …")
    try:
        import recexport
        have_pdf = have_docx = True
        try:
            import fpdf  # noqa: F401
        except ImportError:
            have_pdf = False
        try:
            import docx  # noqa: F401
        except ImportError:
            have_docx = False
        st4 = store.Store(db)
        c0e = st4.add_collection("导出自检")
        s1 = st4.add_sample(collection_id=c0e, name="自检药剂", smiles="CCO")
        st4.update_sample(s1, code="S-T", mw=chem.analyze("CCO")["mw"])
        r1 = st4.add_reaction(collection_id=c0e, title="自检反应")
        st4.update_reaction(r1, procedure="步骤一\n步骤二")
        st4.add_component(r1, sample_id=s1, role="反应物",
                          equivalents=1.0, amount=2.0, unit="g")
        g1 = recexport.gather(st4, "sample", s1)
        check(g1 is not None and g1["title"] == "自检药剂", "药剂 gather 失败")
        check(g1["image_png"] is not None, "药剂结构图没渲染")
        check(g1["image_svg"] and "<svg" in g1["image_svg"], "药剂结构 SVG 没生成")
        g2 = recexport.gather(st4, "reaction", r1)
        check(g2 is not None and g2["comps"] is not None, "反应 gather 缺组成表")
        check(len(g2["comps"]["rows"]) == 1, "反应组成行数不对")
        # 数值容错：文本型的当量/用量不该崩，还能算摩尔量
        st4.update_component(st4.components(r1)[0]["id"],
                             amount="2.0 g", equivalents="1")
        g3 = recexport.gather(st4, "reaction", r1)
        check(g3["comps"]["rows"][0][3] == "2.0 g", f"文本用量显示不对：{g3['comps']['rows'][0]}")
        check(g3["comps"]["rows"][0][4] not in ("", "—"),
              "文本型用量没算出摩尔量")
        # 矢量反应式拼图
        st4.add_drawing("reaction", r1, title="式", kind="scheme",
                        smiles="CCO>>CC(=O)O", data="{}")
        g4 = recexport.gather(st4, "reaction", r1)
        check(g4["image_svg"] and g4["image_svg"].count("<g transform") == 2
              and "line" in g4["image_svg"], "反应式 SVG 拼图不对")
        outd = os.path.join(tmp_dir(), "eln-exp-selfcheck")
        os.makedirs(outd, exist_ok=True)
        if have_pdf:
            p = recexport.build_pdf(g4, os.path.join(outd, "t.pdf"))
            check(os.path.getsize(p) > 5000, "PDF 太小，可能没写出内容")
            import pymupdf
            d = pymupdf.open(p)
            n_vec = len(d[0].get_drawings())
            check(n_vec > 5, f"PDF 里结构式不是矢量（矢量对象 {n_vec} 个）")
            d.close()
        else:
            print("  [跳过] 未装 fpdf2，PDF 导出测试略过")
        if have_docx:
            p = recexport.build_docx(g2, os.path.join(outd, "t.docx"))
            check(os.path.getsize(p) > 5000, "DOCX 太小，可能没写出内容")
        else:
            print("  [跳过] 未装 python-docx，DOCX 导出测试略过")
        check(hasattr(recexport, "build_pdf") and hasattr(recexport, "build_docx"),
              "recexport 缺 builder")
        st4.close()
    except Exception as e:
        check(False, f"记录导出模块异常：{type(e).__name__}: {e}")

    print("3d/10 模板 · FTS5 · 日历 · 打包导出 …")
    import packexport
    import calwin  # noqa: F401  只验证模块可导入（窗口逻辑跑不了无显示环境）
    st5 = store.Store(db)
    check(getattr(st5, "fts", False), "FTS5 索引没建起来")
    c5 = st5.add_collection("3d 冒烟")
    s5 = st5.add_sample(collection_id=c5, name="对硝基苯酚", note="避光保存")
    r5 = st5.add_reaction(collection_id=c5, title="硝化反应", conditions="冰浴")
    st5.add_component(r5, sample_id=s5, role="反应物", equivalents=1.0,
                      amount=3.0, unit="g")
    st5.add_block("reaction", r5, "text", "滴加要慢，内温别超 10 度", 0)
    # FTS5：命中 / 前缀 / 多词 / 笔记 / 更新同步 / 不命中
    check([r["id"] for r in st5.samples(keyword="硝基")] == [s5],
          "FTS5 药剂没命中")
    check([r["id"] for r in st5.reactions(keyword="硝化")] == [r5],
          "FTS5 反应没命中")
    check([r["id"] for r in st5.reactions(keyword="滴加要慢")] == [r5],
          "FTS5 笔记块没命中")
    check([r["id"] for r in st5.reactions(keyword="滴加要慢 10")] == [r5],
          "FTS5 多词笔记查询没生效")
    check([r["id"] for r in st5.samples(keyword="对硝")] == [s5],
          "FTS5 前缀匹配没生效")
    check(st5.samples(keyword="查不到的东西xyz") == [], "FTS5 不该乱命中")
    st5.update_reaction(r5, title="重氮化反应")
    check([r["id"] for r in st5.reactions(keyword="重氮")] == [r5] and
          [r["id"] for r in st5.reactions(keyword="硝化反应")] == [],
          "FTS5 索引没跟着 UPDATE 同步")
    # 模板 CRUD
    tid = st5.add_template("硝化模板", json.dumps(
        {"title": "硝化反应", "conditions": "冰浴",
         "components": [{"sample_id": s5, "label": "", "role": "反应物",
                         "equivalents": 1.0, "amount": None, "unit": "g"}]},
        ensure_ascii=False))
    trow = st5.one("SELECT * FROM templates WHERE id=?", (tid,))
    check(trow is not None and json.loads(trow["content"])["title"] == "硝化反应",
          "模板存取失败")
    check(len(st5.templates("reaction")) == 1, "模板列表不对")
    st5.update_template(tid, name="硝化模板 v2")
    check(st5.one("SELECT name FROM templates WHERE id=?",
                  (tid,))["name"] == "硝化模板 v2", "模板改名失败")
    st5.delete_template(tid)
    check(st5.templates("reaction") == [], "模板删除失败")
    # 打包导出
    outd2 = os.path.join(tmp_dir(), "eln-pack-selfcheck")
    os.makedirs(outd2, exist_ok=True)
    pm = packexport.export_md_zip(st5, os.path.join(outd2, "coll.zip"),
                                  coll_id=c5)
    check(pm == 2, f"集合 Markdown 包该有 2 条：{pm}")
    pe = packexport.export_eln_zip(st5, os.path.join(outd2, "all.eln"),
                                   coll_id=c5, root_name="自检库")
    check(pe == 2, f"集合 .eln 该有 2 条：{pe}")
    p1m = packexport.export_md_zip(st5, os.path.join(outd2, "one.zip"),
                                   owner_type="reaction", oid=r5)
    check(p1m == 1 and os.path.getsize(os.path.join(outd2, "one.zip")) > 500,
          "单条 Markdown 包没写出内容")
    z = zipfile.ZipFile(os.path.join(outd2, "all.eln"))
    meta = json.loads(z.read("自检库/ro-crate-metadata.json"))
    g0 = meta["@graph"][0]
    check(g0["@id"] == "ro-crate-metadata.json" and
          any(c["@id"] == "https://w3id.org/ro/crate/1.1"
              for c in g0["conformsTo"]), "ro-crate 清单结构不对")
    check(len(meta["@graph"][1]["hasPart"]) == 2, "根实体 hasPart 数不对")
    mds = [n for n in z.namelist() if n.endswith("record.md")]
    check(len(mds) == 2, "record.md 数量不对")
    md_head = z.read(mds[0]).decode("utf-8")[:4]
    check(md_head == "---\n", "Markdown frontmatter 没生成")
    st5.close()

    print("4/10 导入导出与命令行 …")
    st3 = store.Store(db)
    rows = [r for r in st3.samples() if r["molfile"]]
    sdf = os.path.join(tmp, "eln_selfcheck.sdf")
    check(chem.write_sdf(sdf, rows) == len(rows), "SDF 写出条数不对")
    back = chem.read_sdf(sdf)
    check(len(back) == len(rows), "SDF 读回条数不对")
    check(back and back[0]["formula"] == "C6H6", "SDF 往返丢了分子式")
    csv_path = os.path.join(tmp, "eln_selfcheck.csv")
    check(cli.cmd_export_csv(st3, Namespace(path=csv_path, collection=None)) == 0,
          "CSV 导出异常")
    with open(csv_path, "rb") as fh:
        raw = fh.read()
    check(raw.startswith(b"\xef\xbb\xbf"), "CSV 缺 UTF-8 BOM，Excel 会乱码")
    head = raw.decode("utf-8-sig").splitlines()[0]
    check("分子式" in head and head.startswith("ID"), "CSV 表头不对")
    st3.close()

    py = sys.executable
    def run(*args):
        return subprocess.run([py, "cli.py", "--db", db, *args], cwd=HERE,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
    r = run("stats")
    check(r.returncode == 0 and "药剂" in r.stdout, f"cli stats 失败：{r.stderr}")
    r = run("list", "--kind", "samples")
    check(r.returncode == 0 and "苯" in r.stdout, "cli list 药剂失败")
    r = run("find", "c1ccccc1", "--mode", "sub")
    check(r.returncode == 0 and "命中 1 个药剂" in r.stdout,
          f"cli find 子结构失败：{r.stdout}")
    r = run("find", "苯", "--mode", "text")
    check(r.returncode == 0 and "苯" in r.stdout, "cli find 文本失败")
    r = run("add-sample", "自检乙醇", "--smiles", "CCO")
    check(r.returncode == 0 and "C2H6O" in r.stdout,
          f"cli add-sample 失败：{r.stdout} {r.stderr}")
    r = run("export-sdf", os.path.join(tmp, "eln_selfcheck_cli.sdf"))
    check(r.returncode == 0 and "写出" in r.stdout, "cli export-sdf 失败")
    r = run("backup", os.path.join(tmp, "eln_selfcheck_cli_bak.db"))
    check(r.returncode == 0 and os.path.exists(os.path.join(tmp, "eln_selfcheck_cli_bak.db")),
          "cli backup 失败")

    print("5/10 绘制区 …")
    from rdkit.Chem import rdChemReactions

    sk = drawpad.Sketch()
    sk.example_benzene()
    smi, err = sk.smiles()
    check(smi == "c1ccccc1", f"苯环没转成 SMILES：{smi} {err}")
    check(err == "", "苯环不该报错")
    check(len(sk.atoms) == 6 and len(sk.bonds) == 6, "苯环原子/键数不对")
    check(len(sk.fragments()) == 1, "苯环应是单一连通分量")
    check(drawpad.Sketch.from_json(sk.to_json()).smiles()[0] == "c1ccccc1",
          "JSON 往返后 SMILES 变了")
    block, e_mol = sk.molfile()
    check(bool(block) and e_mol == "", "molfile 生成失败")
    check(bool(block) and Chem.MolFromMolBlock(block) is not None, "molfile 读不回来")
    check(sk.render_png(320, 200).size == (320, 200), "PNG 尺寸不对")

    rx = drawpad.Sketch()
    rx.example_reaction()
    rsmi, e_rxn = rx.smiles()
    check(">>" in rsmi and "O=Cc1ccccc1" in rsmi, f"反应 SMILES 不对：{rsmi}")
    check(e_rxn == "", "示例反应式不该报错")
    left, right, agents = rx.split_scheme()
    check(len(left) == 1 and len(right) == 1, "箭头分组不对")
    check(any("KMnO4" in a for a in agents), "试剂文字没识别")
    rxn_text, e_file = rx.rxnfile()
    check(rxn_text.startswith("$RXN") and "$MOL" in rxn_text and e_file == "",
          "RXN 文件生成失败")
    rxn_path = os.path.join(tmp, "eln_selfcheck.rxn")
    with open(rxn_path, "w", encoding="utf-8") as fh:
        fh.write(rxn_text)
    reaction = rdChemReactions.ReactionFromRxnFile(rxn_path)
    check(reaction is not None, "RXN 文件读不回来")
    back = drawpad.Sketch()
    back.from_rxn(reaction)
    check(">>" in back.smiles()[0], "读回 RXN 后没生成反应 SMILES")

    # CDXML：反应式交给 ChemDraw 的主格式，箭头和试剂文字都要带上
    cd_text, e_cd = rx.cdxmlfile()
    check(cd_text.startswith("<?xml") and "<arrow" in cd_text
          and "KMnO4" in cd_text and "室温" in cd_text and e_cd == "",
          "CDXML 导出失败，或丢了箭头 / 试剂文字")
    cd_path = os.path.join(tmp, "eln_selfcheck.cdxml")
    with open(cd_path, "w", encoding="utf-8") as fh:
        fh.write(cd_text)
    from structure import parse_cdxml
    m_cd, _notes_cd, _marks_cd = parse_cdxml(cd_path)
    smi_cd = Chem.MolToSmiles(m_cd) if m_cd is not None else ""
    check("O=Cc1ccccc1" in smi_cd and "O=C(O)c1ccccc1" in smi_cd,
          f"CDXML 读回的分子不对：{smi_cd}")
    check(drawpad.Sketch().cdxmlfile()[1] != "", "空画布导出 CDXML 该报错")
    ab_cd_sk = drawpad.Sketch()
    _ax1 = ab_cd_sk.add_atom("O", 100, 100, "OBz")
    _ax2 = ab_cd_sk.add_atom("C", 160, 100)
    ab_cd_sk.add_bond(_ax1, _ax2)
    ab_cd, ab_cd_err = ab_cd_sk.cdxmlfile()
    check(ab_cd_err == "" and "OBz" in ab_cd, "CDXML 没带缩写基团")

    # 读回取景：缩放跟画布尺寸走，离结构很远的孤立箭头要跳过
    fb_sk = drawpad.Sketch()
    fb_data = {
        "atoms": [{"id": 1, "sym": "C", "p": (100.0, 100.0)},
                  {"id": 2, "sym": "C", "p": (114.4, 100.0)}],
        "bonds": [{"B": 1, "E": 2, "order": 1}],
        "arrows": [{"x1": 0.0, "y1": 0.0, "x2": 50.0, "y2": 0.0}],
        "labels": []}
    ok_fb = fb_sk.from_cdxml(fb_data, width=900, height=600)
    check(ok_fb and len(fb_sk.arrows) == 0 and fb_sk.skipped_objects == 1,
          "读回没跳过离结构很远的孤立箭头")
    _dl = ((fb_sk.atoms[0]["x"] - fb_sk.atoms[1]["x"]) ** 2
           + (fb_sk.atoms[0]["y"] - fb_sk.atoms[1]["y"]) ** 2) ** 0.5
    check(_dl > 40, f"读回取景太小（键长只有 {_dl:.0f} px，画板标准是 46）")

    # 原子属性：电荷 / 同位素
    check(drawpad.parse_atom_attrs("N+") == ("N", "", 1, 0), "N+ 解析不对")
    check(drawpad.parse_atom_attrs("O-") == ("O", "", -1, 0), "O- 解析不对")
    check(drawpad.parse_atom_attrs("S2+") == ("S", "", 2, 0), "S2+ 解析不对")
    check(drawpad.parse_atom_attrs("13C") == ("C", "", 0, 13), "13C 解析不对")
    check(drawpad.parse_atom_attrs("OBz") == ("O", "OBz", 0, 0), "OBz 解析不对")
    ch_sk = drawpad.Sketch()
    c_at = ch_sk.add_atom("C", 100, 100)
    o_at = ch_sk.add_atom("O", 140, 100)
    o2_at = ch_sk.add_atom("O", 100, 140, charge=-1)
    ch_sk.add_bond(c_at, o_at, 2)
    ch_sk.add_bond(c_at, o2_at, 1)
    check("[O-]" in ch_sk.smiles()[0], f"电荷没进 SMILES：{ch_sk.smiles()[0]}")
    check("M  CHG" in ch_sk.molfile()[0], "molfile 没写电荷")
    check('Charge="-1"' in ch_sk.cdxmlfile()[0], "CDXML 没写电荷")
    check(ch_sk.atom_display(ch_sk.atom(o2_at)) == "O-", "电荷显示不对")
    check(ch_sk.atom_shows_text(ch_sk.atom(c_at)) is False, "普通碳不该显示文字")
    c_charged = ch_sk.add_atom("C", 200, 200, charge=1)
    check(ch_sk.atom_shows_text(ch_sk.atom(c_charged)), "带电荷的碳要显示文字")

    # 文字 / 箭头对象：id 机制（旧数据要能补 id）
    lsk = drawpad.Sketch()
    lid = lsk.add_label(100, 100, "试剂")
    aid = lsk.add_arrow(10, 10, 60, 10)
    check(lsk.label_by_id(lid) is not None
          and lsk.label_by_id(lid)["text"] == "试剂", "文字 id 找不到")
    check(lsk.arrow_by_id(aid) is not None, "箭头 id 找不到")
    old_sk = drawpad.Sketch.from_dict({"mode": "scheme", "atoms": [], "bonds": [],
                                      "labels": [{"x": 1, "y": 2, "text": "旧"}],
                                      "arrows": [], "roles": {}})
    check(old_sk.labels[0].get("id"), "旧数据没补 id")
    check(drawpad.Sketch.from_dict(old_sk.to_dict()).labels[0].get("id")
          == old_sk.labels[0]["id"], "id 往返后变了")
    check(lsk.label_hit(lsk.label_by_id(lid), 100, 100, 10)
          and not lsk.label_hit(lsk.label_by_id(lid), 300, 100, 10), "文字命中判定不对")
    check(lsk.arrow_hit(lsk.arrow_by_id(aid), 35, 10, 8), "箭头命中判定不对")

    sm = drawpad.Sketch()
    check(sm.from_smiles("CCO") and sm.smiles()[0] == "CCO", "载入 SMILES 失败")
    bad = drawpad.Sketch()
    c0 = bad.add_atom("C", 100, 100)
    for k in range(5):
        a = bad.add_atom("C", 100 + 40 * (k + 1), 100)
        bad.add_bond(c0, a, 1)
    check(bad.smiles()[0] == "" and bad.smiles()[1] != "", "五价碳本该被拒绝")

    # 缩写基团 / 视图相关
    ab = drawpad.Sketch()
    ax1 = ab.add_atom("O", 100, 100, "OBz")
    ax2 = ab.add_atom("C", 160, 100)
    ab.add_bond(ax1, ax2)
    check(ab.abbrev_count() == 1, "缩写原子没被统计到")
    check(ab.smiles()[0].count("*") == 1, "缩写原子该按 * 参与 SMILES")
    check(drawpad.Sketch.from_json(ab.to_json()).abbrev_count() == 1,
          "缩写没随 JSON 保存")
    check(drawpad.parse_atom_text("OBz") == ("O", "OBz"), "OBz 解析不对")
    check(drawpad.parse_atom_text("CH2OBz") == ("C", "CH2OBz"), "CH2OBz 解析不对")
    check(drawpad.parse_atom_text("Cl") == ("Cl", ""), "Cl 该识别为纯元素")
    check(drawpad.parse_atom_text("Ph") == ("C", "Ph"), "Ph 该识别为缩写")
    check(drawpad.parse_atom_text("Ac") == ("C", "Ac"), "Ac 该按乙酰基而不是锕")
    ab_block, ab_err = ab.molfile()
    check(ab_err == "" and "A    1" in ab_block and "OBz" in ab_block,
          "molfile 没带缩写别名（ChemDraw 里会显示成 *）")
    bx0, by0, bx1, by1 = ab.bounds()
    check(bx1 - bx0 > 0 and by1 - by0 > 0, "内容包围盒算错了")
    check(ab.render_png(240, 160).size == (240, 160), "缩写图导出尺寸不对")
    check(drawpad.Sketch().render_png(200, 120).size == (200, 120),
          "空图画布导出会崩")

    # 反应角色与自动布局
    rc = drawpad.Sketch(mode="scheme")
    ra = rc.add_atom("C", 100, 100)
    rb = rc.add_atom("C", 140, 100)
    rc.add_bond(ra, rb)
    pc = rc.add_atom("C", 500, 100)
    rc.arrows.append({"x1": 220, "y1": 100, "x2": 300, "y2": 100})
    rc.set_role(rc.fragment_at(ra), drawpad.ROLE_REACTANT)
    rc.set_role(rc.fragment_at(pc), drawpad.ROLE_PRODUCT)
    check(rc.fragment_role(rc.fragment_at(ra)) == drawpad.ROLE_REACTANT,
          "角色没记到片段上")
    groups = rc.reaction_groups()
    check(len(groups[drawpad.ROLE_REACTANT]) == 1
          and len(groups[drawpad.ROLE_PRODUCT]) == 1, "按角色分组不对")
    rc.layout_reaction()
    b_r = rc._frag_bbox(rc.fragment_at(ra))
    b_p = rc._frag_bbox(rc.fragment_at(pc))
    check(b_r[2] < rc.arrows[0]["x1"], "反应物没排到箭头左侧")
    check(b_p[0] > rc.arrows[0]["x2"], "产物没排到箭头右侧")
    check(rc.smiles()[0] == "CC>>C", f"按角色生成的反应 SMILES 不对：{rc.smiles()}")
    ca = rc.add_atom("C", 240, 20)
    rc.set_role(rc.fragment_at(ca), drawpad.ROLE_CATALYST)
    rc.layout_reaction()
    b_c = rc._frag_bbox(rc.fragment_at(ca))
    check(b_c[3] < rc.arrows[0]["y1"], "催化剂没排到箭头上方")
    check(rc.smiles()[0] == "CC>>C", "催化剂不该进 >> 两侧")
    check(any("C" == a for a in rc.split_scheme()[2]), "催化剂没算进条件")
    check(drawpad.Sketch.from_json(rc.to_json()).roles == rc.roles,
          "角色没随 JSON 保存")
    rc.remove_atom(ca)
    check(str(ca) not in rc.roles, "删原子后角色没清理")

    # 清除：框选删除与一键清除
    cl = drawpad.Sketch(mode="scheme")
    k1 = cl.add_atom("C", 100, 100)
    k2 = cl.add_atom("C", 140, 100)
    cl.add_bond(k1, k2)
    k3 = cl.add_atom("C", 400, 100)
    cl.labels.append({"x": 300, "y": 100, "text": "中间"})
    cl.set_role(cl.fragment_at(k1), drawpad.ROLE_REACTANT)
    cl.set_role(cl.fragment_at(k3), drawpad.ROLE_PRODUCT)
    n_hit = cl.erase_rect(60, 60, 200, 160)
    check(n_hit == 2, f"框选应删掉 2 个原子，实际 {n_hit}")
    check(len(cl.atoms) == 1 and cl.atoms[0]["x"] == 400, "框选删错了范围")
    check(len(cl.bonds) == 0, "框内原子的键没跟着删")
    check(len(cl.labels) == 1, "框外的文字被误删")
    check(len(cl.roles) == 1, "被删片段的角色没清理")
    check(cl.erase_rect(2000, 2000, 2100, 2100) == 0, "空中框选不该删东西")
    n_lab = cl.erase_rect(250, 60, 350, 140)
    check(n_lab == 1 and not cl.labels, "框选没删掉文字")
    cl.clear_all()
    check(not cl.atoms and not cl.bonds and not cl.labels
          and not cl.arrows and not cl.roles, "一键清除没清干净")

    # 新建反应式画布自带箭头；多反应物横向排开并水平对齐
    nc = drawpad.Sketch()
    nc.new_reaction_canvas()
    check(len(nc.arrows) == 1 and nc.arrows[0]["x2"] > nc.arrows[0]["x1"],
          "新建反应式画布没有默认箭头")
    r_ids = []
    for k, smi_k in enumerate(("CCO", "CC(=O)O", "O")):
        b = len(nc.atoms)
        nc.from_smiles(smi_k, 100 + 200 * k, 250)
        r_ids.append(nc.atoms[b]["id"])
    for i in r_ids:
        nc.set_role(nc.fragment_at(i), drawpad.ROLE_REACTANT)
    nc.layout_reaction()
    boxes = [nc._frag_bbox(nc.fragment_at(i)) for i in r_ids]
    centers = {round((b[1] + b[3]) / 2) for b in boxes}
    check(len(centers) == 1, "多个反应物没有水平对齐")
    check(boxes[0][0] < boxes[1][0] < boxes[2][0], "反应物没按加入顺序从左往右排")
    check(boxes[2][2] < nc.arrows[0]["x1"], "最后一个反应物没紧贴箭头左侧")
    check(nc.bounds(0)[0] >= 0 and nc.bounds(0)[1] >= 0, "排版后出现负坐标")

    st5 = store.Store(db)
    tables5 = {r["name"] for r in st5.q(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    check("drawings" in tables5, "缺 drawings 表")

    # 定稿锁定：字段、置位、解锁后不留时间戳
    for tbl in ("samples", "reactions"):
        cols = {r["name"] for r in st5.q(f"PRAGMA table_info({tbl})")}
        check("locked" in cols and "locked_at" in cols, f"{tbl} 缺锁定字段")
    check(not st5.is_locked("sample", sid_benzene), "新记录不该是锁定状态")
    st5.set_locked("sample", sid_benzene, True)
    check(st5.is_locked("sample", sid_benzene), "定稿没写进库")
    check(bool(st5.locked_at("sample", sid_benzene)), "定稿时间没记录")
    st5.set_locked("sample", sid_benzene, False)
    check(not st5.is_locked("sample", sid_benzene), "解锁没生效")
    check(st5.locked_at("sample", sid_benzene) == "", "解锁后不该留定稿时间")
    did = st5.add_drawing("sample", sid_benzene, title="自检苯环",
                          kind="structure", data=sk.to_json(), smiles=smi)
    check(len(st5.drawings("sample", sid_benzene)) == 1, "绘制没写进去")
    check(st5.drawing(did)["smiles"] == "c1ccccc1", "绘制 SMILES 不对")
    st5.update_drawing(did, title="改名")
    check(st5.drawing(did)["title"] == "改名", "绘制更新失败")
    check(st5.stats()["drawings"] >= 1, "stats 没统计绘制")
    r = run("drawings")
    check(r.returncode == 0 and "改名" in r.stdout, "cli drawings 失败")
    st5.delete_sample(sid_benzene)
    check(st5.drawings("sample", sid_benzene) == [], "删药剂没级联删绘制")
    st5.close()

    # ---------------- Ketcher 编辑器（可选增强，未构建则跳过） ----------------
    import ketcherwin
    if ketcherwin.is_built():
        import threading
        import urllib.request
        ksrv = ketcherwin._Server(("127.0.0.1", 0), ketcherwin._Handler,
                                  {"initial": "CCO"})
        kbase = "http://127.0.0.1:%d" % ksrv.server_address[1]
        threading.Thread(target=ksrv.serve_forever, daemon=True).start()
        kpage = urllib.request.urlopen(kbase + "/", timeout=20).read().decode("utf-8")
        check("__ELN_KETCHER__" in kpage and "CCO" in kpage,
              "Ketcher 页面没把初始结构注入")
        check("/assets/" in kpage, "Ketcher 页面没引用打包后的脚本")
        kinit = json.loads(urllib.request.urlopen(kbase + "/api/init",
                                                  timeout=20).read())
        check(kinit.get("structure") == "CCO", "api/init 返回的初始结构不对")
        kreq = urllib.request.Request(
            kbase + "/api/save",
            data=json.dumps({"smiles": "CCO", "mol": "", "rxn": "",
                             "cdxml": ""}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(kreq, timeout=20).read()
        ksrv.done.wait(5)
        kgot = (ksrv.result or {}).get("data") or {}
        check(kgot.get("smiles") == "CCO", "api/save 没把回写内容交出来")
        ksrv.shutdown()

    print("6/10 演示数据库 …")
    demo = os.path.join(HERE, "eln.db")
    if os.path.exists(demo):
        st4 = store.Store(demo)
        check("drawings" in {r["name"] for r in st4.q(
            "SELECT name FROM sqlite_master WHERE type='table'")},
            "演示库缺 drawings 表")
        n_s = st4.stats()["samples"]
        n_r = st4.stats()["reactions"]
        if n_s or n_r:
            check(n_s >= 4, "演示药剂太少")
            check(n_r >= 1, "演示反应太少")
        else:
            print("  [跳过] 库里还没有演示数据（空白库，首次录入后自然有）")
        for r in st4.samples():
            if r["molfile"]:
                check(Chem.MolFromMolBlock(r["molfile"], sanitize=True,
                                           removeHs=False) is not None,
                      f"药剂 {r['id']} 的 molfile 解析不了")
        for c in st4.q("SELECT * FROM reaction_components WHERE sample_id IS NOT NULL"):
            check(st4.sample(c["sample_id"]) is not None,
                  f"组成 {c['id']} 指向了不存在的药剂")
        st4.close()
    else:
        print("  [跳过] 干净源码包还没有 eln.db（首次启动会生成空库）")

    print("7/10 交付文件 …")
    for name in ("store.py", "chem.py", "gui.py", "dialogs.py", "cli.py",
                 "drawpad.py", "notebook.py", "effects.py", "effectswin.py",
                 "helpwin.py", "MANUAL.md", "make_icon.py",
                 "make_shortcut.py", "selfcheck.py",
                 "auth.py", "loginwin.py", "paths.py", "polarity.py",
                 "polaritywin.py", "structure.py", "engine.py", "hybrid.py",
                 "groups.py", "ext.py", "caslookup.py",
                 "README.md", "Start.bat", "自检.bat", "requirements.txt",
                 "assets/app.ico", "assets/icon_preview.png",
                 "assets/screenshot.png", "assets/help.png",
                 "assets/drawpad.png", "assets/effects.png",
                 "assets/notebook.png", "assets/notebook-html.png"):
        check(os.path.exists(os.path.join(HERE, name)), f"缺文件 {name}")
    # 运行期生成物：首次启动 / 建快捷方式后才有，干净源码包里没有不算失败
    for name in ("eln.db", "ELN.lnk"):
        if os.path.exists(os.path.join(HERE, name)):
            check(True, "")
        else:
            print(f"  [跳过] {name} 还没有（首次启动或建快捷方式后生成）")
    check(os.path.getsize(os.path.join(HERE, "assets", "app.ico")) > 1000,
          "图标文件太小，可能没生成对")
    with open(os.path.join(HERE, "gui.py"), encoding="utf-8") as fh:
        gui_src = fh.read()
    check("reaction_ids_by_samples" in gui_src, "GUI 没用上关联反应查询")

    print("8/10 手册与帮助入口 …")
    secs = helpwin.parse_manual()
    check(len(secs) >= 16, f"手册章节太少：{len(secs)}")
    check(any("绘制区" in s["title"] for s in secs), "手册缺绘制区章节")
    check(any("电子效应" in s["title"] for s in secs), "手册缺电子效应章节")
    check(any("实验笔记" in s["title"] for s in secs), "手册缺实验笔记章节")
    check(all(s["title"] and s["lines"] for s in secs), "手册里有空章节")
    check(all(not s["title"].startswith("#") for s in secs), "章节标题没拆干净")
    manual_text = "\n".join(helpwin.plain(s) for s in secs)
    for kw in ("F1", "Ctrl+N", "Ctrl+E", "子结构", "相似性", "导出 SDF", "备份",
               "attachments/", "组成", "SMARTS", "命令行",
               "ChemDraw", "绘制区", "快捷方式", "rxn",
               "基团电子效应判断器", "效应引擎", "--query", "σp",
               "实验笔记", "Ctrl+Shift+B", "mw(", "Pygments",
               "账户登录", "30 天", "数据隔离", "找回密码", "PBKDF2"):
        check(kw in manual_text, f"手册缺关键内容：{kw}")
    page = helpwin.build_html(secs)
    check(page.count("<h2>") == len(secs), "导出网页的章节数对不上")
    check("<h1>ELN 用户手册</h1>" in page, "导出网页标题不对")
    check("<pre><code>" in page, "导出网页丢了代码块")
    with open(os.path.join(HERE, "helpwin.py"), encoding="utf-8") as fh:
        hw_src = fh.read()
    check("tempfile.gettempdir" not in hw_src,
          "导出网页不该写进系统临时目录（约定走 D:/Temp/agent 或项目目录）")
    check(hasattr(gui.App, "on_help"), "GUI 没有帮助入口方法")
    check("<F1>" in gui_src, "没绑 F1")
    check("helpwin.open_help" in gui_src, "帮助按钮没接手册窗口")
    check(callable(helpwin.open_help), "helpwin.open_help 不可用")

    # 手册里的 Markdown 表格：帮助窗口要按表格画，导出 HTML 要出 <table>
    h_secs = helpwin.parse_manual()
    check(len(h_secs) >= 17, f"手册章节少了：{len(h_secs)}")
    h_html = helpwin.build_html(h_secs)
    check("<table>" in h_html and "<th>" in h_html, "手册导出 HTML 没有表格结构")
    check("<p>|" not in h_html, "手册里的表格被当成普通段落了")
    check(hasattr(helpwin.HelpWindow, "_flush_table"), "帮助窗口没有表格渲染")

    with open(os.path.join(HERE, "drawpad.py"), encoding="utf-8") as fh:
        dp_src = fh.read()
    check("win32com" not in dp_src, "画板不该走 COM 自动化")
    check("ReactionFromRxnFile" in dp_src and "MolFromMolFile" in dp_src,
          "画板缺 ChemDraw 文件读回接口")
    check(hasattr(drawpad.Sketch, "render_png")
          and hasattr(drawpad.DrawWindow, "open_chemdraw"), "画板接口不全")
    # 默认不预选工具：打开画板点画布不该凭空加碳原子
    check('self.tool = ""' in dp_src, "画板默认仍预选了工具")
    check(hasattr(drawpad.DrawWindow, "_is_select")
          and hasattr(drawpad.DrawWindow, "_sync_tool_buttons"),
          "未选工具的行为 / 按钮高亮没实现")
    check(drawpad.tool_title("") == "未选择", "空工具的状态栏文字不对")
    check("TOOL_ACTIVE_BG" in dp_src, "工具高亮色没独立于角色按钮本色")
    # 紧凑布局：撤销移到画布工具栏、窗口有最小尺寸保护
    check("command=self.undo" in dp_src and "tbtn(\"撤销 Ctrl+Z\"" not in dp_src,
          "撤销按钮没从左栏挪到画布工具栏")
    check("minsize(" in dp_src, "画板缺最小窗口尺寸保护")
    # 提示折叠：必须记住原始插入位置，否则收起后按钮弹不回来
    check("def _finalize_tips" in dp_src and 'kw["before"]' in dp_src,
          "用法提示没记住插回位置（收起后布局回不去）")
    check(hasattr(gui.App, "on_draw_toolbar")
          and hasattr(gui.App, "_drawing_block")
          and hasattr(gui.App, "apply_drawn_smiles"), "GUI 没接绘制区")
    check("drawpad.open_drawpad" in gui_src, "GUI 没调用画板")
    check(gui.split_rxn_pair("A.B>>C.D") == ("A", "C"), "反应 SMILES 没拆成 A/B")
    check(gui.split_rxn_pair("CCO") == ("CCO", ""), "结构式不该拆出产物")
    check(gui.split_rxn_pair("") == ("", ""), "空 SMILES 拆分不对")
    check(gui.parse_amount("2.5 g") == (2.5, "g"), "用量「2.5 g」解析不对")
    check(gui.parse_amount("2.5g") == (2.5, "g"), "用量「2.5g」解析不对")
    check(gui.parse_amount("2.5") == (2.5, "g"), "纯数字用量该默认 g")
    with open(os.path.join(HERE, "dialogs.py"), encoding="utf-8") as fh:
        dl_src = fh.read()
    check("on_draw" not in dl_src and '"画"' not in dl_src,
          "药剂对话框仍残留「画」入口（已按要求移除）")
    check('"解析"' in dl_src, "药剂对话框缺「解析」按钮")
    with open(os.path.join(HERE, "make_shortcut.py"), encoding="utf-8") as fh:
        ms_src = fh.read()
    check("desktop_dir" in ms_src and "IconLocation" in ms_src,
          "快捷方式脚本不完整")
    if os.path.exists(os.path.join(HERE, "ELN.lnk")):
        check(os.path.getsize(os.path.join(HERE, "ELN.lnk")) > 0, "项目内快捷方式是空文件")

    print("9/10 内置电子效应引擎与极性变化 …")
    ok_eff, why = effects.available()
    check(ok_eff, f"内置效应引擎不可用：{why}")
    if ok_eff:
        ee = effects.engine()
        check(os.path.normcase(os.path.dirname(ee.__file__))
              == os.path.normcase(HERE), "engine.py 不是 ELN 目录里的那份")
        for mod in ("engine.py", "groups.py", "hybrid.py", "structure.py", "ext.py"):
            check(os.path.isfile(os.path.join(HERE, mod)), f"缺内置引擎模块 {mod}")
        check(len(effects.catalog()) >= 40, "基团目录太少")
        rec, err = effects.analyze("硝基")
        check(rec is not None and not err, "基团查询失败")
        check(rec is not None and abs((rec["sp"] or 0) - 0.78) < 1e-6,
              "硝基 σp 值不对")
        check(rec is not None and "吸电子" in rec["cls"], "硝基方向判反了")
        check("硝基" in effects.report_text(rec), "报告没渲染出基团名")
        hits = effects.scan_molecule("Oc1ccc([N+](=O)[O-])cc1")
        keys = {h["rec"]["key"] for h in hits}
        check({"NO2", "OH"} <= keys, f"对硝基苯酚命中不对：{keys}")
        check(all(h["rec"]["key"] != "*INFERRED" for h in hits),
              "扫描结果混进了结构推断值")
        check(all(h["rec"]["key"] != "O-" for h in hits),
              "硝酰氧被误当成独立基团（子集去重生效了吗）")
        asp = effects.scan_molecule("CC(=O)Oc1ccccc1C(=O)O")
        check(any(h["rec"]["key"] == "OCOCH3" for h in asp)
              and any(h["rec"]["key"] == "COOH" for h in asp),
              "阿司匹林应命中乙酰氧基与羧基")
        check(effects.scan_molecule("c1ccccc1") == [], "苯不该凭空命中取代基")
        check(effects.scan_molecule("not-a-smiles") == [], "坏 SMILES 不该抛异常")
        check("sp" in effects.hybrid_text("CC(=O)N"), "整分子杂化清单为空")
        check(not hasattr(effects, "open_standalone"),
              "还留着独立判断器启动接口（入口应已移除）")
    with open(os.path.join(HERE, "effects.py"), encoding="utf-8") as fh:
        eff_src = fh.read()
    check("importlib.util" not in eff_src, "引擎不该再按路径动态加载")
    check("20_ElectronEffect" not in eff_src, "引擎还引用已归档的独立项目目录")
    check("sys.path.insert" not in eff_src, "适配层不该污染 sys.path")
    check("win32com" not in eff_src, "适配层不该依赖 COM")
    check(hasattr(gui.App, "on_effects")
          and hasattr(gui.App, "effects_context"), "GUI 缺电子效应入口方法")
    check("<Control-e>" in gui_src and "电子效应" in gui_src,
          "工具栏 / 快捷键没接电子效应")
    check("effectswin.open_effects" in gui_src, "GUI 没调用分析窗口")
    check("效应引擎" in gui_src, "状态栏没显示引擎状态")
    check("电子效应" in manual_text and "效应引擎" in manual_text,
          "手册缺集成操作说明")

    import polarity
    check(hasattr(gui.App, "polarity_context") and hasattr(gui.App, "on_polarity"),
          "GUI 缺极性变化入口方法")
    check("_polarity_block" in gui_src and "polaritywin.open_polarity" in gui_src,
          "详情区没接极性变化卡片")
    pr = polarity.compare("O=Cc1ccccc1", "O=C(O)c1ccccc1")
    check("error" not in pr, "极性比较失败")
    if "error" not in pr:
        check(pr["delta"]["tpsa"] > 15, "苯甲醛→苯甲酸 TPSA 增量不对")
        check(pr["score"] > 0 and "上升" in pr["verdict"], "极性方向判反了")
        check(pr["ionizable"], "羧酸没被识别成可电离基团")
        rep = polarity.format_report(pr)
        check("成因解析" in rep and "实验后果" in rep, "解析缺成因 / 后果段落")
        check("Rf" in rep and "logD" in rep, "解析缺色谱后果或 logD 局限提示")
    check("error" in polarity.compare("not-a-smiles", "CCO"), "坏 SMILES 没被拦住")
    check("极性变化" in manual_text, "手册缺极性变化说明")
    check("assets/effects.png" in open(os.path.join(HERE, "README.md"),
                                       encoding="utf-8").read(),
          "README 没放分析窗口预览")

    print("9b/10 结构文件解析与点选判定 …")
    import structure
    check(hasattr(structure, "analyze_mol"),
          "structure 缺 analyze_mol（绘制结果走不了同一分析链）")
    for fn in ("file_result", "clipboard_result", "from_smiles", "mol_result",
               "selection_result", "item_report", "item_brief", "babel_status"):
        check(callable(getattr(effects, fn, None)), f"effects 缺 {fn} 接口")
    fmts = effects.supported_formats()
    for ext in (".cdx", ".cdxml", ".mol", ".sdf"):
        check(ext in fmts, f"结构文件格式清单缺 {ext}")
    check("已就绪" in effects.babel_status() or "未装" in effects.babel_status(),
          "Open Babel 状态字符串异常")

    cdxml = os.path.join(HERE, "assets", "示例-对硝基苯酚.cdxml")
    fres = effects.file_result(cdxml)
    check(len(fres["items"]) == 2, "CDXML 示例应检出羟基与硝基")
    fnames = {effects.item_brief(i)[0].split(". ", 1)[-1] for i in fres["items"]}
    check({"羟基", "硝基"} <= fnames, f"CDXML 检出项名字不对：{fnames}")
    frep = effects.item_report(fres["items"][0], fres)
    check("σp" in frep and "所在结构" in frep and "文件" in frep,
          "文件报告缺 σ 数据或来源信息")

    dres = effects.from_smiles("Oc1ccc([N+](=O)[O-])cc1", name="自检绘制")
    check(len(dres["items"]) == 2 and dres["file"] == "自检绘制",
          "绘制结果没走同一分析链")
    dm = dres["mol"]
    nidx = next((a.GetIdx() for a in dm.GetAtoms() if a.GetSymbol() == "N"), None)
    check(nidx is not None, "绘制分子里没找到 N")
    if nidx is not None:
        picked = {nidx} | {b.GetIdx() for b in dm.GetAtomWithIdx(nidx).GetNeighbors()
                           if b.GetSymbol() == "O"}
        sit = effects.selection_result(dm, picked)
        check("硝基" in effects.item_brief(sit)[0], "点选原子没判出硝基")

    brid = effects.file_result(os.path.join(HERE, "assets",
                                            "示例-圈出亚甲二氧基.cdxml"))
    bit = next((i for i in brid["items"] if i.get("bridge")), None)
    check(bit is not None, "圈选示例没识别成桥连片段")
    if bit:
        brep = effects.item_report(bit, brid)
        check("桥连" in brep and "连接点" in brep, "桥连报告缺定性拆解")

    with open(os.path.join(HERE, "effectswin.py"), encoding="utf-8") as fh:
        ew_src = fh.read()
    for fn in ("on_open_file", "on_draw", "on_drawn", "on_clip", "on_img_click",
               "on_judge_pick", "on_reset_auto", "on_back", "_render_mol"):
        check(f"def {fn}" in ew_src, f"效应窗口缺 {fn}")
    check("before=self.report_wrap" in ew_src, "结构图没插在报告上方")
    check("pack_forget" in ew_src, "返回基团目录没隐藏结构图")
    check("drawpad.open_drawpad" in ew_src, "绘制按钮没接 ELN 画板")
    check("filedialog" in ew_src and ".cdx" in ew_src,
          "打开结构文件没接文件对话框 / cdx")
    check("结构图" in manual_text and "点选" in manual_text,
          "手册缺结构图点选说明")

    print("9c/10 账户登录与数据隔离 …")
    import auth
    import loginwin                                   # noqa: F401
    import paths                                      # noqa: F401
    check(auth.SESSION_DAYS == 30, "免登录不是 30 天")
    check(auth.PBKDF2_ITER >= 100_000, "PBKDF2 迭代次数太低")
    check(callable(paths.app_dir) and callable(paths.res_path),
          "便携路径模块缺 app_dir / res_path")

    # 全部写进临时目录，绝不碰项目里真实的 accounts.json / .session / eln.db
    atmp = tempfile.mkdtemp(prefix="eln_selfcheck_auth_")
    old = (auth.AUTH_FILE, auth.SESSION_FILE, auth.app_dir,
           store.app_dir, store._DATA_DIR)
    auth.AUTH_FILE = os.path.join(atmp, "accounts.json")
    auth.SESSION_FILE = os.path.join(atmp, ".session")
    auth.app_dir = lambda: atmp
    store.app_dir = lambda: atmp
    try:
        check(not auth.has_users(), "临时账户库应该一开始是空的")
        u1 = auth.create_user("自检甲", "alpha123")
        u2 = auth.create_user("自检乙", "beta456")
        check(u1["data_dir"] == "" and u2["data_dir"].startswith("users"),
              "首个账户沿用根目录数据，其余账户应各有独立目录")
        check(auth.verify("自检甲", "alpha123") is not None, "正确密码登录失败")
        check(auth.verify("自检甲", "wrong-pass") is None, "错误密码竟能登录")
        check(auth.recover("自检甲") == {"自检甲": "alpha123"},
              "本机明文找回不对")
        check(len(auth.recover()) == 2, "找回全部账户不对")
        with open(auth.AUTH_FILE, encoding="utf-8") as fh:
            raw = fh.read()
        check("alpha123" not in raw and "beta456" not in raw,
              "账户文件里出现了明文密码")
        check(raw.count('"hash"') == 2 and raw.count('"recover"') == 2,
              "账户文件缺登录哈希或找回密文")
        check(auth.protect(b"x").startswith(("dpapi:", "fernet:")),
              "本机密文格式不对")
        check(auth.unprotect(auth.protect(b"x")) == b"x", "本机密文往返失败")
        try:
            auth.unprotect("dpapi:" +
                           base64.b64encode(b"other-pc-blob").decode())
            check(False, "换机器的密文居然解开了")
        except auth.AuthError:
            check(True, "换机器密文解不开")
        auth.save_session("自检甲", True)
        s = auth.load_session()
        check(s is not None and s["name"] == "自检甲", "30 天会话没生效")
        check(29.9 < auth.session_days_left() <= 30.01, "会话有效期不是 30 天")
        payload = json.loads(auth.unprotect(
            open(auth.SESSION_FILE, encoding="utf-8").read()).decode())
        payload["exp"] = time.time() - 1
        with open(auth.SESSION_FILE, "w", encoding="utf-8") as fh:
            fh.write(auth.protect(json.dumps(payload).encode()))
        check(auth.load_session() is None, "过期会话没被拦住")
        auth.save_session("自检甲", False)
        check(auth.load_session() is None, "不勾免登录时仍写了会话")
        auth.clear_session()

        store.set_data_dir("")
        s1 = store.Store()
        s1.add_sample(name="仅甲可见", code="A-ONLY")
        s1.close()
        p1 = store.db_path()
        store.set_data_dir(u2["data_dir"])
        p2 = store.db_path()
        s2 = store.Store()
        s2.add_sample(name="仅乙可见", code="B-ONLY")
        names2 = [r[0] for r in s2.q("SELECT name FROM samples")]
        s2.close()
        check(p1 != p2, "两个账户用了同一个数据库文件")
        check("仅甲可见" not in names2, "账户数据没隔离")
        store.set_data_dir("")
        s3 = store.Store()
        names1 = [r[0] for r in s3.q("SELECT name FROM samples")]
        s3.close()
        check("仅乙可见" not in names1, "账户数据反向串了")
    finally:
        (auth.AUTH_FILE, auth.SESSION_FILE, auth.app_dir,
         store.app_dir, store._DATA_DIR) = old
        shutil.rmtree(atmp, ignore_errors=True)

    check("loginwin.show_login" in gui_src and "auth.load_session" in gui_src,
          "主程序没接登录窗口 / 30 天会话")
    check("auth.apply_user" in gui_src, "登录后没切换账户数据目录")
    check("def on_switch_user" in gui_src and "restart_app" in gui_src,
          "工具栏缺切换账户")
    check("--selftest" in gui_src, "便携版缺自检入口")
    with open(os.path.join(HERE, "loginwin.py"), encoding="utf-8") as fh:
        lw_src = fh.read()
    check("def on_recover" in lw_src and "RecoverDialog" in lw_src,
          "登录页缺找回密码")
    check("30 天" in lw_src and "创建账户" in lw_src,
          "登录页缺免登录选项或创建账户")
    with open(os.path.join(HERE, "README.md"), encoding="utf-8") as fh:
        rdm = fh.read()
    check("账户登录" in rdm and "30 天" in rdm,
          "README 缺账户登录说明")

    print("10/10 实验笔记 …")
    nbdb = os.path.join(tmp, "eln_selfcheck_note.db")
    if os.path.exists(nbdb):
        os.remove(nbdb)
    stn = store.Store(nbdb)
    check(set(notebook.KINDS) == {"text", "step", "chem", "table", "calc"},
          "笔记块类型不全")
    nsid = stn.add_sample(name="笔记测试样", code="S-NOTE", smiles="CCO")
    bid1 = stn.add_block("sample", nsid, "text",
                         notebook.dump_content({"md": "## 目标\n样放置 4 ℃ 冰箱"}))
    bid2 = stn.add_block("sample", nsid, "step",
                         notebook.dump_content({"title": "投料", "body": "加 2.5 g",
                                                "time": "5 min", "done": True}))
    bid3 = stn.add_block("sample", nsid, "chem",
                         notebook.dump_content({"smiles": "O=C(O)c1ccccc1",
                                                "caption": "苯甲酸"}))
    bid4 = stn.add_block("sample", nsid, "table",
                         notebook.dump_content({"cols": ["时间", "温度"],
                                                "rows": [["0 min", "3"]]}))
    bid5 = stn.add_block("sample", nsid, "calc",
                         notebook.dump_content({"expr": 'mw("O=C(O)c1ccccc1")',
                                                "result": ""}))
    rows = stn.blocks("sample", nsid)
    check([r["position"] for r in rows] == [0, 1, 2, 3, 4], "块顺序不是 0..4")
    check(len(rows) == 5, f"块数不对：{len(rows)}")
    check(stn.block_counts("sample", nsid)["calc"] == 1, "块类型计数不对")

    check(stn.move_block(bid2, -1) is True, "上移失败")
    check([r["id"] for r in stn.blocks("sample", nsid)][:2] == [bid2, bid1],
          "上移后顺序不对")
    check(stn.move_block(bid2, -1) is False, "已在最上面还能再上移")
    stn.move_block(bid2, 1)                       # 还原
    dup = stn.duplicate_block(bid2)
    check(dup is not None and stn.block(dup)["content"] == stn.block(bid2)["content"],
          "复制块没带上内容")
    stn.delete_block(dup)
    check(len(stn.blocks("sample", nsid)) == 5, "删除块后数量不对")

    # 缺字段要能补默认值，别让旧数据把界面搞崩
    stn.add_block("sample", nsid, "table", '{"cols": ["只有一列"]}')
    trow = [b for b in stn.blocks("sample", nsid) if b["kind"] == "table"][-1]
    tc = notebook.load_content(trow)
    check(tc["cols"] == ["只有一列"] and isinstance(tc["rows"], list),
          "表格块缺字段没补默认值")

    # 导出
    blocks = [(b["kind"], notebook.load_content(b)) for b in stn.blocks("sample", nsid)]
    md = notebook.to_markdown("笔记测试", blocks)
    check("## 目标" in md, "Markdown 导出丢了标题")
    check("### 步骤 1 · 投料" in md, "Markdown 导出丢了步骤")
    check("| 时间 | 温度 |" in md, "Markdown 表格没转成表格")
    page = notebook.to_html("笔记测试", blocks, subtitle="药剂 · S-NOTE")
    check("<table>" in page, "HTML 导出没有表格")
    check("data:image/png;base64" in page, "HTML 导出没内嵌结构图")
    check("codehilite" in page or "<pre>" in page, "HTML 导出没有代码块样式")

    # 计算块
    cns = notebook.calc_namespace()
    val, err = notebook.eval_calc('mw("O=C(O)c1ccccc1")', cns)
    check(not err and abs(float(val) - 122.12) < 0.2, f"mw() 算错：{val} {err}")
    check(abs(float(notebook.eval_calc("mol(5, 100)", cns)[0]) - 0.05) < 1e-9,
          "mol() 算错")
    check(abs(float(notebook.eval_calc("yld(4.6, 5.2)", cns)[0]) - 88.46) < 0.1,
          "yld() 算错")
    notebook.eval_calc("n = 5.0 / 100", cns)
    check(abs(float(notebook.eval_calc("n * 2", cns)[0]) - 0.1) < 1e-9,
          "计算块之间没有共享变量")
    check(notebook.eval_calc("1/0", cns)[1] != "", "除零没报错")
    check(notebook.eval_calc("import os", cns)[1] != "", "计算块该拦下 import")

    # 文本检索要能搜到笔记内容
    check(any(r["id"] == nsid for r in stn.samples(keyword="冰箱")),
          "文本检索搜不到笔记里的字")
    stn.delete_sample(nsid)
    check(stn.blocks("sample", nsid) == [], "删药剂没级联删笔记块")
    stn.close()

    check(hasattr(gui.App, "on_notebook_toolbar") and hasattr(gui.App, "_notebook_block"),
          "GUI 缺笔记入口")
    check("<Control-Shift-B>" in gui_src, "笔记快捷键没绑")
    check("notebook.open_notebook" in gui_src, "GUI 没调用笔记窗口")
    check("实验笔记" in manual_text and "块" in manual_text, "手册缺笔记章节")
    readme = open(os.path.join(HERE, "README.md"), encoding="utf-8").read()
    check("实验笔记" in readme, "README 没写笔记功能")
    check("assets/notebook.png" in readme, "README 没放笔记截图")

    # 输入兜底：某些键盘 / 输入法把 '-' 报成 keysym Insert，Tk 的 Text 会吞掉
    import keyfix
    keyfix.install()
    _tk = tkinter.Tk()
    _tk.withdraw()
    _tw = tkinter.Text(_tk)

    class _Ev:
        def __init__(self, char, keysym, widget):
            self.char, self.keysym, self.widget = char, keysym, widget

    check(keyfix._on_key(_Ev("-", "Insert", _tw)) == "break"
          and _tw.get("1.0", "end-1c") == "-",
          "Text 吞字符的兜底没生效（'-' 仍插不进去）")
    check(keyfix._on_key(_Ev("", "Insert", _tw)) is None
          and _tw.get("1.0", "end-1c") == "-",
          "真按 Insert 键被误插了字符")
    check(keyfix._on_key(_Ev("a", "a", _tw)) is None,
          "普通字母被兜底逻辑重复插入")
    _tk.destroy()

    # ---------------- 浏览器访问（webapp / webui） ----------------
    print("11/11 浏览器访问 …")
    import threading
    import urllib.request

    import webapp
    import webui
    check("openEditor" in webui.PAGE and "saveRecord" in webui.PAGE,
          "网页缺编辑入口")
    check({"title", "conditions", "yield_pct"} <=
          {f["key"] for f in webapp.FIELD_DEFS["reaction"]},
          "反应字段白名单不完整")
    check({"name", "smiles", "cas"} <=
          {f["key"] for f in webapp.FIELD_DEFS["sample"]},
          "药剂字段白名单不完整")
    check(webapp._num("1.5") == 1.5 and webapp._num("") is None,
          "网页端数字解析有误")

    webdb = os.path.join(tmp, "eln_selfcheck_web.db")
    srv = webapp.make_server("127.0.0.1", 8899, db=webdb)
    wport = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{wport}/api/list?kind=reaction", timeout=15) as r:
            payload = json.loads(r.read())
        check(r.status == 200 and "items" in payload, "Web 列表接口不通")
        with urllib.request.urlopen(
                f"http://127.0.0.1:{wport}/api/form?kind=sample&id=0", timeout=15) as r:
            form = json.loads(r.read())
        check(len(form.get("fields", [])) >= 10, "Web 表单字段缺失")
        check("doLogin" in webapp.LOGIN_PAGE, "登录页缺失")
        check(auth.is_admin({"role": "admin"}) and not auth.is_admin({"role": "user"}),
              "管理员判定有误")
        check(auth.is_admin({"name": "old"}) is False, "老账户应视为普通用户")
        check(hasattr(webapp, "new_token") and len(webapp.new_token()) == 8,
              "局域网口令生成异常")
    finally:
        srv.shutdown()

    # 清掉自己造的临时文件
    for p in (db, db + "-bak.db", sdf, csv_path, link, rxn_path, nbdb,
              webdb, webdb + "-journal",
              os.path.join(tmp, "eln_selfcheck_cli.sdf"),
              os.path.join(tmp, "eln_selfcheck_cli_bak.db"),
              os.path.join(tmp, "eln_selfcheck_orphan.db")):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

    print("9d/10 集合孤儿保险（防记录因漏归类 / 删集合而消失） …")
    ob_db = os.path.join(tmp, "eln_selfcheck_orphan.db")
    if os.path.exists(ob_db):
        os.remove(ob_db)
    obs = store.Store(ob_db)
    dc = obs.default_collection_id()
    # 1) 新建记录不指定集合 → 应自动归入默认集合，绝不写 NULL
    s_orphan = obs.add_sample(name="未指定集合的药剂")
    r_orphan = obs.add_reaction(title="未指定集合的反应")
    check(obs.sample(s_orphan)["collection_id"] == dc,
          "未指定集合的药剂被写成 NULL（应归默认集合）")
    check(obs.reaction(r_orphan)["collection_id"] == dc,
          "未指定集合的反应被写成 NULL（应归默认集合）")
    # 2) 删除集合时，名下条目应改挂默认集合，而非被置空（外键 ON DELETE SET NULL 兜底）
    c2 = obs.add_collection("待删集合")
    s2 = obs.add_sample(name="条目A", collection_id=c2)
    r2 = obs.add_reaction(title="反应B", collection_id=c2)
    obs.delete_collection(c2)
    check(obs.sample(s2)["collection_id"] == dc, "删集合后药剂被置空（产生孤儿）")
    check(obs.reaction(r2)["collection_id"] == dc, "删集合后反应被置空（产生孤儿）")
    check(obs.one("SELECT COUNT(*) AS n FROM collections WHERE id=?", (c2,))["n"] == 0,
          "集合没删掉")
    # 3) 直接注入 NULL 再跑 reassign_orphans，应被自动修复
    obs.conn.execute("UPDATE samples SET collection_id=NULL WHERE id=?", (s_orphan,))
    obs.conn.commit()
    check(obs.orphan_counts() == (1, 0), "orphan_counts 计数不对")
    ns, nr = obs.reassign_orphans()
    check((ns, nr) == (1, 0), f"reassign_orphans 修复数不对：{ns},{nr}")
    check(obs.sample(s_orphan)["collection_id"] == dc, "reassign_orphans 没修好 NULL")
    check(obs.orphan_counts() == (0, 0), "修复后仍有孤儿")
    # 4) ORPHAN 哨兵查询：NULL 记录能被专门捞出来（界面「未归类」入口的依托）
    obs.conn.execute("UPDATE reactions SET collection_id=NULL WHERE id=?", (r_orphan,))
    obs.conn.commit()
    check(len(obs.reactions(store.ORPHAN)) == 1, "ORPHAN 哨兵查不出 NULL 反应")
    obs.reassign_orphans()
    obs.close()
    try:
        os.remove(ob_db)
    except Exception:
        pass

    print("9e/10 记录版本快照（LWW：保存/定稿各只留最新一份） …")
    sv_db = os.path.join(tmp, "eln_selfcheck_version.db")
    if os.path.exists(sv_db):
        os.remove(sv_db)
    vs = store.Store(sv_db)
    dc = vs.default_collection_id()
    sid = vs.add_sample(name="快照测试", smiles="CCO", collection_id=dc)
    # 1) 连续两次保存，应只留 1 行且是后一次的内容（LWW 覆盖）
    vs.save_snapshot("sample", sid, "save")
    vs.update_sample(sid, name="快照测试_v2", smiles="CCC")
    vs.save_snapshot("sample", sid, "save")
    n_save = vs.one("SELECT COUNT(*) AS n FROM record_versions "
                    "WHERE owner_type='sample' AND owner_id=? AND kind='save'", (sid,))["n"]
    check(n_save == 1, f"保存快照未合并为 1 份（实际 {n_save}）")
    snap = vs.get_snapshot("sample", sid, "save")
    check(snap is not None and snap["fields"]["name"] == "快照测试_v2",
          "保存快照没覆盖成最新内容")
    # 2) 定稿快照独立于保存，二者并存（各 1 份 = 共 2 份）
    vs.save_snapshot("sample", sid, "finalize")
    n_total = vs.one("SELECT COUNT(*) AS n FROM record_versions "
                     "WHERE owner_type='sample' AND owner_id=?", (sid,))["n"]
    check(n_total == 2, f"保存+定稿应并存 2 份（实际 {n_total}）")
    # 3) 多次定稿也只留 1 份
    vs.update_sample(sid, name="快照测试_v3")
    vs.save_snapshot("sample", sid, "finalize")
    n_fin = vs.one("SELECT COUNT(*) AS n FROM record_versions "
                   "WHERE owner_type='sample' AND owner_id=? AND kind='finalize'", (sid,))["n"]
    check(n_fin == 1, f"定稿快照未合并为 1 份（实际 {n_fin}）")
    # 4) 恢复：改掉内容后从保存快照恢复，应回到 v2
    vs.update_sample(sid, name="篡改")
    vs.restore_snapshot("sample", sid, "save")
    check(vs.sample(sid)["name"] == "快照测试_v2", "恢复保存快照失败")
    # 5) 清空后 get_snapshot 返回 None
    vs.conn.execute("DELETE FROM record_versions WHERE owner_type='sample' AND owner_id=?",
                    (sid,))
    vs.conn.commit()
    check(vs.get_snapshot("sample", sid) is None, "清空后仍能取到快照")
    # 6) 反应快照含组成，恢复能还原组成条数
    rid = vs.add_reaction(title="快照反应", collection_id=dc)
    vs.add_component(rid, sample_id=sid, role="产物", equivalents=1.0)
    vs.add_component(rid, sample_id=None, role="溶剂", label="THF")
    vs.save_snapshot("reaction", rid, "save")
    vs.conn.execute("DELETE FROM reaction_components WHERE reaction_id=?", (rid,))
    vs.conn.commit()
    check(len(vs.components(rid)) == 0, "组成没删掉，无法验证恢复")
    vs.restore_snapshot("reaction", rid, "save")
    check(len(vs.components(rid)) == 2, "恢复反应快照没还原组成")
    vs.close()
    try:
        os.remove(sv_db)
    except Exception:
        pass

    # ------------------------------------------------ 显示 H / 状态栏刷新
    print("\n12/12 显示 H 开关与状态栏刷新 …")
    import math
    import drawpad
    hs = drawpad.Sketch()
    hs.from_smiles("CCO")
    ov = hs.hydrogen_overlays()
    check(len(ov) == 6, f"CCO 应补画 6 个 H（实际 {len(ov)}）")
    if len(ov) >= 2:
        gaps = [math.hypot(a["x"] - b["x"], a["y"] - b["y"])
                for i, a in enumerate(ov) for b in ov[i + 1:]]
        check(min(gaps) > 15, f"补画的 H 互相重叠（最小间距 {min(gaps):.1f}px）")
    ph = drawpad.Sketch()
    ph.from_smiles("c1ccccc1O")
    check(len(ph.hydrogen_overlays()) == 6, "苯酚应补画 5 芳氢 + 1 羟基氢")
    before = (len(hs.atoms), len(hs.bonds), hs.to_json())
    check(hs.render_png(240, 160).tobytes() !=
          hs.render_png(240, 160, show_h=True).tobytes(),
          "show_h 没有改变导出图")
    check((len(hs.atoms), len(hs.bonds), hs.to_json()) == before,
          "显示 H 不应改动 sketch 数据")
    gui_src = open(os.path.join(HERE, "gui.py"), encoding="utf-8").read()
    check("def on_refresh_state" in gui_src and "⟳ 刷新" in gui_src,
          "状态栏刷新按钮缺失")
    check(gui_src.index('text="保存"') < gui_src.index('text="⟳ 刷新"') <
          gui_src.index('text="↺ 恢复"'),
          "刷新按钮应排在恢复与保存之间")
    dp_src = open(os.path.join(HERE, "drawpad.py"), encoding="utf-8").read()
    check("def toggle_show_h" in dp_src and "显示 H" in dp_src,
          "画板显示 H 开关缺失")

    print(f"\n通过 {OK} 项，失败 {BAD} 项")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
