# -*- coding: utf-8 -*-
"""当前记录导出为 PDF / DOCX。

gather()      把样品 / 反应记录整理成一份结构化内容（字段、结构图、组成表、操作），
              组成表带摩尔量与实测列，汇总行用 stoich 现算。
build_pdf()   fpdf2：正文 12pt（小四），中文宋体、数字与英文 Times New Roman，
              两者按字符自动切换；只有主标题用大字号。
build_docx()  python-docx，正文微软雅黑，表格带网格边框。
              反应式图：左右两侧结构各渲染一张，白底拼图 + 箭头。

两个 builder 都不依赖 GUI，可单独自检。
"""
from __future__ import annotations

import datetime
import io
import json
import os

import chem
import stoich

APP_NAME = "ELN 电子实验记录"

# 结构式导出分辨率：按 110 mm 图宽算，1500 px 约合 350 dpi（屏幕/打印都够）
IMG_W, IMG_H = 1500, 1000
RXN_W, RXN_H = 900, 620


# ---------------------------------------------------------------- 内容收集

def _s(v):
    return "" if v is None else str(v)


def _g(v):
    """数字按 %g 缩写；存成文本的值（如纯度「≥98%」、数量「5.0 g」）原样返回。"""
    if v is None or v == "":
        return ""
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return str(v)


def _amt(v, unit) -> str:
    """数值 + 单位；文本里已带同样单位的（如「5.0 g」+ g）不再重复拼。"""
    s = _g(v)
    if not s:
        return ""
    u = _s(unit).strip()
    if u and not s.lower().endswith(u.lower()):
        return f"{s} {u}"
    return s


def _split_rxn(smi: str):
    """'A.B>>C.D' -> (left, right)；普通结构式 -> (smi, '')。"""
    s = (smi or "").strip()
    if ">>" in s:
        l, r = s.split(">>", 1)
        return l.strip(), r.strip()
    return s, ""


