# -*- coding: utf-8 -*-
"""把记录打包成两种「程序没了也读得开」的格式：

- **Markdown 包（zip）**：每条记录一个 .md + YAML frontmatter，配结构图 PNG、
  molfile、组成表 CSV、附件副本——Obsidian / Typora / 记事本都能直接看。
- **.eln 包（zip）**：RO-Crate 1.1 规范（ELN Consortium 的跨 ELN 交换格式，
  eLabFTW 等开源 ELN 互相认）：根目录 ro-crate-metadata.json 描述所有实体，
  记录作为 Dataset 实体挂进 @graph。

两个 builder 都不依赖 GUI。附件从磁盘读，读不到的跳过并在包里记 missing.txt。
"""
from __future__ import annotations

import csv
import datetime
import io
import json
import os
import zipfile

import chem
import recexport
import stoich

APP_NAME = "ELN 电子实验记录"
RO_CRATE_CONTEXT = "https://w3id.org/ro/crate/1.1/context"
RO_CRATE_SPEC = "https://w3id.org/ro/crate/1.1"
ELN_SPEC_URL = "https://github.com/TheELNConsortium/eln-schema"


# ---------------------------------------------------------------- 采集

def _s(v):
    return "" if v is None else str(v)


def gather(store, owner_type: str, oid: int) -> dict | None:
    """一条记录的完整打包素材（文件都在内存里）。"""
    row = store.sample(oid) if owner_type == "sample" else store.reaction(oid)
    if row is None:
        return None
    p = {"owner_type": owner_type,
         "kind": "样品" if owner_type == "sample" else "反应",
         "id": oid,
         "title": "",
         "created": _s(row["created"]),
         "meta": {},
         "blocks": [],
         "files": {}}

    def addfile(name, data):
        p["files"][name] = data

    if owner_type == "sample":
        p["title"] = _s(row["name"]) or f"药剂 {oid}"
        p["meta"] = {"type": "sample", "id": oid, "name": _s(row["name"]),
                     "code": _s(row["code"]), "cas": _s(row["cas"]),
                     "formula": _s(row["formula"]),
                     "mw": _s(row["mw"]), "smiles": _s(row["smiles"]),
                     "amount": _s(row["amount"]), "unit": _s(row["unit"]),
                     "purity": _s(row["purity"]), "state": _s(row["state"]),
                     "location": _s(row["location"]), "note": _s(row["note"]),
                     "created": p["created"], "updated": _s(row["updated"]),
                     "kind": "样品", "app": APP_NAME}
        mol = _s(row["molfile"])
        if mol:
            addfile("structure.mol", mol)
        m = chem.mol_from_record(row)
        img = chem.render(m, recexport.IMG_W, recexport.IMG_H)
        if img is not None:
            addfile("structure.png", rec_png(img))
            svg = chem.render_svg(m, recexport.IMG_W, recexport.IMG_H)
            if svg:
                addfile("structure.svg", svg)
        comps = None
    else:
        p["title"] = _s(row["title"]) or f"反应 {oid}"
        p["meta"] = {"type": "reaction", "id": oid, "title": _s(row["title"]),
                     "code": _s(row["code"]), "conditions": _s(row["conditions"]),
                     "yield_pct": _s(row["yield_pct"]), "note": _s(row["note"]),
                     "created": p["created"], "updated": _s(row["updated"]),
                     "kind": "反应", "app": APP_NAME}
        comps = [dict(r) for r in store.components(oid)]
        for i, d in enumerate(store.drawings("reaction", oid), start=1):
            addfile(f"drawing-{i}.json", _s(d["data"]))
            if d["smiles"]:
                addfile(f"drawing-{i}.smiles", _s(d["smiles"]))
        # 反应式拼图（PNG + 矢量 SVG）
        img = _reaction_image(store, oid)
        if img is not None:
            addfile("scheme.png", rec_png(img))
        svg = recexport._reaction_svg(store, oid)
        if svg:
            addfile("scheme.svg", svg)

    # 组成表
    if comps:
        rows = []
        for c in comps:
            mmol = stoich.row_mmol(c)
            rows.append([c.get("role") or "",
                         c.get("s_name") or c.get("label") or "（未关联药剂）",
                         "" if c["equivalents"] is None else recexport._g(c["equivalents"]),
                         "" if c["amount"] is None else
                         recexport._amt(c["amount"], c["unit"]),
                         "" if mmol is None else f"{mmol:.2f}",
                         "" if c["actual"] is None else recexport._g(c["actual"])])
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["role", "name", "equivalents", "amount", "mmol", "actual_g"])
        w.writerows(rows)
        addfile("composition.csv", buf.getvalue())
        p["comps"] = rows
        p["summary"] = stoich.summary_text(comps) or ""
    else:
        p["comps"] = None
        p["summary"] = ""

    # 附件
    atts = store.attachments(owner_type, oid)
    missing = []
    for a in atts:
        src = _s(a["path"])
        if src and os.path.exists(src):
            try:
                with open(src, "rb") as fh:
                    addfile(f"attachments/{os.path.basename(src)}", fh.read())
            except OSError:
                missing.append(src)
        elif src:
            missing.append(src)
    if missing:
        addfile("attachments/_missing.txt",
                "以下附件在磁盘上找不到，没有进包：\n" + "\n".join(missing))

    # 笔记块
    p["blocks"] = [dict(b) for b in store.blocks(owner_type, oid)]
    return p


