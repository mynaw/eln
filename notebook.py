# -*- coding: utf-8 -*-
"""实验笔记：Jupyter 那种「一块一块」的记法，但内容是化学的。

一条记录（样品或反应）挂一串顺序排列的块，五类：

    text   文本    Markdown：# 标题、- 列表、**粗体**、`代码`、> 引用
    step   步骤    标题 + 用时 + 正文 + 完成勾选
    chem   化学    一个 SMILES，实时画结构式
    table  表格    行列随便加，记时间点 / 温度 / 转化率这种
    calc   计算    能算数，也能调 mw() / mol() / yld()，变量在块之间共享

交互照着 Jupyter 的习惯来：Ctrl+Enter 运行当前块（文本块就是渲染），
Shift+Enter 运行并在下面接一个文本块，全部运行会把计算块从上往下跑一遍。

设计取舍：
  - 内容存 JSON 进 blocks 表，纯文本可检索，换机器拷 eln.db 就带走。
  - 不嵌 WebView、不引第三方编辑器，Tkinter 原生控件，离线可用。
  - 计算块用受限命名空间（无 __builtins__），能算数就够了，不做脚本引擎。
"""
from __future__ import annotations

import base64
import html
import json
import math
import os
import re
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from PIL import ImageTk

import chem
try:                           # CAS 解析是可选能力，缺了不影响 SMILES / 绘制
    import caslookup
except Exception:
    caslookup = None

try:                       # 开源 Markdown 实现：表格、围栏代码、语法高亮都交给它
    import markdown as _markdown
except Exception:          # 没装就退回内置解析，功能不受影响
    _markdown = None

try:
    from pygments.formatters import HtmlFormatter as _HtmlFormatter
except Exception:
    _HtmlFormatter = None

from paths import app_dir
from store import data_root

HERE = app_dir()

UI = "Microsoft YaHei UI"
MONO = UI   # 字体统一：等宽位也用同一族
# 正文与界面统一用同一字体（原先西文 Times New Roman / 中文宋体）。
# 本机没有 FontLink 注册表，TNR 不会自动回退中文，故渲染时逐字切到宋体标签。
F_LATIN = UI
F_CJK = UI
CONTENT_SIZE = 10  # 与详情面板、组成表统一

BG = "#f4f6f9"
CARD = "#ffffff"
INK = "#16202c"
DIM = "#6b7684"
ACCENT = "#1f6feb"
GREEN = "#1a7f4b"
RED = "#c0392b"
LINE = "#dde3ea"
CHIP_BG = "#f1f4f9"

KINDS = {"text": "文本", "step": "步骤", "chem": "化学",
         "table": "表格", "calc": "计算"}
KIND_COLORS = {"text": ("#eef2f8", "#3b556f"), "step": ("#e8f4ec", GREEN),
               "chem": ("#ede7f6", "#6a4fa3"), "table": ("#fff4e5", "#a06a1b"),
               "calc": ("#e7f0ff", ACCENT)}
KIND_HINT = {
    "text": "Markdown：# 标题、- 列表、**粗体**、`代码`、> 引用",
    "step": "一步一条，勾上表示已做完",
    "chem": "SMILES / CAS / 简写，回车或「出图」出结构式；「画」打开绘图窗口",
    "table": "记时间点、温度、转化率这类数据",
    "calc": "mw(\"CCO\") · mol(质量, 分子量) · yld(实测, 理论) · 变量块间共享",
}

PLACEHOLDER_CHEM = "（填 SMILES 或 CAS，如 c1ccccc1 / 50-00-0；点「画」打开绘图窗口）"


# ---------------------------------------------------------------- 数据

def default_content(kind: str) -> dict:
    if kind == "step":
        return {"title": "", "body": "", "time": "", "done": False}
    if kind == "chem":
        return {"smiles": "", "caption": ""}
    if kind == "table":
        return {"cols": ["项目", "数值", "单位"],
                "rows": [["", "", ""], ["", "", ""]]}
    if kind == "calc":
        return {"expr": "", "note": "", "result": ""}
    return {"md": ""}


def load_content(row) -> dict:
    """把数据库行里的 JSON 读成字典，缺字段用默认值补齐。"""
    kind = row["kind"] or "text"
    base = default_content(kind)
    try:
        data = json.loads(row["content"] or "{}")
    except Exception:
        data = {}
    if isinstance(data, dict):
        for k in base:
            if k in data and isinstance(data[k], type(base[k]) if base[k] is not None else object):
                base[k] = data[k]
        # 表格的 cols / rows 允许空列表，但元素得是 list
        if kind == "table":
            cols = data.get("cols")
            rows = data.get("rows")
            if isinstance(cols, list) and cols and all(isinstance(c, str) for c in cols):
                base["cols"] = cols
            if isinstance(rows, list) and all(isinstance(r, list) for r in rows):
                base["rows"] = rows
    return base


def dump_content(content: dict) -> str:
    return json.dumps(content, ensure_ascii=False)


def _clip(text: str, width: int = 34) -> str:
    """按显示宽度截断：中文/全角算 2，ASCII 算 1。"""
    out, used = [], 0
    for ch in text:
        cw = 2 if ord(ch) > 0x2E80 else 1
        if used + cw > width:
            return "".join(out) + "…"
        out.append(ch)
        used += cw
    return text


def _clip_px(text: str, max_px: int, font=("Microsoft YaHei UI", 9)) -> str:
    """按像素截断。Treeview 不会自己加省略号，只能先量宽。"""
    from tkinter import font as tkfont
    try:
        f = tkfont.Font(font=font)
        if f.measure(text) <= max_px:
            return text
        out = ""
        for ch in text:
            if f.measure(out + ch + "…") > max_px:
                break
            out += ch
        return out + "…"
    except Exception:
        return _clip(text, 26)


def summary(kind: str, content: dict) -> str:
    """目录 / 详情里用的一行摘要。"""
    if kind == "text":
        md = content.get("md", "")
        head = next((l.strip(" #>*-") for l in md.split("\n") if l.strip()), "")
        return head or "（空文本块）"
    if kind == "step":
        return content.get("title") or "（未命名步骤）"
    if kind == "chem":
        return content.get("caption") or content.get("smiles") or "（空结构）"
    if kind == "table":
        return f"{len(content.get('rows', []))} 行 × {len(content.get('cols', []))} 列"
    if kind == "calc":
        return content.get("expr") or "（空计算）"
    return ""


# ---------------------------------------------------------------- Markdown

def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    # 基础拉丁 / 希腊字母交给 TNR（TNR 自带）；其余（汉字、CJK 标点、全角、
    # 常用符号 ℃、箭头 →、数学符 ±×≈、带圈数字 ① 等）交给宋体（覆盖更全）。
    return (0x2E80 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or
            0xFF00 <= o <= 0xFFEF or 0x3000 <= o <= 0x303F or
            0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x4DBF or
            0xAC00 <= o <= 0xD7AF or
            0x2000 <= o <= 0x214F or 0x2190 <= o <= 0x23FF or
            0x2460 <= o <= 0x24FF)


def insert_mixed(txt: tk.Text, text: str, tag: str, cjk_tag: str | None = None):
    """按 CJK / 非 CJK 拆成连续段插入：中文用 cjk_tag（宋体），其余用 tag（TNR）。
    cjk_tag 为 None 时（如行内代码）整段都用 tag。"""
    if not text:
        return
    if cjk_tag is None:
        txt.insert("end", text, (tag,))
        return
    run, run_is_cjk = "", None

    def flush():
        nonlocal run, run_is_cjk
        if not run:
            return
        txt.insert("end", run, (tag, cjk_tag) if run_is_cjk else (tag,))
        run = ""

    for ch in text:
        c = _is_cjk(ch)
        if run_is_cjk is None:
            run_is_cjk, run = c, ch
        elif c == run_is_cjk:
            run += ch
        else:
            flush()
            run_is_cjk, run = c, ch
    flush()


