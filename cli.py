# -*- coding: utf-8 -*-
"""无界面命令行：批量导入、导出、结构检索、笔记、备份。

    python cli.py stats
    python cli.py list --kind samples
    python cli.py find "c1ccccc1" --mode sub
    python cli.py blocks --owner reaction --id 1
    python cli.py note-export --owner reaction --id 1 -o note.md
    python cli.py import-sdf compounds.sdf --collection 1
    python cli.py export-sdf out.sdf
    python cli.py export-csv out.csv
    python cli.py backup eln-backup.db

默认操作程序目录下的 eln.db；用 --db 可以指向另一个数据库文件。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

import chem
import notebook
from store import DB_PATH, Store

CSV_COLS = ["id", "code", "name", "cas", "formula", "mw", "amount", "unit",
            "purity", "state", "location", "note"]
CSV_HEAD = ["ID", "编号", "名称", "CAS", "分子式", "分子量",
            "数量", "单位", "纯度", "状态", "位置", "备注"]


def cmd_stats(st, _a):
    s = st.stats()
    print(f"数据库  {st.path}")
    print(f"集合 {s['collections']}    药剂 {s['samples']}    "
          f"反应 {s['reactions']}    附件 {s['attachments']}    "
          f"绘制 {s['drawings']}    笔记块 {s['blocks']}")


def cmd_list(st, a):
    if a.kind == "samples":
        rows = st.samples(a.collection, a.query)
        print(f"药剂 {len(rows)} 条")
        for r in rows:
            amt = f"{r['amount']:g}{r['unit'] or ''}" if r["amount"] is not None else "-"
            print(f"  [{r['id']}] {r['code'] or '-':<9} {r['name']:<16} "
                  f"{r['formula'] or '-':<12} {amt}")
    else:
        rows = st.reactions(a.collection, a.query)
        print(f"反应 {len(rows)} 条")
        for r in rows:
            y = f"{r['yield_pct']:g}%" if r["yield_pct"] is not None else "-"
            print(f"  [{r['id']}] {r['code'] or '-':<9} {r['title']}    产率 {y}")
        if a.components:
            for r in rows:
                comp = st.components(r["id"])
                print(f"  反应 {r['id']} 的组成：")
                for c in comp:
                    print(f"    {c['role']:<5} {c['s_name'] or c['label'] or '?'}  "
                          f"{c['equivalents'] or ''} eq")


def cmd_drawings(st, _a):
    rows = st.q("SELECT * FROM drawings ORDER BY id DESC")
    print(f"绘制 {len(rows)} 张")
    for r in rows:
        print(f"  [{r['id']}] {r['owner_type']}:{r['owner_id']}  "
              f"{r['kind'] or 'structure':<9} {r['title'] or '-'}")
        if r["smiles"]:
            print(f"       {r['smiles']}")


def cmd_blocks(st, a):
    rows = st.blocks(a.owner, a.id)
    if not rows:
        print(f"{a.owner}:{a.id} 还没有笔记。")
        return 0
    counts = st.block_counts(a.owner, a.id)
    parts = [f"{notebook.KINDS[k]} {counts[k]}" for k in notebook.KINDS if counts.get(k)]
    print(f"{a.owner}:{a.id} 笔记 {len(rows)} 块（{' / '.join(parts)}）")
    for i, b in enumerate(rows):
        c = notebook.load_content(b)
        print(f"  {i + 1:02d} {notebook.KINDS.get(b['kind'], b['kind'])}  "
              f"{notebook.summary(b['kind'], c)}")
        if a.full:
            print("      " + json.dumps(c, ensure_ascii=False))
        if b["kind"] == "calc" and c.get("result"):
            print(f"      → {c['result']}")
    return 0


def cmd_note_export(st, a):
    rows = st.blocks(a.owner, a.id)
    if not rows:
        print("这条记录没有笔记可导出。", file=sys.stderr)
        return 1
    blocks = [(b["kind"], notebook.load_content(b)) for b in rows]
    title = f"{a.owner} {a.id}"
    if a.owner == "reaction":
        row = st.reaction(a.id)
        if row is not None:
            title = f"{row['code'] + ' ' if row['code'] else ''}{row['title']}"
    else:
        row = st.sample(a.id)
        if row is not None:
            title = row["name"] or title

    ext = os.path.splitext(a.out)[1].lower()
    if ext in (".html", ".htm"):
        text = notebook.to_html(title, blocks, subtitle=f"{a.owner} · {a.id}")
    else:
        text = notebook.to_markdown(title, blocks)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"已导出 {len(blocks)} 块到 {a.out}")
    return 0


def cmd_find(st, a):
    records = st.all_molfiles()
    if a.mode == "sub":
        hits = [(i, None) for i in chem.substructure_hits(a.query, records)]
        print(f"子结构 {a.query} —— 命中 {len(hits)} 个药剂")
    elif a.mode == "sim":
        hits = chem.similarity_hits(a.query, records, a.threshold)
        print(f"相似性 >= {a.threshold} —— 命中 {len(hits)} 个药剂")
    else:
        rows = st.samples(keyword=a.query)
        print(f"文本检索 —— 命中 {len(rows)} 个药剂")
        for r in rows:
            print(f"  [{r['id']}] {r['name']}  {r['formula'] or ''}")
        return

    by_id = {r["id"]: r for r in st.samples()}
    for sid, score in hits:
        r = by_id.get(sid)
        if r is None:
            continue
        tail = f"  相似度 {score:.3f}" if score is not None else ""
        print(f"  [{sid}] {r['name']}  {r['formula'] or ''}{tail}")
    rids = st.reaction_ids_by_samples(i for i, _ in hits)
    if rids:
        print(f"相关反应 {len(rids)} 条：")
        for rid in sorted(rids):
            row = st.reaction(rid)
            print(f"  [{rid}] {row['title'] if row else '?'}")


def cmd_import_sdf(st, a):
    rows = chem.read_sdf(a.path)
    if not rows:
        print("没读到可解析的结构，检查 SDF 文件。", file=sys.stderr)
        return 1
    for r in rows:
        r["collection_id"] = a.collection
        st.add_sample(**r)
    print(f"导入 {len(rows)} 条药剂到集合 {a.collection or '（无）'}")
    return 0


def cmd_export_sdf(st, a):
    rows = [r for r in st.samples(a.collection) if r["molfile"]]
    if not rows:
        print("没有带结构的药剂可导出。", file=sys.stderr)
        return 1
    n = chem.write_sdf(a.path, rows)
    print(f"写出 {n} 条结构到 {a.path}")
    return 0


def cmd_export_csv(st, a):
    rows = st.samples(a.collection)
    with open(a.path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_HEAD)
        for r in rows:
            w.writerow([r[c] if r[c] is not None else "" for c in CSV_COLS])
    print(f"写出 {len(rows)} 条到 {a.path}")
    return 0


def cmd_backup(st, a):
    st.backup_to(a.path)
    print(f"已备份数据库到 {a.path}")
    print("注意：附件在 attachments/ 目录里，要一起复制。")
    return 0


def cmd_add_sample(st, a):
    data = {
        "name": a.name, "code": a.code or "", "cas": a.cas or "",
        "smiles": a.smiles or "", "amount": a.amount,
        "unit": a.unit, "purity": a.purity or "",
        "note": a.note or "", "collection_id": a.collection,
    }
    if a.smiles:
        info = chem.analyze(a.smiles)
        if "error" in info:
            print(info["error"], file=sys.stderr)
            return 1
        data.update({"formula": info["formula"], "mw": info["mw"],
                     "molfile": info["molfile"], "smiles": info["smiles"]})
    sid = st.add_sample(**data)
    print(f"已添加药剂 [{sid}] {a.name}"
          + (f"  {data.get('formula', '')}" if a.smiles else ""))
    return 0


def build_parser():
    p = argparse.ArgumentParser(description="ELN 命令行工具")
    p.add_argument("--db", default=DB_PATH, help="指定数据库文件（默认 eln.db）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats", help="数据概况").set_defaults(func=cmd_stats)

    sub.add_parser("drawings", help="列出所有绘制（结构式 / 反应式）").set_defaults(
        func=cmd_drawings)

    q = sub.add_parser("list", help="列出药剂或反应")
    q.add_argument("--kind", choices=["samples", "reactions"], default="samples")
    q.add_argument("--query", default="", help="文本关键词")
    q.add_argument("--collection", type=int, default=None)
    q.add_argument("--components", action="store_true", help="连带打印反应组成")
    q.set_defaults(func=cmd_list)

    n = sub.add_parser("blocks", help="列出某条记录的笔记块")
    n.add_argument("--owner", choices=["sample", "reaction"], required=True)
    n.add_argument("--id", type=int, required=True)
    n.add_argument("--full", action="store_true", help="连 JSON 内容一起打印")
    n.set_defaults(func=cmd_blocks)

    ne = sub.add_parser("note-export", help="把笔记导出成 Markdown / HTML")
    ne.add_argument("--owner", choices=["sample", "reaction"], required=True)
    ne.add_argument("--id", type=int, required=True)
    ne.add_argument("-o", "--out", required=True, help="输出文件（.md / .html）")
    ne.set_defaults(func=cmd_note_export)

    f = sub.add_parser("find", help="检索（文本 / 子结构 / 相似性）")
    f.add_argument("query")
    f.add_argument("--mode", choices=["text", "sub", "sim"], default="text")
    f.add_argument("--threshold", type=float, default=0.3)
    f.set_defaults(func=cmd_find)

    i = sub.add_parser("import-sdf", help="从 SDF 批量导入药剂")
    i.add_argument("path")
    i.add_argument("--collection", type=int, default=None)
    i.set_defaults(func=cmd_import_sdf)

    e = sub.add_parser("export-sdf", help="导出带结构的药剂")
    e.add_argument("path")
    e.add_argument("--collection", type=int, default=None)
    e.set_defaults(func=cmd_export_sdf)

    c = sub.add_parser("export-csv", help="导出药剂台账")
    c.add_argument("path")
    c.add_argument("--collection", type=int, default=None)
    c.set_defaults(func=cmd_export_csv)

    b = sub.add_parser("backup", help="整库快照")
    b.add_argument("path")
    b.set_defaults(func=cmd_backup)

    s = sub.add_parser("add-sample", help="添加一条药剂")
    s.add_argument("name")
    s.add_argument("--smiles", default="")
    s.add_argument("--code", default="")
    s.add_argument("--cas", default="")
    s.add_argument("--amount", type=float, default=None)
    s.add_argument("--unit", default="g")
    s.add_argument("--purity", default="")
    s.add_argument("--note", default="")
    s.add_argument("--collection", type=int, default=None)
    s.set_defaults(func=cmd_add_sample)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    st = Store(os.path.abspath(a.db))
    try:
        rc = a.func(st, a)
    finally:
        st.close()
    return rc or 0


if __name__ == "__main__":
    sys.exit(main())