def _reaction_image(store, rid: int):
    """反应式拼图——直接复用 recexport 的实现，避免两处箭头参数走样。"""
    return recexport._reaction_image(store, rid)


def rec_png(img) -> bytes:
    """RGBA 贴白底存 PNG 字节。"""
    from PIL import Image
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
    buf = io.BytesIO()
    bg.save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- Markdown

def _yaml_str(v) -> str:
    s = _s(v)
    if s == "" or any(ch in s for ch in ":#{}[]&*!|>'\"%@`,\n") or s != s.strip():
        return json.dumps(s, ensure_ascii=False)
    return s


def record_markdown(p: dict) -> str:
    """frontmatter + 正文。"""
    fm = ["---"]
    for k, v in p["meta"].items():
        fm.append(f"{k}: {_yaml_str(v)}")
    fm.append("---")
    out = ["\n".join(fm), "", f"# {p['title']}", ""]

    def body(*lines):
        out.extend(lines)

    pairs = [(k, v) for k, v in p["meta"].items()
             if k not in ("type", "id", "kind", "app", "created", "updated") and _s(v)]
    if pairs:
        body("| 字段 | 值 |")
        body("|---|---|")
        for k, v in pairs:
            body(f"| {k} | {_s(v).replace(chr(10), ' / ')} |")
        body("")

    img = ("scheme.png" if p["kind"] == "反应" else "structure.png")
    if img in p["files"]:
        body(f"![{p['title']}]({img})")
        body("")

    if p["comps"]:
        body("## 组成", "")
        body("| 角色 | 物质 | 当量 | 用量 | 摩尔量 | 实测/g |")
        body("|---|---|---|---|---|---|")
        for r in p["comps"]:
            body("| " + " | ".join(_s(x) or "—" for x in r) + " |")
        if p["summary"]:
            body("", f"> {p['summary']}")
        body("")

    if p["meta"].get("note"):
        body("## 备注", "", _s(p["meta"]["note"]), "")

    blocks = p["blocks"]
    if blocks:
        body("## 笔记", "")
        for b in blocks:
            try:
                c = json.loads(b["content"] or "{}")
            except ValueError:
                c = {}
            body(f"### 块 {b['position'] + 1}（{b['kind']}）", "")
            k = b["kind"]
            if k == "text":
                body(_s(c.get("md")), "")
            elif k == "step":
                body(f"- [ {'x' if c.get('done') else ' '} ] "
                     f"**{_s(c.get('title'))}**"
                     + (f"（{_s(c.get('time'))}）" if c.get("time") else ""), "",
                     _s(c.get("body")), "")
            elif k == "chem":
                body(f"`{_s(c.get('smiles'))}`"
                     + (f" — {_s(c.get('caption'))}" if c.get("caption") else ""), "")
            elif k == "table":
                cols = c.get("cols") or []
                if cols:
                    body("| " + " | ".join(map(_s, cols)) + " |")
                    body("|" + "---|" * len(cols))
                    for row in c.get("rows") or []:
                        body("| " + " | ".join(_s(x) for x in row) + " |")
                    body("")
            elif k == "calc":
                body("```", _s(c.get("expr")), "```", "")
                if c.get("note"):
                    body(_s(c.get("note")), "")
    body("", "---", f"*导出于 {datetime.datetime.now():%Y-%m-%d %H:%M} · {APP_NAME}*")
    return "\n".join(out)


def _safe_name(s: str) -> str:
    return "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in _s(s)).strip() or "记录"


def write_markdown_zip(packages: list[dict], path: str, root: str = "ELN-Markdown"):
    """packages: gather() 的结果列表 → 一个 zip，每条记录一个 .md + 素材。"""
    used = set()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in packages:
            base = f"{p['created'][:10] or 'undated'}-{_safe_name(p['title'])}"
            name, i = base, 2
            while f"{name}.md" in used:
                name = f"{base}-{i}"
                i += 1
            z.writestr(f"{root}/{name}.md", record_markdown(p))
            used.add(f"{name}.md")
            for rel, data in p["files"].items():
                z.writestr(f"{root}/{name}-assets/{rel}", data)
    return path


# ---------------------------------------------------------------- .eln (RO-Crate)

def _eln_entity(eid: str, etype, **props) -> dict:
    e = {"@id": eid, "@type": etype}
    e.update(props)
    return e


def _eln_part_of(graph_root_parts, dir_name: str) -> dict:
    return {"@id": dir_name}