def configure_md_tags(txt: tk.Text):
    """正文样式：西文 Times New Roman、中文强制宋体（SimSun），逐字切换标签。

    本机没有 FontLink 注册表，TNR 不会自动回退中文，故每个段落 tag 都配一个
    `_cjk` 伴侣 tag：二者排版/尺寸完全一致，仅字体族不同（西文 TNR / 中文宋体）。
    """
    def _pair(name, size, weight, fg, lm1, lm2, sp1, sp3, bg=None):
        kw = dict(font=(F_LATIN, size, weight), lmargin1=lm1, lmargin2=lm2,
                  spacing1=sp1, spacing3=sp3, justify="left")
        if fg:
            kw["foreground"] = fg
        if bg:
            kw["background"] = bg
        txt.tag_configure(name, **kw)
        kw["font"] = (F_CJK, size, weight)          # 中文伴侣：换宋体
        txt.tag_configure(name + "_cjk", **kw)

    specs = [
        ("h1", 18, "bold", "#0f1b26", 0, 0, 4, 8),
        ("h2", 15, "bold", "#16202c", 0, 0, 8, 6),
        ("h3", 13, "bold", "#2b3a4d", 0, 0, 6, 4),
        ("p", CONTENT_SIZE, "normal", None, 0, 0, 0, 6),
        ("p_b", CONTENT_SIZE, "bold", None, 0, 0, 0, 6),
        ("p_i", CONTENT_SIZE, "italic", None, 0, 0, 0, 6),
        ("li", CONTENT_SIZE, "normal", None, 18, 32, 0, 3),
        ("li_b", CONTENT_SIZE, "bold", None, 18, 32, 0, 3),
        ("li_i", CONTENT_SIZE, "italic", None, 18, 32, 0, 3),
        ("quote", CONTENT_SIZE, "normal", "#44546a", 14, 28, 0, 5),
        ("quote_b", CONTENT_SIZE, "bold", "#44546a", 14, 28, 0, 5),
        ("quote_i", CONTENT_SIZE, "italic", "#44546a", 14, 28, 0, 5),
    ]
    for name, size, weight, fg, lm1, lm2, sp1, sp3 in specs:
        _pair(name, size, weight, fg, lm1, lm2, sp1, sp3)

    # 行内代码 / 代码块：等宽字体，基本是 ASCII，不切中文
    txt.tag_configure("code", font=(MONO, 9), background="#f3f5f8",
                      lmargin1=12, lmargin2=12, spacing1=2, spacing3=2)
    txt.tag_configure("p_c", font=(MONO, 9), background="#eef2f8",
                      lmargin1=0, lmargin2=0, spacing3=6)
    txt.tag_configure("li_c", font=(MONO, 9), background="#eef2f8",
                      lmargin1=18, lmargin2=32, spacing3=3)
    txt.tag_configure("quote_c", font=(MONO, 9), background="#eef2f8",
                      lmargin1=14, lmargin2=28, spacing3=5)
    # 分隔线用等宽字体保证「─」能画出来（TNR 不含制表框线）
    txt.tag_configure("hr", font=(MONO, 8), foreground="#c8d2dd",
                      spacing1=6, spacing3=8)
    txt.tag_configure("gap", font=(F_LATIN, 4), spacing3=2)


def _rich(txt: tk.Text, text: str, base: str, prefix: str = ""):
    if prefix:
        insert_mixed(txt, prefix, base, base + "_cjk")
    for part in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)", text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            insert_mixed(txt, part[2:-2], base + "_b", base + "_b_cjk")
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            insert_mixed(txt, part[1:-1], base + "_i", base + "_i_cjk")
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            txt.insert("end", part[1:-1], (base + "_c",))
        else:
            insert_mixed(txt, part, base, base + "_cjk")
    txt.insert("end", "\n", (base,))


def render_md(txt: tk.Text, md: str):
    """把一小段 Markdown 画进 Text。支持标题/列表/有序列表/引用/代码块/分隔线。"""
    in_code, buf = False, []
    for raw in (md or "").split("\n"):
        line = raw.rstrip()
        if line.strip().startswith("```"):
            if in_code:
                txt.insert("end", ("\n".join(buf) or " ") + "\n", "code")
                buf = []
            in_code = not in_code
            continue
        if in_code:
            buf.append(line)
            continue
        s = line.strip()
        if not s:
            txt.insert("end", "\n", "gap")
        elif s.startswith("---") and set(s) <= set("- "):
            txt.insert("end", "─" * 46 + "\n", "hr")
        elif s.startswith("### "):
            insert_mixed(txt, s[4:].strip(), "h3", "h3_cjk")
            txt.insert("end", "\n")
        elif s.startswith("## "):
            insert_mixed(txt, s[3:].strip(), "h2", "h2_cjk")
            txt.insert("end", "\n")
        elif s.startswith("# "):
            insert_mixed(txt, s[2:].strip(), "h1", "h1_cjk")
            txt.insert("end", "\n")
        elif s.startswith(("- ", "* ", "· ")):
            _rich(txt, s[2:], "li", "· ")
        elif re.match(r"^\d+[.)]\s", s):
            m = re.match(r"^(\d+[.)])\s+(.*)$", s)
            _rich(txt, m.group(2), "li", m.group(1) + " ")
        elif s.startswith(">"):
            _rich(txt, s[1:].strip(), "quote", "▎ ")
        else:
            _rich(txt, s, "p")
    if in_code and buf:
        txt.insert("end", "\n".join(buf) + "\n", "code")


class MarkdownView(tk.Text):
    """只读的 Markdown 预览，高度跟着内容自己长。"""

    def __init__(self, master, bg=CARD, **kw):
        super().__init__(master, wrap="char", bd=0, relief="flat", bg=bg, fg=INK,
                         font=(F_LATIN, CONTENT_SIZE), padx=0, pady=0, cursor="arrow",
                         height=1, spacing1=1, spacing3=2,
                         selectbackground="#d7e6ff", **kw)
        configure_md_tags(self)
        self._width = 0
        self._fitting = False
        self.bind("<Configure>", self._on_conf)

    def set_md(self, md: str):
        self.configure(state="normal")
        self.delete("1.0", "end")
        render_md(self, md)
        self.configure(state="disabled")
        self.after_idle(self.fit)
        self.after(60, self.fit)        # 换行要在布局定下来之后才算得准
        self.after(200, self.fit)       # 窗口刚开时宽度会变两次，再来一遍收敛

    def fit(self):
        # 注意：这里别调 update_idletasks——fit 本身就是在 idle 回调里跑的，
        # 再强制刷新 idle 队列会递归，窗口直接卡死。
        if self._fitting:
            return
        self._fitting = True
        try:
            # 行高按像素算：段落带 spacing1/spacing3，只数行数会切掉最后一行的下半截。
            # 取倒数第二个字符的显示行（末尾的 \n 会多出一个空行，算进去就多一行的空白）。
            info = self.dlineinfo("end-2c") or self.dlineinfo("end-1c")
            need = 0
            if info:
                from tkinter import font as tkfont
                lh = tkfont.Font(font=self.cget("font")).metrics("linespace") or 20
                # dlineinfo 的第 4 项含段后间距，拿它算会多出一行空白；
                # 用基线（第 5 项）当文字底边，再加 2px 余量。
                bottom = info[1] + (info[4] or info[3] * 0.6) + 2
                need = math.ceil(bottom / lh)
            if not need:
                n = self.count("1.0", "end-1c", "displaylines")
                need = int(n[0] if isinstance(n, tuple) else n or 1)
            if need and int(need) != int(self.cget("height")):
                self.configure(height=max(1, int(need)))
        except Exception:
            pass
        finally:
            self._fitting = False

    def _on_conf(self, event):
        if abs(event.width - self._width) > 4:
            self._width = event.width
            self.after(40, self.fit)


# ---------------------------------------------------------------- 计算

_MW_CACHE: dict[str, float] = {}