def gather(store, owner_type: str, oid: int, att_paths: bool = False) -> dict | None:
    """整理一条记录。owner_type: 'sample' | 'reaction'。

    att_paths=True 时附带附件清单（文件名 + 完整路径，不含内容），
    供导出 PDF/DOCX 时在文末打印附件存放在哪里。
    """
    row = store.sample(oid) if owner_type == "sample" else store.reaction(oid)
    if row is None:
        return None

    c = {"kind": "样品" if owner_type == "sample" else "反应",
         "title": "", "fields": [], "image_png": None, "image_svg": None,
         "image_caption": "", "comps": None, "summary": "",
         "procedure": "", "note": ""}

    if owner_type == "sample":
        c["title"] = _s(row["name"]) or "未命名药剂"
        pairs = [("编号", row["code"]), ("CAS 号", row["cas"]),
                 ("分子式", row["formula"]),
                 ("分子量", _g(row["mw"])), ("SMILES", row["smiles"]),
                 ("数量", _amt(row["amount"], row["unit"])),
                 ("纯度", _g(row["purity"])), ("状态", row["state"]),
                 ("存放位置", row["location"]), ("备注", row["note"])]
        c["fields"] = [(k, _s(v)) for k, v in pairs if _s(v)]
        mol = chem.mol_from_record(row)
        img = chem.render(mol, IMG_W, IMG_H)
        if img is not None:
            c["image_png"] = _white_png(img)
            c["image_svg"] = chem.render_svg(mol, IMG_W, IMG_H)
            c["image_caption"] = _s(row["smiles"])
    else:
        c["title"] = _s(row["title"]) or "未命名反应"
        pairs = [("编号", row["code"]), ("条件", row["conditions"]),
                 ("产率", f"{_g(row['yield_pct'])}%" if row["yield_pct"] is not None else ""),
                 ("记录时间", row["created"]), ("备注", row["note"])]
        c["fields"] = [(k, _s(v)) for k, v in pairs if _s(v)]
        c["procedure"] = _s(row["procedure"])
        c["note"] = _s(row["note"])
        img = _reaction_image(store, oid)
        if img is not None:
            c["image_png"] = _white_png(img)
            c["image_svg"] = _reaction_svg(store, oid)
            c["image_caption"] = "反应式（取自最新绘制）"
        # 组成表（带双向计算结果）
        comp = [dict(r) for r in store.components(oid)]
        if comp:
            head = ["角色", "物质", "当量", "用量", "摩尔量"]
            body = []
            for r in comp:
                amt = _amt(r["amount"], r["unit"])
                mmol = stoich.row_mmol(r)
                body.append([r.get("role") or "",
                             r.get("s_name") or r.get("label") or "（未关联药剂）",
                             _g(r["equivalents"]) if r["equivalents"] is not None else "",
                             amt,
                             f"{mmol:.2f}" if mmol is not None else "—"])
            c["comps"] = {"head": head, "rows": body}
            c["summary"] = stoich.summary_text(comp) or ""

    # 实验笔记块（笔记本里的文字 / 步骤 / 结构 / 表格 / 计算块）
    c["blocks"] = _blocks_view(store, owner_type, oid)

    # 附件路径清单（默认不收；开关打开时才打印）
    c["att_paths"] = []
    if att_paths:
        try:
            for a in store.attachments(owner_type, oid):
                nm = _s(a["title"]) or os.path.basename(a["path"] or "")
                if _s(a["path"]):
                    c["att_paths"].append([nm, _s(a["path"])])
        except Exception:
            pass

    c["exported_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return c


def _blocks_view(store, owner_type: str, oid: int) -> list[dict]:
    """笔记本块 → 导出用列表（与网页 _block_view 同一套展示规则）。"""
    out: list[dict] = []
    n_step = 0
    try:
        raw = list(store.blocks(owner_type, oid))
    except Exception:
        raw = []
    for b in raw:
        try:
            ct = json.loads(b["content"] or "{}")
        except (ValueError, TypeError):
            ct = {}
        if not isinstance(ct, dict):
            ct = {}
        k = b["kind"] or "text"
        if k == "step":
            n_step += 1
            head = f"步骤 {n_step} · {ct.get('title') or '未命名'}"
            if ct.get("done"):
                head += "（已完成）"
            bits = [head]
            if ct.get("time"):
                bits.append(f"用时：{ct['time']}")
            body = (ct.get("body") or "").strip()
            if body:
                bits.append(body)
            out.append({"kind": "step", "head": head, "body": body,
                        "text": "\n".join(bits)})
        elif k == "chem":
            t = " · ".join(x for x in (ct.get("caption"), ct.get("smiles"))
                           if x).strip()
            out.append({"kind": "chem", "text": t})
        elif k == "table":
            cols = [str(x) for x in (ct.get("cols") or [])]
            rows = [[str(x) for x in r] for r in (ct.get("rows") or [])]
            rows = [r + [""] * (len(cols) - len(r)) for r in rows]
            out.append({"kind": "table", "cols": cols, "rows": rows})
        elif k == "calc":
            bits = []
            if ct.get("expr"):
                bits.append(ct["expr"])
            if ct.get("result"):
                bits.append(f"→ {ct['result']}")
            if ct.get("note"):
                bits.append(ct["note"])
            out.append({"kind": "calc", "text": "\n".join(bits).strip()})
        else:
            t = (ct.get("md") or "").strip()
            if t:
                out.append({"kind": "text", "text": t})
    return out


def _svg_inner(svg_text: str) -> str:
    """取 RDKit SVG 的内部元素（去掉根标签与背景 rect），供拼图外层复用。"""
    import re
    m = re.search(r"<svg[^>]*>(.*)</svg>", svg_text or "", re.S)
    if not m:
        return ""
    return re.sub(r"<rect[^>]*/>", "", m.group(1))


def _reaction_svg(store, rid: int) -> str | None:
    """反应式的矢量拼图：左右两侧 SVG + 矢量箭头，布局与 _reaction_image 一致。"""
    import re as _re
    drawings = store.drawings("reaction", rid)
    smi = next((d["smiles"] for d in drawings if d["smiles"]), "")
    left, right = _split_rxn(smi)
    svgs = [chem.render_smiles_svg(x, RXN_W, RXN_H) for x in (left, right)]
    svgs = [s for s in svgs if s]
    if not svgs:
        return None
    if len(svgs) == 1:
        return svgs[0]

    s = RXN_W / 320.0
    gap, arrow = int(34 * s), int(26 * s)
    pad = int(6 * s)
    lw = max(3, int(3 * s))
    h = RXN_H
    w = RXN_W * 2 + gap + arrow + int(12 * s)
    x0 = pad + RXN_W + gap // 2
    ym = h // 2
    x1 = x0 + arrow + gap // 2 + pad
    head = int(9 * s)
    hh = int(6 * s)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'width="{w}px" height="{h}px" viewBox="0 0 {w} {h}">'
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="white"/>'
        f'<g transform="translate({pad},0)">{_svg_inner(svgs[0])}</g>'
        f'<g transform="translate({x1},0)">{_svg_inner(svgs[1])}</g>'
        f'<line x1="{x0}" y1="{ym}" x2="{x0 + arrow}" y2="{ym}" '
        f'stroke="#3c3c3c" stroke-width="{lw}"/>'
        f'<polygon points="{x0 + arrow},{ym} {x0 + arrow - head},{ym - hh} '
        f'{x0 + arrow - head},{ym + hh}" fill="#3c3c3c"/>'
        f'</svg>'
    )