def write_eln_zip(packages: list[dict], path: str, root: str = "") -> str:
    """RO-Crate 1.1 的 .eln 包。

    root: 包内根目录名（eLabFTW 习惯用实验标题）。空 = 用默认名。
    """
    now = datetime.datetime.now().isoformat(timespec="seconds")
    root = _safe_name(root) or "ELN-export"
    graph = [
        _eln_entity("ro-crate-metadata.json", "CreativeWork",
                    about={"@id": "./"},
                    conformsTo=[{"@id": RO_CRATE_SPEC}, {"@id": ELN_SPEC_URL}]),
        _eln_entity("./", "Dataset",
                    name=root,
                    description=f"导出自 {APP_NAME}，{len(packages)} 条记录",
                    datePublished=now,
                    license="https://creativecommons.org/licenses/by-nc/4.0/",
                    hasPart=[]),
    ]
    parts = graph[1]["hasPart"]
    used = set()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in packages:
            rec_dir = f"records/{p['owner_type']}-{p['id']}-{_safe_name(p['title'])[:40]}"
            i = 2
            base = rec_dir
            while rec_dir in used:
                rec_dir = f"{base}-{i}"
                i += 1
            used.add(rec_dir)
            rec_files = [f"{rec_dir}/record.json", f"{rec_dir}/record.md"]
            z.writestr(f"{root}/{rec_dir}/record.json",
                       json.dumps({"meta": p["meta"], "components": p["comps"],
                                   "blocks": p["blocks"],
                                   "summary": p["summary"]},
                                  ensure_ascii=False, indent=1))
            z.writestr(f"{root}/{rec_dir}/record.md", record_markdown(p))
            for rel, data in p["files"].items():
                rel = rel.replace("\\", "/")
                z.writestr(f"{root}/{rec_dir}/{rel}", data)
                rec_files.append(f"{rec_dir}/{rel}")
            ent = _eln_entity(rec_dir + "/", "Dataset",
                              name=p["title"],
                              description=_s(p["meta"].get("note") or
                                             p["meta"].get("smiles") or
                                             p["meta"].get("conditions")),
                              dateCreated=p["created"] or now,
                              additionalType=p["kind"],
                              identifier=f"{p['owner_type']}:{p['id']}",
                              hasPart=[{"@id": f} for f in rec_files])
            graph.append(ent)
            parts.append({"@id": rec_dir + "/"})
        # 说明文件
        z.writestr(f"{root}/README.txt",
                   f"{APP_NAME} 导出的 .eln（RO-Crate 1.1）包\n"
                   f"导出时间：{now}\n记录数：{len(packages)}\n\n"
                   "ro-crate-metadata.json 是包清单；records/ 下每条记录一个目录，\n"
                   "record.json 是结构化数据（字段 / 组成 / 笔记块），record.md 是人可读版。\n"
                   "附件在各自记录目录的 attachments/ 下。\n")
        z.writestr(f"{root}/ro-crate-metadata.json",
                   json.dumps({"@context": RO_CRATE_CONTEXT, "@graph": graph},
                              ensure_ascii=False, indent=1))
    return path


# ---------------------------------------------------------------- 便捷入口

def gather_many(store, owner_type: str, oids) -> list[dict]:
    out = []
    for oid in oids:
        p = gather(store, owner_type, oid)
        if p:
            out.append(p)
    return out


def collection_ids(store, coll_id: int) -> dict:
    """集合里所有药剂与反应的 id。"""
    return {"sample": [r["id"] for r in store.q(
                "SELECT id FROM samples WHERE collection_id=?", (coll_id,))],
            "reaction": [r["id"] for r in store.q(
                "SELECT id FROM reactions WHERE collection_id=?", (coll_id,))]}


def export_md_zip(store, path: str, coll_id: int | None = None,
                  owner_type: str | None = None, oid: int | None = None) -> int:
    """单条记录或整个集合 → Markdown zip。返回打包条数。"""
    pkgs: list[dict] = []
    if oid is not None:
        p = gather(store, owner_type, oid)
        if p:
            pkgs = [p]
    else:
        ids = collection_ids(store, coll_id) if coll_id else {
            "sample": [r["id"] for r in store.q("SELECT id FROM samples")],
            "reaction": [r["id"] for r in store.q("SELECT id FROM reactions")]}
        pkgs = gather_many(store, "sample", ids["sample"]) + \
            gather_many(store, "reaction", ids["reaction"])
    if not pkgs:
        return 0
    write_markdown_zip(pkgs, path)
    return len(pkgs)


def export_eln_zip(store, path: str, coll_id: int | None = None,
                   owner_type: str | None = None, oid: int | None = None,
                   root_name: str = "") -> int:
    """单条记录或整库（不传 coll_id/oid）→ .eln zip。返回打包条数。"""
    if oid is not None:
        p = gather(store, owner_type, oid)
        pkgs = [p] if p else []
    else:
        if coll_id:
            ids = collection_ids(store, coll_id)
        else:
            ids = {"sample": [r["id"] for r in store.q("SELECT id FROM samples")],
                   "reaction": [r["id"] for r in store.q("SELECT id FROM reactions")]}
        pkgs = gather_many(store, "sample", ids["sample"]) + \
            gather_many(store, "reaction", ids["reaction"])
    if not pkgs:
        return 0
    root_name = root_name or (f"ELN-{coll_id or 'all'}-"
                              f"{datetime.datetime.now():%Y%m%d-%H%M}")
    write_eln_zip(pkgs, path, root_name)
    return len(pkgs)