def molar_mass(smiles: str) -> float:
    """SMILES / molfile -> 分子量。算不出来就报错，别默默返回 0。"""
    key = (smiles or "").strip()
    if not key:
        raise ValueError("mw() 需要一个 SMILES")
    if key in _MW_CACHE:
        return _MW_CACHE[key]
    info = chem.analyze(key)
    if "error" in info:
        raise ValueError(f"结构解析不了：{key}")
    _MW_CACHE[key] = float(info["mw"])
    return float(info["mw"])


def calc_namespace() -> dict:
    ns: dict = {"__builtins__": {}}
    for name in dir(math):
        if not name.startswith("_"):
            ns[name] = getattr(math, name)
    ns.update({
        "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
        "len": len, "float": float, "int": int, "str": str,
        "mw": molar_mass,
        "mol": lambda mass, mw: mass / mw if mw else float("nan"),
        "yld": lambda actual, theoretical: (actual / theoretical * 100.0
                                            if theoretical else float("nan")),
    })
    return ns


def fmt_value(v) -> str:
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        if v != v:
            return "nan"
        return f"{v:.6g}"
    if isinstance(v, int):
        return str(v)
    return str(v)


def eval_calc(expr: str, ns: dict) -> tuple[str, str]:
    """跑一条计算。返回 (结果文本, 错误文本)，两者必有一个为空。"""
    text = (expr or "").strip()
    if not text:
        return "", ""
    for line in text.split("\n"):
        if "import" in line or "__" in line:
            return "", "计算块不执行 import / 双下划线，只做算式"
    try:
        value = eval(compile(text, "<calc>", "eval"), ns, ns)
    except SyntaxError:
        try:
            exec(compile(text, "<calc>", "exec"), ns, ns)
        except Exception as e:                     # noqa: BLE001
            return "", f"{type(e).__name__}: {e}"
        m = re.match(r"\s*([A-Za-z_]\w*)\s*=", text)
        if m and m.group(1) in ns:
            return fmt_value(ns[m.group(1)]), ""
        return "已执行", ""
    except Exception as e:                         # noqa: BLE001
        return "", f"{type(e).__name__}: {e}"
    return fmt_value(value), ""


# ---------------------------------------------------------------- 导出

def _blocks_of(store, owner_type: str, owner_id: int):
    return [(b["kind"], load_content(b)) for b in store.blocks(owner_type, owner_id)]


def to_markdown(title: str, blocks) -> str:
    out = [f"# {title}", ""]
    n_step = 0
    for kind, c in blocks:
        if kind == "text":
            out += [c.get("md", ""), ""]
        elif kind == "step":
            n_step += 1
            tag = "（已完成）" if c.get("done") else ""
            head = f"### 步骤 {n_step} · {c.get('title') or '未命名'}{tag}"
            out.append(head)
            if c.get("time"):
                out.append(f"- 用时：{c['time']}")
            if c.get("body"):
                out += ["", c["body"]]
            out.append("")
        elif kind == "chem":
            out.append(f"**结构**　`{c.get('smiles', '')}`")
            if c.get("caption"):
                out.append(f"\n{c['caption']}")
            out.append("")
        elif kind == "table":
            cols = c.get("cols") or []
            rows = c.get("rows") or []
            if cols:
                out.append("| " + " | ".join(cols) + " |")
                out.append("|" + "|".join(["---"] * len(cols)) + "|")
                for row in rows:
                    cells = [str(x) for x in row] + [""] * (len(cols) - len(row))
                    out.append("| " + " | ".join(cells[:len(cols)]) + " |")
                out.append("")
        elif kind == "calc":
            out.append("```")
            out.append(c.get("expr", ""))
            out.append("```")
            if c.get("note"):
                out.append(f"<sub>{c['note']}</sub>")
            if c.get("result"):
                out.append(f"→ `{c['result']}`")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


_MD_INLINE = re.compile(r"\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`")

MD_EXTENSIONS = ["tables", "fenced_code", "sane_lists"] + (
    ["codehilite"] if _HtmlFormatter is not None else [])


def md_to_html(text: str) -> str:
    """Markdown -> HTML。

    有 Python-Markdown 就用它（表格、围栏代码、Pygments 高亮都是现成的，
    行内样式写进标签，导出的 HTML 不依赖外部 CSS）；没装就退回内置解析。
    """
    if _markdown is None:
        return _md_html(text)
    try:
        return _markdown.markdown(
            text or "", extensions=MD_EXTENSIONS,
            extension_configs={"codehilite": {"noclasses": True,
                                              "pygments_style": "friendly"}})
    except Exception:
        return _md_html(text)
def _inline_html(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", text)


def _md_html(md: str) -> str:
    out, in_code, buf = [], False, []
    for raw in (md or "").split("\n"):
        line = raw.rstrip()
        if line.strip().startswith("```"):
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(buf)) + "</code></pre>")
                buf = []
            in_code = not in_code
            continue
        if in_code:
            buf.append(line)
            continue
        s = line.strip()
        if not s:
            continue
        if s.startswith("---") and set(s) <= set("- "):
            out.append("<hr>")
        elif s.startswith("### "):
            out.append(f"<h4>{_inline_html(s[4:])}</h4>")
        elif s.startswith("## "):
            out.append(f"<h3>{_inline_html(s[3:])}</h3>")
        elif s.startswith("# "):
            out.append(f"<h2>{_inline_html(s[2:])}</h2>")
        elif s.startswith(("- ", "* ")):
            out.append(f"<li>{_inline_html(s[2:])}</li>")
        elif re.match(r"^\d+[.)]\s", s):
            out.append(f"<li>{_inline_html(s)}</li>")
        elif s.startswith(">"):
            out.append(f"<blockquote>{_inline_html(s[1:].strip())}</blockquote>")
        else:
            out.append(f"<p>{_inline_html(s)}</p>")
    if in_code and buf:
        out.append("<pre><code>" + html.escape("\n".join(buf)) + "</code></pre>")
    return "\n".join(out)