def _white_png(img) -> bytes:
    """RGBA 贴到白底，存成 PNG 字节。"""
    from PIL import Image
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
    buf = io.BytesIO()
    bg.save(buf, "PNG")
    return buf.getvalue()


def _reaction_image(store, rid: int):
    """反应式拼图：左 → 右，各渲染后白底拼接。"""
    from PIL import Image, ImageDraw
    drawings = store.drawings("reaction", rid)
    smi = next((d["smiles"] for d in drawings if d["smiles"]), "")
    left, right = _split_rxn(smi)
    imgs = [chem.render_smiles(x, RXN_W, RXN_H) for x in (left, right)]
    if all(i is None for i in imgs):
        return None
    imgs = [i for i in imgs if i is not None]
    if len(imgs) == 1:
        return imgs[0]
    # 箭头间距按出图尺寸等比放大（基准 320 px 宽）
    s = RXN_W / 320.0
    gap, arrow = int(34 * s), int(26 * s)
    pad = int(6 * s)
    lw = max(3, int(3 * s))
    h = max(i.height for i in imgs) + int(16 * s)
    w = sum(i.width for i in imgs) + gap + arrow + int(12 * s)
    canvas = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    y0 = (h - imgs[0].height) // 2
    canvas.paste(imgs[0], (pad, y0), imgs[0])
    x0 = pad + imgs[0].width + gap // 2
    ym = h // 2
    d = ImageDraw.Draw(canvas)
    d.line((x0, ym, x0 + arrow, ym), fill=(60, 60, 60, 255), width=lw)
    tip = int(9 * s)
    head = int(6 * s)
    d.polygon([(x0 + arrow, ym), (x0 + arrow - tip, ym - head),
               (x0 + arrow - tip, ym + head)], fill=(60, 60, 60, 255))
    x1 = x0 + arrow + gap // 2 + pad
    canvas.paste(imgs[1], (x1, (h - imgs[1].height) // 2), imgs[1])
    return canvas


# ---------------------------------------------------------------- DOCX

def build_docx(c: dict, path: str) -> str:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

    h = doc.add_heading(f"{c['title']}", level=0)
    for r in h.runs:
        r.font.name = "微软雅黑"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    sub = doc.add_paragraph()
    run = sub.add_run(f"[{c['kind']}记录 · 导出于 {c['exported_at']} · {APP_NAME}]")
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x8A, 0x94, 0xA2)

    if c["fields"]:
        t = doc.add_table(rows=0, cols=2)
        t.style = "Table Grid"
        for k, v in c["fields"]:
            cells = t.add_row().cells
            cells[0].width, cells[1].width = Cm(3.2), Cm(12.8)
            for cell, text, bold in ((cells[0], k, True), (cells[1], v, False)):
                p = cell.paragraphs[0]
                r = p.add_run(text)
                r.font.bold = bold
                r.font.size = Pt(9.5)
        doc.add_paragraph()

    if c["image_png"]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run().add_picture(io.BytesIO(c["image_png"]), width=Cm(9))
        cap = doc.add_paragraph(c["image_caption"])
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for r in cap.runs:
            r.font.size = Pt(8.5)
            r.font.color.rgb = RGBColor(0x8A, 0x94, 0xA2)

    if c["comps"]:
        doc.add_heading("组成", level=1)
        t = doc.add_table(rows=1, cols=len(c["comps"]["head"]))
        t.style = "Table Grid"
        t.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for cell, text in zip(t.rows[0].cells, c["comps"]["head"]):
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = cell.paragraphs[0].add_run(text)
            r.font.bold = True
            r.font.size = Pt(9)
        for row_vals in c["comps"]["rows"]:
            cells = t.add_row().cells
            for cell, text in zip(cells, row_vals):
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
                r = cell.paragraphs[0].add_run(_s(text))
                r.font.size = Pt(9)
        if c["summary"]:
            p = doc.add_paragraph()
            r = p.add_run(c["summary"])
            r.font.size = Pt(8.5)
            r.font.color.rgb = RGBColor(0x1A, 0x7F, 0x37)

    if c["procedure"]:
        doc.add_heading("操作", level=1)
        for para in c["procedure"].splitlines() or [""]:
            doc.add_paragraph(para)

    blocks = [b for b in (c.get("blocks") or [])
              if b.get("text") or b.get("kind") == "table"]
    if blocks:
        doc.add_heading("实验笔记", level=1)
        for b in blocks:
            if b["kind"] == "table" and b.get("cols"):
                t = doc.add_table(rows=1, cols=len(b["cols"]))
                t.style = "Table Grid"
                for cell, text in zip(t.rows[0].cells, b["cols"]):
                    r = cell.paragraphs[0].add_run(text)
                    r.font.bold = True
                    r.font.size = Pt(9)
                for vals in b["rows"]:
                    cells = t.add_row().cells
                    for cell, text in zip(cells, vals):
                        r = cell.paragraphs[0].add_run(_s(text))
                        r.font.size = Pt(9)
                doc.add_paragraph()
                continue
            if b["kind"] == "step" and b.get("head"):
                p = doc.add_paragraph()
                r = p.add_run(b["head"])
                r.font.bold = True
                if b.get("body"):
                    doc.add_paragraph(b["body"])
            elif b["kind"] == "chem":
                doc.add_paragraph("结构：" + (b.get("text") or ""))
            else:
                doc.add_paragraph(b.get("text") or "")

    if c["note"]:
        doc.add_heading("备注", level=1)
        doc.add_paragraph(c["note"])

    if c.get("att_paths"):
        doc.add_heading("附件", level=1)
        for nm, p in c["att_paths"]:
            doc.add_paragraph(p if os.path.basename(p) == nm else f"{nm}：{p}")

    doc.save(path)
    return path


# ---------------------------------------------------------------- PDF

_FONTS_DIR = r"C:\Windows\Fonts"

# 西文：Times New Roman（正/斜/粗/粗斜）；中文：宋体（宋体没有真粗体，
# 粗体样式复用同一份字形文件，版面里靠字号/颜色区分层级）。
_LATIN_FAMILIES = [
    # 名字不能叫 times —— 那是 PDF 内置核心字体名，会顶掉 Times New Roman
    ("tnr", {"": "times.ttf", "B": "timesbd.ttf",
             "I": "timesi.ttf", "BI": "timesbi.ttf"}),
]
_CJK_FAMILIES = [
    ("song", {"": "simsun.ttc", "B": "simsun.ttc"}),
    ("msyh", {"": "msyh.ttc", "B": "msyhbd.ttc"}),
    ("hei", {"": "simhei.ttf", "B": "simhei.ttf"}),
]

BODY_PT = 12.0          # 小四
LINE_H = 6.2            # 12pt 行距（约 1.45 倍）


def _install(pdf, families) -> str | None:
    """按优先级注册一组字体族，返回第一个可用的名字。"""
    for fam, styles in families:
        ok = False
        for style, name in styles.items():
            path = os.path.join(_FONTS_DIR, name)
            if not os.path.exists(path):
                continue
            try:
                pdf.add_font(fam, style, path)
                ok = ok or style == ""
            except Exception:
                pass
        if ok:
            return fam
    return None


def _pdf_fonts(pdf) -> tuple:
    """注册西文 + 中文字体并开字符级回退，返回 (西文族, 中文族)。"""
    latin = _install(pdf, _LATIN_FAMILIES) or "helvetica"
    cjk = _install(pdf, _CJK_FAMILIES)
    if cjk:
        # 当前字体缺字形时逐字切到中文字体：数字/英文走 Times，汉字走宋体
        try:
            pdf.set_fallback_fonts([cjk], exact_match=True)
        except Exception:
            cjk = None
    return latin, cjk


def build_pdf(c: dict, path: str) -> str:
    """正文统一 12pt（小四）：中文宋体、数字与英文 Times New Roman。
    只有文档主标题保持大字号。"""
    from fpdf import FPDF
    from fpdf.fonts import FontFace

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(16, 14, 16)
    pdf.add_page()
    fam, _cjk = _pdf_fonts(pdf)

    def head(text, lh=LINE_H):
        pdf.ln(1.4)
        pdf.set_font(fam, style="B", size=BODY_PT)
        pdf.set_text_color(22, 32, 44)
        pdf.multi_cell(0, lh, text, new_x="LMARGIN", new_y="NEXT")

    def dim(text):
        pdf.set_font(fam, size=BODY_PT)
        pdf.set_text_color(138, 148, 162)
        pdf.multi_cell(0, LINE_H, text, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(22, 32, 44)

    # 主标题：唯一比正文大的部分
    pdf.set_font(fam, style="B", size=17)
    pdf.set_text_color(22, 32, 44)
    pdf.multi_cell(0, 11, c["title"], new_x="LMARGIN", new_y="NEXT")
    dim(f"[{c['kind']}记录 · 导出于 {c['exported_at']} · {APP_NAME}]")
    pdf.ln(1)

    if c["fields"]:
        for k, v in c["fields"]:
            y0 = pdf.get_y()
            pdf.set_font(fam, style="B", size=BODY_PT)
            pdf.cell(32, LINE_H, f"{k}：")
            pdf.set_font(fam, size=BODY_PT)
            pdf.multi_cell(0, LINE_H, v, new_x="LMARGIN", new_y="NEXT")
            if pdf.get_y() - y0 < LINE_H:
                pdf.ln(LINE_H)
        pdf.ln(1)

    if c["image_png"] or c["image_svg"]:
        try:
            w = 110 if c["kind"] == "样品" else 170
            x = (pdf.w - w) / 2
            if c["image_svg"]:                     # PDF 用矢量图，无限清晰
                pdf.image(io.BytesIO(c["image_svg"].encode("utf-8")), x=x, w=w)
            else:
                pdf.image(io.BytesIO(c["image_png"]), x=x, w=w)
            dim(c["image_caption"])
        except Exception:
            try:                                   # SVG 失败退回 PNG
                w = 110 if c["kind"] == "样品" else 170
                x = (pdf.w - w) / 2
                pdf.image(io.BytesIO(c["image_png"]), x=x, w=w)
                dim(c["image_caption"])
            except Exception:
                pass

    style_b = FontFace(family=fam, emphasis="BOLD", size_pt=BODY_PT,
                       fill_color=(228, 236, 246))
    if c["comps"]:
        head("组成")
        # 五列合计须 ≤ 178mm（A4 宽 210 − 左右边距 16×2），超了会被裁掉
        widths = (26, 74, 22, 34, 22)
        aligns = ("CENTER", "CENTER", "CENTER", "CENTER", "CENTER")
        pdf.set_font(fam, size=BODY_PT)
        with pdf.table(col_widths=widths, text_align=aligns,
                       headings_style=style_b, line_height=6.0,
                       padding=1.5) as table:
            hr = table.row()
            for t in c["comps"]["head"]:
                hr.cell(t)
            for vals in c["comps"]["rows"]:
                row = table.row()
                for v in vals:
                    row.cell(_s(v))
        if c["summary"]:
            pdf.set_font(fam, size=BODY_PT)
            pdf.set_text_color(26, 127, 55)
            pdf.multi_cell(0, LINE_H, c["summary"],
                           new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(22, 32, 44)
        pdf.ln(2)

    if c["procedure"]:
        head("操作")
        pdf.set_font(fam, size=BODY_PT)
        pdf.multi_cell(0, LINE_H, c["procedure"], new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    blocks = [b for b in (c.get("blocks") or [])
              if b.get("text") or b.get("kind") == "table"]
    if blocks:
        head("实验笔记")
        for b in blocks:
            if b["kind"] == "table" and b.get("cols"):
                ncol = max(1, len(b["cols"]))
                w = round(178.0 / ncol, 1)
                pdf.set_font(fam, size=BODY_PT)
                with pdf.table(col_widths=[w] * ncol,
                               text_align=["CENTER"] * ncol,
                               headings_style=style_b, line_height=6.0,
                               padding=1.5) as table:
                    hr = table.row()
                    for t in b["cols"]:
                        hr.cell(t)
                    for vals in b["rows"]:
                        row = table.row()
                        for v in vals:
                            row.cell(_s(v))
                pdf.ln(1.5)
                continue
            if b["kind"] == "step" and b.get("head"):
                pdf.set_font(fam, style="B", size=BODY_PT)
                pdf.multi_cell(0, LINE_H, b["head"],
                               new_x="LMARGIN", new_y="NEXT")
                if b.get("body"):
                    pdf.set_font(fam, size=BODY_PT)
                    pdf.multi_cell(0, LINE_H, b["body"],
                                   new_x="LMARGIN", new_y="NEXT")
            else:
                prefix = {"chem": "结构：", "calc": ""}.get(b["kind"], "")
                pdf.set_font(fam, size=BODY_PT)
                pdf.multi_cell(0, LINE_H, prefix + (b.get("text") or ""),
                               new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        pdf.ln(1)

    if c["note"]:
        head("备注")
        pdf.set_font(fam, size=BODY_PT)
        pdf.multi_cell(0, LINE_H, c["note"], new_x="LMARGIN", new_y="NEXT")

    if c.get("att_paths"):
        head("附件")
        pdf.set_font(fam, size=BODY_PT)
        for nm, p in c["att_paths"]:
            line = p if os.path.basename(p) == nm else f"{nm}：{p}"
            pdf.multi_cell(0, LINE_H, line, new_x="LMARGIN", new_y="NEXT")

    pdf.output(path)
    return path