def to_html(title: str, blocks, subtitle: str = "") -> str:
    body = []
    n_step = 0
    for kind, c in blocks:
        if kind == "text":
            body.append(md_to_html(c.get("md", "")))
        elif kind == "step":
            n_step += 1
            done = " done" if c.get("done") else ""
            meta = f"<span class='meta'>{html.escape(c.get('time') or '')}</span>"
            body.append(
                f"<div class='step{done}'><div class='steptitle'>"
                f"<span class='badge'>{n_step}</span>"
                f"{html.escape(c.get('title') or '未命名')}{meta}</div>"
                f"<div class='stepbody'>{_md_html(c.get('body', ''))}</div></div>")
        elif kind == "chem":
            img = ""
            try:
                mol = chem.load(c.get("smiles", ""))
                pic = chem.render(mol, 420, 300) if mol is not None else None
                if pic is not None:
                    import io
                    bio = io.BytesIO()
                    pic.save(bio, format="PNG")
                    b64 = base64.b64encode(bio.getvalue()).decode("ascii")
                    img = (f"<img src='data:image/png;base64,{b64}' "
                           f"alt='structure' width='420'>")
            except Exception:
                img = ""
            cap = html.escape(c.get("caption") or c.get("smiles", ""))
            body.append(f"<figure>{img}<figcaption>{cap}</figcaption></figure>")
        elif kind == "table":
            cols = c.get("cols") or []
            rows = c.get("rows") or []
            if cols:
                head = "".join(f"<th>{html.escape(str(x))}</th>" for x in cols)
                trs = []
                for row in rows:
                    cells = [str(x) for x in row] + [""] * (len(cols) - len(row))
                    trs.append("<tr>" + "".join(
                        f"<td>{html.escape(x)}</td>" for x in cells[:len(cols)]) + "</tr>")
                body.append(f"<table><thead><tr>{head}</tr></thead>"
                            f"<tbody>{''.join(trs)}</tbody></table>")
        elif kind == "calc":
            note = f"<div class='note'>{html.escape(c.get('note', ''))}</div>" if c.get("note") else ""
            res = f"<div class='result'>→ {html.escape(c.get('result', ''))}</div>" if c.get("result") else ""
            body.append(f"<div class='calc'><pre>{html.escape(c.get('expr', ''))}</pre>"
                        f"{note}{res}</div>")

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
 body {{ font-family: "Microsoft YaHei", "Segoe UI", sans-serif; line-height: 1.8;
        max-width: 860px; margin: 40px auto; padding: 0 24px; color: #16202c; }}
 h1 {{ font-size: 28px; border-bottom: 3px solid #1f6feb; padding-bottom: 10px; }}
 h2 {{ font-size: 21px; margin-top: 30px; }}
 h3 {{ font-size: 17px; margin-top: 24px; }}
 h4 {{ font-size: 15px; margin-top: 18px; }}
 .sub {{ color: #6b7684; font-size: 13px; margin-bottom: 26px; }}
 code {{ font-family: Consolas, monospace; background: #eef2f8; padding: 1px 4px;
         border-radius: 3px; font-size: 13px; }}
 pre {{ background: #f6f8fb; border-left: 3px solid #1f6feb; padding: 10px 14px;
        overflow-x: auto; border-radius: 4px; font-size: 13px; }}
 li {{ margin: 3px 0; }}
 blockquote {{ margin: 10px 0; padding: 6px 14px; border-left: 3px solid #c8d2dd;
               color: #44546a; background: #fafbfd; }}
 hr {{ border: 0; border-top: 1px solid #e3e8ef; margin: 26px 0; }}
 .step {{ border: 1px solid #dde3ea; border-radius: 6px; padding: 12px 16px;
          margin: 12px 0; background: #fcfdfe; }}
 .step.done {{ background: #f6faf7; border-color: #cfe6d8; }}
 .steptitle {{ font-weight: 700; font-size: 15px; }}
 .badge {{ display: inline-block; padding: 1px 7px; border-radius: 10px;
           background: #1f6feb; color: #fff; font-size: 12px; margin-right: 8px; }}
 .meta {{ color: #6b7684; font-weight: 400; font-size: 12px; margin-left: 10px; }}
 .stepbody p {{ margin: 6px 0 0; }}
 table {{ border-collapse: collapse; margin: 14px 0; width: 100%; }}
 th, td {{ border: 1px solid #dde3ea; padding: 6px 10px; text-align: left;
           font-size: 14px; }}
 th {{ background: #f4f6f9; }}
 figure {{ margin: 14px 0; }}
 figure img {{ max-width: 420px; }}
 figcaption {{ color: #6b7684; font-size: 13px; }}
 .calc pre {{ border-left-color: #1a7f4b; background: #f7fbf8; }}
 .codehilite {{ margin: 10px 0; border-radius: 4px; }}
 .codehilite pre {{ margin: 0; }}
 .note {{ color: #6b7684; font-size: 12px; }}
 .result {{ font-family: Consolas, monospace; color: #1a7f4b; font-weight: 700; }}
</style></head><body>
<h1>{html.escape(title)}</h1>
<div class="sub">{html.escape(subtitle)}</div>
{''.join(body)}
</body></html>"""


# ---------------------------------------------------------------- 滚动容器

class _ScrollArea(tk.Frame):
    def __init__(self, master, bg=BG):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.sb.pack(side="right", fill="y")
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _on_body(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)

    def _wheel(self, event):
        w = event.widget
        if isinstance(w, tk.Text):
            first, last = w.yview()
            if (first, last) != (0.0, 1.0):        # 文本自己还能滚，别抢
                return
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def scroll_to(self, widget):
        total = max(1, self.body.winfo_reqheight())
        self.canvas.yview_moveto(max(0.0, widget.winfo_y() - 12) / total)


# ---------------------------------------------------------------- 单个块

class CellCard:
    """一块的界面：标题条 + 正文（编辑 / 预览）。"""

    def __init__(self, nb, row, index: int):
        self.nb = nb
        self.bid = row["id"]
        self.kind = row["kind"] or "text"
        self.content = load_content(row)
        self.index = index
        self.showing = "edit"
        self._imgs: list = []
        self._rebuilding = False
        self._cas_result = None              # CAS 后台线程 -> 主线程的结果槽

        self.frame = tk.Frame(nb.area.body, bg=CARD, highlightthickness=1,
                              highlightbackground=LINE)
        self.frame.pack(fill="x", padx=(4, 10), pady=(0, 8))

        self._header()
        self.body = tk.Frame(self.frame, bg=CARD)
        self.body.pack(fill="x", padx=14, pady=(0, 12))
        self._build_body()

        # 默认：有内容的文本/步骤块直接给预览，空的进编辑
        if self.kind in ("text", "step") and self._has_content():
            self._set_mode("preview")
        else:
            self._set_mode("edit")

    # ------------------------------------------------------------ 头部
    def _header(self):
        bar = tk.Frame(self.frame, bg=CARD)
        bar.pack(fill="x", padx=12, pady=(8, 4))

        tk.Label(bar, text=f"{self.index:02d}", bg=CARD, fg="#b3bec9",
                 font=(MONO, 9)).pack(side="left", padx=(0, 8))

        bg, fg = KIND_COLORS.get(self.kind, (CHIP_BG, INK))
        tk.Label(bar, text=KINDS.get(self.kind, self.kind), bg=bg, fg=fg,
                 font=(UI, 8, "bold"), padx=7, pady=1).pack(side="left")

        ops = tk.Frame(bar, bg=CARD)
        ops.pack(side="right")
        for text, cmd, color in (("删除", self.on_delete, RED),
                                 ("复制", self.on_duplicate, DIM),
                                 ("▼", lambda: self.on_move(1), DIM),
                                 ("▲", lambda: self.on_move(-1), DIM)):
            tk.Button(ops, text=text, command=cmd, relief="flat", bd=0, bg=CARD,
                      fg=color, font=(UI, 8), cursor="hand2",
                      padx=4).pack(side="right", padx=1)

        self.toggle = None
        if self.kind in ("text", "step"):
            self.toggle = tk.Button(ops, text="编辑", command=self.on_toggle,
                                    relief="flat", bd=0, bg=CARD, fg=ACCENT,
                                    font=(UI, 8), cursor="hand2", padx=6)
            self.toggle.pack(side="right", padx=(0, 4))

    def _has_content(self):
        c = self.content
        if self.kind == "text":
            return bool((c.get("md") or "").strip())
        if self.kind == "step":
            return bool((c.get("title") or "").strip() or (c.get("body") or "").strip())
        return False

    def _set_mode(self, mode: str):
        """edit / preview 互斥显示。"""
        if self.kind not in ("text", "step"):
            return
        self.showing = mode
        if mode == "preview":
            self.edit_frame.pack_forget()
            self.preview_frame.pack(fill="x")
            if self.toggle:
                self.toggle.configure(text="编辑")
            self.refresh_preview()
        else:
            self.preview_frame.pack_forget()
            self.edit_frame.pack(fill="x")
            if self.toggle:
                self.toggle.configure(text="预览")
        self.after_fit()

    def after_fit(self):
        for view in getattr(self, "_views", []):
            view.after_idle(view.fit)

    # ------------------------------------------------------------ 正文
    def _build_body(self):
        self._views = []
        if self.kind == "text":
            self._build_text()
        elif self.kind == "step":
            self._build_step()
        elif self.kind == "chem":
            self._build_chem()
        elif self.kind == "table":
            self._build_table()
        elif self.kind == "calc":
            self._build_calc()

    def _hint(self, parent, text):
        tk.Label(parent, text=text, bg=CARD, fg="#9aa6b3", font=(UI, 8),
                 anchor="w").pack(fill="x", pady=(3, 0))

    # ---- 文本
    def _build_text(self):
        self.edit_frame = tk.Frame(self.body, bg=CARD)
        self.txt = tk.Text(self.edit_frame, height=6, wrap="char", bd=1,
                           relief="solid", bg="#fcfdfe", fg=INK, font=(UI, 10),
                           padx=10, pady=8, spacing1=1, spacing3=2,
                           insertbackground=ACCENT)
        self.txt.pack(fill="x")
        self.txt.insert("1.0", self.content.get("md", ""))
        self.txt.bind("<KeyRelease>", lambda e: self.nb.schedule_save())
        self.txt.bind("<Control-Return>", lambda e: (self.on_run(), "break")[1])
        self.txt.bind("<Shift-Return>", lambda e: (self.on_run_then_new(), "break")[1])
        self._hint(self.edit_frame, KIND_HINT["text"])

        self.preview_frame = tk.Frame(self.body, bg=CARD)
        self.preview = MarkdownView(self.preview_frame)
        self.preview.pack(fill="x")
        self.preview.bind("<Double-1>", lambda e: self._set_mode("edit"))
        self._views.append(self.preview)

    # ---- 步骤
    def _build_step(self):
        c = self.content
        self.edit_frame = tk.Frame(self.body, bg=CARD)

        top = tk.Frame(self.edit_frame, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text="标题", bg=CARD, fg=DIM, font=(UI, 9)).pack(side="left")
        self.st_title = tk.Entry(top, font=(UI, 10), bd=1, relief="solid",
                                 bg="#fcfdfe", fg=INK)
        self.st_title.pack(side="left", fill="x", expand=True, padx=(6, 10), ipady=3)
        self.st_title.insert(0, c.get("title", ""))
        tk.Label(top, text="用时", bg=CARD, fg=DIM, font=(UI, 9)).pack(side="left")
        self.st_time = tk.Entry(top, width=10, font=(UI, 10), bd=1, relief="solid",
                                bg="#fcfdfe", fg=INK)
        self.st_time.pack(side="left", padx=(6, 0), ipady=3)
        self.st_time.insert(0, c.get("time", ""))

        self.st_body = tk.Text(self.edit_frame, height=3, wrap="char", bd=1,
                               relief="solid", bg="#fcfdfe", fg=INK, font=(UI, 10),
                               padx=10, pady=8, spacing1=1, spacing3=2,
                               insertbackground=ACCENT)
        self.st_body.pack(fill="x", pady=(6, 0))
        self.st_body.insert("1.0", c.get("body", ""))

        self.st_done = tk.BooleanVar(value=bool(c.get("done")))
        tk.Checkbutton(self.edit_frame, text="这一步已完成", variable=self.st_done,
                       bg=CARD, fg=DIM, font=(UI, 9), activebackground=CARD,
                       cursor="hand2",
                       command=self.nb.schedule_save).pack(anchor="w", pady=(4, 0))

        for w in (self.st_title, self.st_time, self.st_body):
            w.bind("<KeyRelease>", lambda e: self.nb.schedule_save())
            w.bind("<Control-Return>", lambda e: (self.on_run(), "break")[1])
        self._hint(self.edit_frame, KIND_HINT["step"])

        self.preview_frame = tk.Frame(self.body, bg=CARD)
        self.preview = MarkdownView(self.preview_frame)
        self.preview.pack(fill="x")
        self.preview.bind("<Double-1>", lambda e: self._set_mode("edit"))
        self._views.append(self.preview)

    # ---- 化学
    def _build_chem(self):
        c = self.content
        self.edit_frame = None
        self.preview_frame = None

        top = tk.Frame(self.body, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text="SMILES", bg=CARD, fg=DIM, font=(UI, 9)).pack(side="left")
        self.ch_smiles = tk.Entry(top, font=(MONO, 10), bd=1, relief="solid",
                                  bg="#fcfdfe", fg=INK)
        self.ch_smiles.pack(side="left", fill="x", expand=True, padx=(8, 8), ipady=3)
        self.ch_smiles.insert(0, c.get("smiles", ""))
        tk.Button(top, text="出图", command=self.on_chem_render, relief="flat", bd=0,
                  bg="#ede7f6", fg="#6a4fa3", font=(UI, 9), padx=9,
                  cursor="hand2").pack(side="left", padx=(0, 4))
        tk.Button(top, text="画", command=self.on_open_drawpad, relief="flat", bd=0,
                  bg="#e8f4ec", fg=GREEN, font=(UI, 9), padx=9,
                  cursor="hand2").pack(side="left")
        self.ch_smiles.bind("<Return>", lambda e: self.on_chem_render())
        self.ch_smiles.bind("<KeyRelease>", lambda e: self.nb.schedule_save())

        cap = tk.Frame(self.body, bg=CARD)
        cap.pack(fill="x", pady=(6, 0))
        tk.Label(cap, text="图注", bg=CARD, fg=DIM, font=(UI, 9)).pack(side="left")
        self.ch_caption = tk.Entry(cap, font=(UI, 10), bd=1, relief="solid",
                                   bg="#fcfdfe", fg=INK)
        self.ch_caption.pack(side="left", fill="x", expand=True, padx=(8, 0), ipady=3)
        self.ch_caption.insert(0, c.get("caption", ""))
        self.ch_caption.bind("<KeyRelease>", lambda e: self.nb.schedule_save())

        self.ch_img = tk.Label(self.body, bg=CARD, anchor="w", cursor="hand2")
        self.ch_img.pack(anchor="w", pady=(8, 0))
        self.ch_img.bind("<Button-1>", lambda e: self.on_big())
        self.ch_msg = tk.Label(self.body, text="", bg=CARD, fg=RED, font=(UI, 8),
                               anchor="w", justify="left")
        self.ch_msg.pack(fill="x")
        self.on_chem_render(quiet=True)

    def on_chem_render(self, quiet=False):
        """「出图」/ 回车：SMILES、简写或 CAS 号 -> 结构式。

        CAS 走后台线程查（联网），避免卡住界面；解析成功把 SMILES 回填到
        输入框，这样下次打开就是纯离线渲染。
        """
        raw = self.ch_smiles.get().strip()
        try:
            self.content["caption"] = self.ch_caption.get().strip()
        except Exception:
            self.content["caption"] = ""
        if not raw:
            self._clear_chem_image()
            self.ch_img.configure(text=PLACEHOLDER_CHEM, fg=DIM, font=(UI, 9))
            self.ch_msg.configure(
                text="" if quiet else
                "填 SMILES / CAS 后点「出图」或按回车；点「画」打开绘图窗口。",
                fg=RED)
            self.nb.schedule_save()
            return
        if caslookup is not None and caslookup.is_cas(raw):
            self.content["smiles"] = raw
            self._cas_result = None
            self.ch_msg.configure(text=f"正在解析 CAS {raw} …", fg=DIM)
            threading.Thread(target=self._cas_worker, args=(raw,),
                             daemon=True).start()
            # 轮询必须在主线程注册：后台线程直接调 Tk 的 after 不可靠
            self.ch_smiles.after(80, self._poll_cas)
            return
        self._render_smiles(raw)

    def _clear_chem_image(self):
        self.ch_img.configure(image="", text="", fg=DIM)
        self.ch_img.image = None

    def _cas_worker(self, raw):
        """后台查 CAS，只写结果变量；UI 更新交给主线程轮询。"""
        try:
            smi, note = caslookup.resolve(raw)
        except Exception as e:
            smi, note = None, f"{type(e).__name__}: {e}"
        self._cas_result = (raw, smi, note)

    def _poll_cas(self):
        """主线程轮询，把 CAS 解析结果落到界面上。"""
        res = getattr(self, "_cas_result", None)
        if res is None:
            try:
                self.ch_smiles.after(80, self._poll_cas)
            except Exception:
                pass                          # 窗口已关，停止轮询
            return
        self._cas_result = None
        raw, smi, note = res
        try:
            if self.ch_smiles.get().strip() != raw:
                return                        # 用户已改输入，丢掉过期结果
            if not smi:
                self._clear_chem_image()
                self.ch_msg.configure(text=f"CAS {raw} 解析失败：{note}", fg=RED)
                return
            self.ch_smiles.delete(0, "end")
            self.ch_smiles.insert(0, smi)
            self._render_smiles(smi, note)
        except Exception as e:
            try:
                self.ch_msg.configure(text=f"CAS 结果处理失败：{e}", fg=RED)
            except Exception:
                pass

    def _render_smiles(self, smi, note=""):
        """真正出图：SMILES 直接调，CAS 解析完 / 画板回填完也走这里。"""
        smi = (smi or "").strip()
        self.content["smiles"] = smi
        if not smi:
            self._clear_chem_image()
            return
        try:
            pic = chem.render_smiles(smi, 360, 240)
            if pic is None:
                self._clear_chem_image()
                self.ch_msg.configure(
                    text=f"「{smi}」解析不了，检查一下 SMILES / 括号 / 原子符号。",
                    fg=RED)
                self.nb.schedule_save()
                return
            photo = ImageTk.PhotoImage(pic)
            self._imgs.append(photo)
            self.ch_img.configure(image=photo, text="")
            self.ch_img.image = photo
            info = chem.analyze(smi)
            try:
                mw = float(info.get("mw", 0) or 0)
            except (TypeError, ValueError):
                mw = 0.0
            desc = (f"{info.get('formula', '')}　M = {mw:.2f}"
                    if "error" not in info else info["error"])
            if note:
                desc = f"{desc}　·　{note}"
            self.ch_msg.configure(text=desc, fg=DIM)
        except Exception as e:
            self._clear_chem_image()
            self.ch_msg.configure(text=f"出图失败：{type(e).__name__}: {e}", fg=RED)
        self.nb.schedule_save()

    def on_open_drawpad(self):
        """「画」：打开绘图窗口，画完点保存把 SMILES 回填到这个块。

        owner_id=None 让画板只借来回填，不往库里写一张孤儿绘制记录。
        """
        try:
            import drawpad
            smi = self.ch_smiles.get().strip()
            if caslookup is not None and caslookup.is_cas(smi):
                smi = ""                    # CAS 不能直接喂给画板

            def on_smiles(new_smi):
                try:
                    self.ch_smiles.delete(0, "end")
                    self.ch_smiles.insert(0, new_smi)
                    self._render_smiles(new_smi, "绘图窗口")
                except Exception as e:
                    self.ch_msg.configure(text=f"回填结构失败：{e}", fg=RED)

            drawpad.open_drawpad(
                self.nb.win, self.nb.store, self.nb.owner_type, None,
                initial_smiles=smi, on_smiles=on_smiles)
            self.ch_msg.configure(text="绘图窗口已打开，画完点「保存」回填结构。",
                                  fg=DIM)
        except Exception as e:
            self.ch_msg.configure(
                text=f"绘图窗口打不开：{type(e).__name__}: {e}", fg=RED)

    def on_big(self):
        smi = self.ch_smiles.get().strip()
        if not smi:
            self.ch_msg.configure(text="先出一张结构图，再点图放大。", fg=RED)
            return
        if caslookup is not None and caslookup.is_cas(smi):
            self.ch_msg.configure(text="先按回车把 CAS 解析成结构式，再点图放大。", fg=RED)
            return
        self.nb.show_big_structure(smi)

    # ---- 表格
    def _build_table(self):
        self.edit_frame = None
        self.preview_frame = None
        self._tbl_frame = tk.Frame(self.body, bg=CARD)
        self._tbl_frame.pack(fill="x")
        self._render_table()

    def _render_table(self):
        for w in self._tbl_frame.winfo_children():
            w.destroy()
        cols = self.content.setdefault("cols", [])
        rows = self.content.setdefault("rows", [])
        self._col_vars, self._cell_vars = [], []

        for j, cname in enumerate(cols):
            var = tk.StringVar(value=cname)
            e = tk.Entry(self._tbl_frame, textvariable=var, font=(UI, 9, "bold"),
                         bd=1, relief="solid", bg="#eef2f8", fg=INK)
            e.grid(row=0, column=j, sticky="ew", padx=1, pady=1, ipady=2)
            var.trace_add("write", lambda *a: self.nb.schedule_save())
            self._col_vars.append(var)
            self._tbl_frame.columnconfigure(j, weight=1)

        for i, row in enumerate(rows):
            line = []
            for j in range(len(cols)):
                var = tk.StringVar(value=str(row[j]) if j < len(row) else "")
                e = tk.Entry(self._tbl_frame, textvariable=var, font=(UI, 9),
                             bd=1, relief="solid", bg="#fcfdfe", fg=INK)
                e.grid(row=i + 1, column=j, sticky="ew", padx=1, pady=1, ipady=2)
                var.trace_add("write", lambda *a: self.nb.schedule_save())
                line.append(var)
            self._cell_vars.append(line)

        ops = tk.Frame(self.body, bg=CARD)
        ops.pack(fill="x", pady=(4, 0))
        for text, cmd in (("+ 行", lambda: self._tbl_add("row")),
                          ("− 行", lambda: self._tbl_del("row")),
                          ("+ 列", lambda: self._tbl_add("col")),
                          ("− 列", lambda: self._tbl_del("col"))):
            tk.Button(ops, text=text, command=cmd, relief="flat", bd=0, bg=CARD,
                      fg=ACCENT, font=(UI, 8), cursor="hand2",
                      padx=6).pack(side="left")

    def _tbl_collect(self):
        self.content["cols"] = [v.get() for v in self._col_vars]
        rows = []
        for line in self._cell_vars:
            rows.append([v.get() for v in line])
        self.content["rows"] = rows

    def _tbl_add(self, what):
        self._tbl_collect()
        if what == "row":
            self.content["rows"].append([""] * len(self.content["cols"]))
        else:
            self.content["cols"].append(f"列{len(self.content['cols']) + 1}")
            for row in self.content["rows"]:
                row.append("")
        self._render_table()
        self.nb.schedule_save()

    def _tbl_del(self, what):
        self._tbl_collect()
        if what == "row" and len(self.content["rows"]) > 1:
            self.content["rows"].pop()
        elif what == "col" and len(self.content["cols"]) > 1:
            self.content["cols"].pop()
            for row in self.content["rows"]:
                if row:
                    row.pop()
        self._render_table()
        self.nb.schedule_save()

    # ---- 计算
    def _build_calc(self):
        c = self.content
        self.edit_frame = None
        self.preview_frame = None

        self.calc_txt = tk.Text(self.body, height=2, wrap="char", bd=1,
                                relief="solid", bg="#fbfdfb", fg=INK,
                                font=(MONO, 10), padx=10, pady=7,
                                insertbackground=ACCENT)
        self.calc_txt.pack(fill="x")
        self.calc_txt.insert("1.0", c.get("expr", ""))
        self.calc_txt.bind("<KeyRelease>", lambda e: self.nb.schedule_save())
        self.calc_txt.bind("<Control-Return>", lambda e: (self.on_run_calc(), "break")[1])
        self.calc_txt.bind("<Shift-Return>", lambda e: (self.on_run_then_new(), "break")[1])

        bottom = tk.Frame(self.body, bg=CARD)
        bottom.pack(fill="x", pady=(5, 0))
        tk.Button(bottom, text="▶ 运行", command=self.on_run_calc, relief="flat",
                  bd=0, bg="#e7f0ff", fg=ACCENT, font=(UI, 9), padx=12,
                  cursor="hand2").pack(side="left")
        self.calc_note = tk.Entry(bottom, font=(UI, 9), bd=1, relief="solid",
                                  bg="#fcfdfe", fg=DIM)
        self.calc_note.pack(side="left", fill="x", expand=True, padx=(8, 0), ipady=3)
        self.calc_note.insert(0, c.get("note", ""))
        self.calc_note.bind("<KeyRelease>", lambda e: self.nb.schedule_save())

        self.calc_out = tk.Label(self.body, text="", bg=CARD, fg=GREEN,
                                 font=(MONO, 11, "bold"), anchor="w",
                                 justify="left")
        self.calc_out.pack(fill="x", pady=(6, 0))
        if c.get("result"):
            self.calc_out.configure(text="→ " + c["result"])
        self._hint(self.body, KIND_HINT["calc"])

    def on_run_calc(self):
        self.content["expr"] = self.calc_txt.get("1.0", "end-1c").strip()
        self.content["note"] = self.calc_note.get().strip()
        result, err = eval_calc(self.content["expr"], self.nb.ns)
        if err:
            self.content["result"] = ""
            self.calc_out.configure(text="✗ " + err, fg=RED)
        else:
            self.content["result"] = result
            self.calc_out.configure(text=("→ " + result) if result else "", fg=GREEN)
        self.nb.schedule_save()
        return not err

    # ------------------------------------------------------------ 收集 / 动作
    def collect(self) -> dict:
        k = self.kind
        if k == "text":
            self.content["md"] = self.txt.get("1.0", "end-1c")
        elif k == "step":
            self.content["title"] = self.st_title.get().strip()
            self.content["time"] = self.st_time.get().strip()
            self.content["body"] = self.st_body.get("1.0", "end-1c")
            self.content["done"] = bool(self.st_done.get())
        elif k == "chem":
            self.content["smiles"] = self.ch_smiles.get().strip()
            self.content["caption"] = self.ch_caption.get().strip()
        elif k == "table":
            self._tbl_collect()
        elif k == "calc":
            self.content["expr"] = self.calc_txt.get("1.0", "end-1c").strip()
            self.content["note"] = self.calc_note.get().strip()
        return self.content

    def refresh_preview(self):
        c = self.collect()
        if self.kind == "text":
            self.preview.set_md(c.get("md", ""))
        elif self.kind == "step":
            meta = []
            if c.get("time"):
                meta.append(f"用时 {c['time']}")
            if c.get("done"):
                meta.append("✓ 已完成")
            md = f"### {c.get('title') or '未命名步骤'}"
            if meta:
                md += "\n" + " · ".join(meta)
            if c.get("body"):
                md += "\n\n" + c["body"]
            self.preview.set_md(md)

    def on_toggle(self):
        if self.showing == "preview":
            self._set_mode("edit")
            return
        self.on_run()

    def on_run(self):
        """Ctrl+Enter：保存、渲染、切到预览。"""
        self.nb.save_cell(self)
        self.refresh_preview()
        self._set_mode("preview")
        self.nb.set_status("已保存并渲染")

    def on_run_then_new(self):
        self.on_run()
        self.nb.add_block("text", after=self.bid)

    def on_move(self, delta):
        self.nb.save_cell(self)
        if self.nb.store.move_block(self.bid, delta):
            self.nb.reload(select=self.bid)
        else:
            self.nb.set_status("已经在最上/最下面了")

    def on_duplicate(self):
        self.nb.save_cell(self)
        new_id = self.nb.store.duplicate_block(self.bid)
        if new_id:
            self.nb.reload(select=new_id)
            self.nb.set_status("复制了一块")

    def on_delete(self):
        self.nb.save_cell(self)
        text = summary(self.kind, self.collect())
        if text and not messagebox.askyesno(
                "删除这一块", f"删掉「{text[:24]}」？", parent=self.nb.win):
            return
        self.nb.store.delete_block(self.bid)
        self.nb.reload()
        self.nb.set_status("已删除一块")


# ---------------------------------------------------------------- 窗口

class NotebookWindow:
    """一条记录的全部块。窗口同时只开一个（按记录去重）。"""

    _open: dict = {}

    def __init__(self, parent, store, owner_type: str, owner_id: int,
                 title: str = "", subtitle: str = "", on_close=None):
        self.store = store
        self.owner_type = owner_type
        self.owner_id = owner_id
        self.title = title or f"{owner_type} {owner_id}"
        self.subtitle = subtitle
        self.on_close_cb = on_close
        self.ns = calc_namespace()
        self.cells: list[CellCard] = []
        self._save_job = None
        self._imgs: list = []

        self.win = tk.Toplevel(parent)
        self.win.title(f"实验笔记 · {self.title}")
        self.win.geometry("1180x820")
        self.win.minsize(900, 560)
        self.win.configure(bg=BG)

        self._build()
        self.reload()
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda e: self.close())
        self.win.bind("<Control-Return>", lambda e: self.on_ctrl_enter())

    # ------------------------------------------------------------ 布局
    def _build(self):
        bar = tk.Frame(self.win, bg=BG)
        bar.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(bar, text="实验笔记", bg=BG, fg=INK,
                 font=(UI, 14, "bold")).pack(side="left")
        tk.Label(bar, text=self.title, bg=BG, fg=DIM,
                 font=(UI, 9)).pack(side="left", padx=(10, 0))

        for text, cmd, bg, fg in (("关闭", self.close, "#eef2f8", DIM),
                                  ("导出 HTML", self.export_html, "#f1f4f9", INK),
                                  ("导出 Markdown", self.export_md, "#f1f4f9", INK),
                                  ("网页预览", self.preview_web, "#e8f4ec", GREEN),
                                  ("▶ 全部运行", self.run_all, "#e7f0ff", ACCENT)):
            tk.Button(bar, text=text, command=cmd, relief="flat", bd=0, bg=bg,
                      fg=fg, font=(UI, 9), padx=12, pady=5,
                      cursor="hand2").pack(side="right", padx=3)

        bar2 = tk.Frame(self.win, bg=BG)
        bar2.pack(fill="x", padx=14, pady=(0, 8))
        tk.Label(bar2, text="加一块", bg=BG, fg=DIM,
                 font=(UI, 8)).pack(side="left", padx=(0, 6))
        for kind in ("text", "step", "chem", "table", "calc"):
            bg, fg = KIND_COLORS[kind]
            tk.Button(bar2, text="+ " + KINDS[kind], relief="flat", bd=0, bg=bg,
                      fg=fg, font=(UI, 9), padx=10, pady=4, cursor="hand2",
                      command=lambda k=kind: self.add_block(k)).pack(side="left", padx=2)
        tk.Label(bar2, text="Ctrl+Enter 运行当前块 · Shift+Enter 接下一块 · 双击预览改回编辑",
                 bg=BG, fg="#9aa6b3", font=(UI, 8)).pack(side="left", padx=(14, 0))

        body = tk.Frame(self.win, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        # 左：块目录
        left = tk.Frame(body, bg=CARD, highlightthickness=1,
                        highlightbackground=LINE, width=272)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)
        tk.Label(left, text="块目录", bg=CARD, fg=INK, font=(UI, 10, "bold"),
                 anchor="w").pack(fill="x", padx=10, pady=(8, 4))
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.tree.pack(fill="both", expand=True, padx=4, pady=(0, 6))
        self.tree.bind("<<TreeviewSelect>>", self.on_outline_pick)
        self._outline_lock = False
        self._focused_bid = None

        # 右：块列表
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        self.area = _ScrollArea(right, bg=BG)
        self.area.pack(fill="both", expand=True)

        self.status = tk.Label(self.win, text="", bg=BG, fg=DIM, font=(UI, 8),
                               anchor="w")
        self.status.pack(fill="x", padx=14, pady=(0, 8))

    # ------------------------------------------------------------ 数据
    def reload(self, select=None, keep_scroll=False):
        self.save_all()
        rows = self.store.blocks(self.owner_type, self.owner_id)
        self.area.clear()
        self.cells = []
        for i, row in enumerate(rows):
            card = CellCard(self, row, i)
            self.cells.append(card)
        self._refresh_outline()
        self._update_status()
        if not rows:
            empty = tk.Frame(self.area.body, bg=CARD, highlightthickness=1,
                             highlightbackground=LINE)
            empty.pack(fill="x", padx=(4, 10), pady=4)
            tk.Label(empty, text="还没有内容。上面选一种块开始记：\n"
                                 "文本写思路，步骤记操作，化学放结构，表格记数据，计算算收率。",
                     bg=CARD, fg=DIM, font=(UI, 10), justify="left",
                     padx=20, pady=22).pack(anchor="w")
        if select:
            self.win.after_idle(lambda: self.focus_block(select))
        if keep_scroll:
            self.win.after_idle(lambda: self.area.canvas.yview_moveto(0))

    def _refresh_outline(self):
        sel = self.tree.selection()
        keep = sel[0] if sel else None
        self._outline_lock = True
        self.tree.delete(*self.tree.get_children())
        for card in self.cells:
            text = summary(card.kind, card.collect()).replace("\n", " ")
            line = f" {card.index + 1:02d}  {KINDS[card.kind]} · {text}"
            self.tree.insert("", "end", iid=str(card.bid),
                             text=_clip_px(line, 216, (UI, 9)))
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)
        self._outline_lock = False

    def _update_status(self, extra=""):
        counts = self.store.block_counts(self.owner_type, self.owner_id)
        parts = [f"{KINDS[k]} {counts[k]}" for k in KINDS if counts.get(k)]
        total = sum(counts.values())
        bits = [f"{total} 块"] + parts
        if extra:
            bits.append(extra)
        bits.append("自动保存")
        self.status.configure(text="    ·    ".join(bits))

    def set_status(self, text):
        self._update_status(text)

    def _card(self, bid) -> CellCard | None:
        return next((c for c in self.cells if c.bid == bid), None)

    # ------------------------------------------------------------ 保存
    def schedule_save(self):
        if self._save_job:
            try:
                self.win.after_cancel(self._save_job)
            except Exception:
                pass
        self._save_job = self.win.after(500, self.save_all)

    def save_cell(self, card: CellCard):
        self.store.update_block(card.bid, content=dump_content(card.collect()))

    def save_all(self):
        if self._save_job:
            try:
                self.win.after_cancel(self._save_job)
            except Exception:
                pass
            self._save_job = None
        for card in self.cells:
            try:
                self.save_cell(card)
            except Exception:
                pass
        self._refresh_outline()

    # ------------------------------------------------------------ 动作
    def add_block(self, kind: str, after=None):
        self.save_all()
        pos = None
        if after is not None:
            b = self.store.block(after)
            if b is not None:
                pos = int(b["position"]) + 1
                self.store._open_slot(self.owner_type, self.owner_id, pos)
        bid = self.store.add_block(self.owner_type, self.owner_id, kind,
                                   dump_content(default_content(kind)), pos)
        self.reload(select=bid)
        self.set_status(f"新增一块{KINDS[kind]}")

    def focus_block(self, bid):
        card = self._card(bid)
        if card is None:
            return
        # 记一下「当前块」：目录的 <<TreeviewSelect>> 是异步派发的，
        # 用锁挡不住回弹，得靠这个值判断这次选中是不是自己刚设的。
        self._focused_bid = bid
        self.area.scroll_to(card.frame)
        if self.tree.selection() != (str(bid),):
            self._outline_lock = True
            try:
                self.tree.selection_set(str(bid))
                self.tree.see(str(bid))
            finally:
                self._outline_lock = False
        if card.kind == "text":
            card.txt.focus_set()
        elif card.kind == "step":
            card.st_title.focus_set()
        elif card.kind == "chem":
            card.ch_smiles.focus_set()
        elif card.kind == "calc":
            card.calc_txt.focus_set()

    def on_outline_pick(self, _e=None):
        if self._outline_lock:
            return
        sel = self.tree.selection()
        if not sel:
            return
        bid = int(sel[0])
        if bid == self._focused_bid:       # 自己刚设的选中，别再来一遍
            return
        self.focus_block(bid)

    def on_ctrl_enter(self):
        """窗口级的 Ctrl+Enter：作用在光标所在的块上。"""
        w = self.win.focus_get()
        for card in self.cells:
            if w is not None and (w is card.frame or self._is_child(w, card.frame)):
                if card.kind == "calc":
                    card.on_run_calc()
                else:
                    card.on_run()
                return

    @staticmethod
    def _is_child(widget, ancestor) -> bool:
        w = widget
        while w is not None:
            if w is ancestor:
                return True
            w = getattr(w, "master", None)
        return False

    def run_all(self):
        """把所有块从上往下存一遍，计算块依次求值——变量可以跨块传递。"""
        self.save_all()
        self.ns = calc_namespace()
        ok = bad = 0
        for card in self.cells:
            card.nb = self
            if card.kind == "calc":
                if card.on_run_calc():
                    ok += 1
                else:
                    bad += 1
            elif card.kind in ("text", "step"):
                card.refresh_preview()
        self.save_all()
        msg = f"全部运行：{ok} 个计算块成功"
        if bad:
            msg += f"，{bad} 个出错"
        self.set_status(msg)

    def show_big_structure(self, smiles):
        pic = chem.render_smiles(smiles, 900, 660)
        if pic is None:
            return
        win = tk.Toplevel(self.win)
        win.title("结构式")
        photo = ImageTk.PhotoImage(pic)
        lbl = tk.Label(win, image=photo, bg="white")
        lbl.image = photo
        lbl.pack(padx=8, pady=8)
        win.bind("<Escape>", lambda e: win.destroy())

    # ------------------------------------------------------------ 导出
    def export_md(self):
        self.save_all()
        blocks = _blocks_of(self.store, self.owner_type, self.owner_id)
        text = to_markdown(self.title, blocks)
        path = os.path.join(data_root(), f"笔记-{self.owner_type}-{self.owner_id}.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.set_status(f"已导出 {os.path.basename(path)}")
        try:
            os.startfile(path)                        # noqa: S606
        except Exception:
            messagebox.showinfo("已导出", path, parent=self.win)

    def export_html(self):
        self.save_all()
        blocks = _blocks_of(self.store, self.owner_type, self.owner_id)
        doc = to_html(self.title, blocks, subtitle=self.subtitle)
        path = os.path.join(data_root(), f"笔记-{self.owner_type}-{self.owner_id}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(doc)
        self.set_status(f"已导出 {os.path.basename(path)}")
        try:
            webbrowser.open("file:///" + path.replace("\\", "/"))
        except Exception:
            pass

    def preview_web(self):
        """内置浏览器预览：有 tkinterweb 就用它，没有就退回系统浏览器。"""
        self.save_all()
        blocks = _blocks_of(self.store, self.owner_type, self.owner_id)
        doc = to_html(self.title, blocks, subtitle=self.subtitle)
        try:
            from tkinterweb import HtmlFrame
        except Exception:
            HtmlFrame = None
        if HtmlFrame is None:
            self.export_html()
            self.set_status("没装 tkinterweb，改用浏览器预览")
            return
        win = tk.Toplevel(self.win)
        win.title(f"笔记预览 · {self.title}")
        win.geometry("1000x800")
        win.configure(bg="white")
        try:
            frame = HtmlFrame(win, messages_enabled=False,
                              horizontal_scrollbar="auto")
            frame.pack(fill="both", expand=True)
            frame.load_html(doc)
        except Exception as e:                     # noqa: BLE001
            win.destroy()
            messagebox.showinfo("预览失败", f"{e}\n\n已改用浏览器打开。",
                                parent=self.win)
            self.export_html()
            return
        win.bind("<Escape>", lambda e: win.destroy())
        self.set_status("已打开网页预览")

    # ------------------------------------------------------------ 关闭
    def close(self):
        self.save_all()
        NotebookWindow._open.pop((self.owner_type, self.owner_id), None)
        if self.on_close_cb:
            try:
                self.on_close_cb()
            except Exception:
                pass
        self.win.destroy()


def open_notebook(parent, store, owner_type: str, owner_id: int,
                  title: str = "", subtitle: str = "", on_close=None) -> NotebookWindow:
    """统一入口：同一条记录只开一个窗口，重复点就抬到前面。"""
    import keyfix
    keyfix.install()          # 修 Text 吞字符（'-' 被报成 keysym Insert）
    key = (owner_type, owner_id)
    win = NotebookWindow._open.get(key)
    if win is not None:
        try:
            win.win.deiconify()
            win.win.lift()
            win.win.focus_force()
            return win
        except Exception:
            NotebookWindow._open.pop(key, None)
    win = NotebookWindow(parent, store, owner_type, owner_id, title, subtitle, on_close)
    NotebookWindow._open[key] = win
    return win
