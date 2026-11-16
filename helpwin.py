# -*- coding: utf-8 -*-
"""
内置帮助窗口。

读 MANUAL.md，按 `## ` 拆成章节，左边目录右边正文，顶上能搜。
「导出网页」会把整份手册转成一个带样式的 HTML，用浏览器打开——
想打印或者发给同学的时候用这个。
"""
from __future__ import annotations

import html
import os
import re
import tkinter as tk
import webbrowser
from tkinter import ttk

from paths import app_dir, res_path

BG = "#f4f6f9"
SHEET = "#ffffff"
INK = "#16202c"
DIM = "#6b7684"
ACCENT = "#1f6feb"
LINE = "#dde3ea"
UI_FONT = "Microsoft YaHei UI"
MONO_FONT = UI_FONT   # 字体统一：代码块也用同一族

MANUAL = res_path("MANUAL.md")

FENCE = "```"


# ---------------------------------------------------------------- 解析

def parse_manual(path: str = MANUAL) -> list[dict]:
    """把 Markdown 拆成 [{title, lines}]，第一个 `## ` 之前的内容丢掉。"""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    sections: list[dict] = []
    cur = None
    for line in text.split("\n"):
        if line.startswith("## "):
            cur = {"title": line[3:].strip(), "lines": []}
            sections.append(cur)
        elif cur is not None:
            cur["lines"].append(line)
    return sections


def plain(section: dict) -> str:
    return section["title"] + "\n" + "\n".join(section["lines"])


# ---------------------------------------------------------------- 窗口

class HelpWindow:
    def __init__(self, parent: tk.Misc):
        self.sections = parse_manual()
        self._current = -1
        self.win = tk.Toplevel(parent)
        self.win.title("ELN · 用户手册")
        self.win.geometry("960x720")
        self.win.minsize(720, 500)
        self.win.configure(bg=BG)

        self._build()
        if self.sections:
            self.show(0)

    # ------------------------------------------------------------ 布局
    def _build(self):
        bar = tk.Frame(self.win, bg=BG)
        bar.pack(fill="x", padx=12, pady=(10, 6))

        tk.Label(bar, text="用户手册", bg=BG, fg=INK,
                 font=(UI_FONT, 13, "bold")).pack(side="left")
        tk.Label(bar, text="F1 随时打开", bg=BG, fg=DIM,
                 font=(UI_FONT, 8)).pack(side="left", padx=(8, 16))

        self.kw = tk.StringVar()
        entry = tk.Entry(bar, textvariable=self.kw, width=22, font=(UI_FONT, 10),
                         bd=1, relief="solid", bg="#ffffff", fg=INK)
        entry.pack(side="left", ipady=3)
        entry.bind("<KeyRelease>", self.on_search)
        tk.Label(bar, text="搜索", bg=BG, fg=DIM,
                 font=(UI_FONT, 8)).pack(side="left", padx=(6, 0))

        tk.Button(bar, text="导出网页", command=self.export_html, relief="flat",
                  bd=0, bg="#e8eef7", fg=ACCENT, font=(UI_FONT, 9), padx=10,
                  pady=4, cursor="hand2").pack(side="right")

        body = tk.Frame(self.win, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        # 左：目录
        left = tk.Frame(body, bg=SHEET, highlightthickness=1,
                        highlightbackground=LINE, width=300)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        left.grid_propagate(False)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        sb = ttk.Scrollbar(left, command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self.on_pick)

        # 右：正文
        right = tk.Frame(body, bg=SHEET, highlightthickness=1,
                         highlightbackground=LINE)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        # 中文没有词边界，wrap="word" 会把整句当成一个词，导致「· 」被单独
        # 折到上一行；按字符折行才符合中文排版习惯。
        self.txt = tk.Text(right, wrap="char", bd=0, relief="flat", bg=SHEET,
                           fg=INK, padx=20, pady=16, cursor="arrow",
                           font=(UI_FONT, 10), spacing1=2, spacing3=2)
        self.txt.grid(row=0, column=0, sticky="nsew")
        sb2 = ttk.Scrollbar(right, command=self.txt.yview)
        sb2.grid(row=0, column=1, sticky="ns")
        self.txt.configure(yscrollcommand=sb2.set)

        self.txt.tag_configure("h2", font=(UI_FONT, 15, "bold"), spacing1=6,
                               spacing3=10, foreground=INK)
        self.txt.tag_configure("h3", font=(UI_FONT, 11, "bold"), spacing1=12,
                               spacing3=5, foreground="#2b3a4d")
        self.txt.tag_configure("body", font=(UI_FONT, 10), spacing3=4,
                               lmargin1=6, lmargin2=6)
        self.txt.tag_configure("bullet", font=(UI_FONT, 10), spacing3=3,
                               lmargin1=22, lmargin2=38)
        self.txt.tag_configure("code", font=(MONO_FONT, 10), background="#f4f6f9",
                               spacing1=1, spacing3=1, lmargin1=24, lmargin2=24)
        self.txt.tag_configure("bold", font=(UI_FONT, 10, "bold"))
        self.txt.tag_configure("icode", font=(MONO_FONT, 10), background="#eef2f8")
        self.txt.tag_configure("dim", font=(UI_FONT, 9), foreground=DIM)
        # 同一行里混用 lmargin 不同的 tag 会让 Tk 把「· 」单独折到上一行。
        # 给粗体 / 行内代码各配一份带相同缩进的组合 tag，段落就不会被拆开。
        for base, lm1, lm2, sp in (("body", 6, 6, 4), ("bullet", 22, 38, 3)):
            self.txt.tag_configure(base + "_mark", font=(UI_FONT, 10),
                                   lmargin1=lm1, lmargin2=lm2, spacing3=sp)
            self.txt.tag_configure(base + "_bold", font=(UI_FONT, 10, "bold"),
                                   lmargin1=lm1, lmargin2=lm2, spacing3=sp)
            self.txt.tag_configure(base + "_icode", font=(MONO_FONT, 10),
                                   background="#eef2f8", lmargin1=lm1,
                                   lmargin2=lm2, spacing3=sp)
        self.txt.configure(state="disabled")

        self.win.bind("<Escape>", lambda e: self.win.destroy())
        self.refresh_tree()

    # ------------------------------------------------------------ 目录
    def refresh_tree(self, keyword: str = ""):
        self.tree.delete(*self.tree.get_children())
        kw = keyword.strip().lower()
        self._visible = []
        for i, sec in enumerate(self.sections):
            if kw and kw not in plain(sec).lower():
                continue
            self._visible.append(i)
            title = sec["title"]
            self.tree.insert("", "end", iid=str(i), text=" " + title)
        if self._visible:
            first = str(self._visible[0])
            self.tree.selection_set(first)
            self.tree.focus(first)

    def on_search(self, _e=None):
        self.refresh_tree(self.kw.get())
        if self._visible:
            self.show(self._visible[0])

    def on_pick(self, _e=None):
        sel = self.tree.selection()
        if sel and int(sel[0]) != self._current:
            self.show(int(sel[0]))

    # ------------------------------------------------------------ 正文
    @staticmethod
    def _disp_width(text: str) -> int:
        """按「中文算 2、其它算 1」估显示宽度，用来算表格列宽。"""
        return sum(2 if ord(ch) > 127 else 1 for ch in text)

    def _flush_table(self, rows: list[list[str]], idx: int):
        """把一组 |a|b| 行渲染成用制表位对齐的表格（Text 里没法放真表格）。"""
        if not rows:
            return
        cols = max(len(r) for r in rows)
        widths = []
        for c in range(cols):
            w = max((self._disp_width(r[c].strip()) if c < len(r) else 0) for r in rows)
            # 10pt 下中文约 13.3px、英文约 6.6px；_disp_width 里中文记 2，所以按每单位 6.6px 估
            widths.append(max(56, min(520, int(w * 6.6) + 26)))
        # 总宽超过正文宽度就等比压缩，免得 tab 顶到右边界外
        try:
            tw = self.txt.winfo_width()
        except Exception:
            tw = 0
        avail = (tw - 36) if tw > 120 else 620
        total = sum(widths)
        if total > avail:
            k = avail / total
            widths = [max(48, int(w * k)) for w in widths]
        stops, acc = [], 0
        for w in widths[:-1]:
            acc += w
            stops.append(acc)
        row_tag, head_tag = f"tbl{idx}", f"tblh{idx}"
        self.txt.tag_configure(row_tag, tabs=tuple(stops), spacing1=1, spacing3=2)
        self.txt.tag_configure(head_tag, tabs=tuple(stops), spacing1=3, spacing3=3,
                               background="#eef3fa", font=(UI_FONT, 9, "bold"))
        for i, row in enumerate(rows):
            # 单元格里不做富文本（混用 lmargin 会把整行拆坏），只去掉标记符号
            cells = [c.strip().replace("**", "").replace("`", "") for c in row]
            cells += [""] * (cols - len(cells))
            line = "\t".join(cells) + "\n"
            self.txt.insert("end", line, (row_tag, head_tag) if i == 0 else row_tag)

    def show(self, idx: int):
        if not (0 <= idx < len(self.sections)):
            return
        self._current = idx
        iid = str(idx)
        if self.tree.exists(iid) and self.tree.selection() != (iid,):
            self.tree.selection_set(iid)      # 目录跟着正文走，别让选中项停在旧位置
            self.tree.see(iid)
        sec = self.sections[idx]
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")

        self.txt.insert("end", sec["title"] + "\n", "h2")

        in_code = False
        table_rows: list[list[str]] = []
        tbl_no = 0

        def flush():
            nonlocal tbl_no
            if table_rows:
                self._flush_table(table_rows, tbl_no)
                tbl_no += 1
                table_rows.clear()

        for raw in sec["lines"]:
            line = raw.rstrip()

            if line.startswith(FENCE):
                in_code = not in_code
                if in_code:
                    self.txt.insert("end", "\n")
                continue

            if in_code:
                self.txt.insert("end", (line if line else " ") + "\n", "code")
                continue

            stripped = line.strip()
            if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 2:
                cells = [c for c in stripped.strip("|").split("|")]
                if all(re.fullmatch(r":?-{2,}:?", c.strip()) for c in cells if c.strip()):
                    continue                   # |---|---| 是分隔行，跳过
                table_rows.append(cells)
                continue
            flush()

            if not line or line.startswith("---"):
                self.txt.insert("end", "\n")
                continue

            if line.startswith("### "):
                self.txt.insert("end", line[4:].strip() + "\n", "h3")
            elif line.startswith("- "):
                self._rich(line[2:], "bullet", "· ")
            elif line.startswith("**") and line.endswith("**") and line.count("**") == 2:
                self.txt.insert("end", line.strip("*") + "\n", "h3")
            else:
                self._rich(line, "body")

        flush()
        self.txt.configure(state="disabled")
        self.txt.yview_moveto(0)

    def _rich(self, text: str, base_tag: str, prefix: str = ""):
        """处理 **加粗** 和 `行内代码`；同一行所有片段共用缩进，避免 Tk 折行。"""
        if prefix:
            self.txt.insert("end", prefix, (base_tag + "_mark",))
        for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
            if not part:
                continue
            if part.startswith("**") and part.endswith("**"):
                self.txt.insert("end", part[2:-2], (base_tag + "_bold",))
            elif part.startswith("`") and part.endswith("`"):
                self.txt.insert("end", part[1:-1], (base_tag + "_icode",))
            else:
                self.txt.insert("end", part, (base_tag,))
        self.txt.insert("end", "\n", (base_tag,))

    # ------------------------------------------------------------ 导出
    def export_html(self):
        if not self.sections:
            return
        html_text = build_html(self.sections)
        # 导出的是交付物，落在当前账户的数据目录里方便找；不往系统临时目录写
        path = os.path.join(app_dir(), "ELN-用户手册.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html_text)
        try:
            webbrowser.open("file:///" + path.replace("\\", "/"))
        except Exception:
            pass


# ---------------------------------------------------------------- HTML

_HTML_HEAD = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>ELN 用户手册</title>
<style>
  body { font-family: "Microsoft YaHei", "Segoe UI", sans-serif; line-height: 1.75;
         max-width: 860px; margin: 48px auto; padding: 0 24px; color: #16202c; }
  h1 { font-size: 30px; border-bottom: 3px solid #1f6feb; padding-bottom: 12px; }
  h2 { font-size: 22px; margin-top: 42px; color: #16202c; }
  h3 { font-size: 16px; margin-top: 26px; color: #2b3a4d; }
  p  { margin: 10px 0; }
  ul { margin: 8px 0 8px 4px; padding-left: 22px; }
  li { margin: 4px 0; }
  pre { background: #f4f6f9; border-left: 3px solid #1f6feb; padding: 14px 16px;
        overflow-x: auto; border-radius: 4px; }
  code { font-family: Consolas, monospace; font-size: 13px; }
  table { border-collapse: collapse; margin: 12px 0; font-size: 14px; }
  th, td { border: 1px solid #dde3ea; padding: 6px 10px; text-align: left;
           vertical-align: top; }
  th { background: #eef3fa; }
  hr { border: 0; border-top: 1px solid #e3e8ef; margin: 28px 0; }
  @media print { body { margin: 0; max-width: none; } h2 { page-break-after: avoid; } }
</style></head><body>
<h1>ELN 用户手册</h1>
"""


def build_html(sections: list[dict]) -> str:
    out = [_HTML_HEAD]
    for sec in sections:
        out.append(f"<h2>{html.escape(sec['title'])}</h2>")
        in_code, buf = False, []
        table_rows: list[list[str]] = []

        def flush():
            nonlocal buf
            if buf:
                out.append("<pre><code>" + html.escape("\n".join(buf)) + "</code></pre>")
                buf = []

        def flush_table():
            if not table_rows:
                return
            out.append("<table>")
            for i, row in enumerate(table_rows):
                tag = "th" if i == 0 else "td"
                cells = "".join(f"<{tag}>{_inline(c.strip())}</{tag}>" for c in row)
                out.append(f"<tr>{cells}</tr>")
            out.append("</table>")
            table_rows.clear()

        for raw in sec["lines"]:
            line = raw.rstrip()
            if line.startswith(FENCE):
                if in_code:
                    flush()
                in_code = not in_code
                continue
            if in_code:
                buf.append(line)
                continue
            stripped = line.strip()
            if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 2:
                cells = [c for c in stripped.strip("|").split("|")]
                if all(re.fullmatch(r":?-{2,}:?", c.strip()) for c in cells if c.strip()):
                    continue                       # |---|---| 分隔行
                table_rows.append(cells)
                continue
            flush_table()
            if not line or line.startswith("---"):
                continue
            if line.startswith("### "):
                out.append(f"<h3>{html.escape(line[4:].strip())}</h3>")
            elif line.startswith("- "):
                out.append(f"<li>{_inline(line[2:])}</li>")
            else:
                out.append(f"<p>{_inline(line)}</p>")
        flush_table()
        flush()
    out.append("</body></html>")
    return "\n".join(out)


def _inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", text)


# ---------------------------------------------------------------- 兜底

def open_help(parent: tk.Misc) -> HelpWindow | None:
    """没有 MANUAL.md 时退回一个最简窗口，至少不会什么都点不出来。"""
    if not os.path.exists(MANUAL):
        win = tk.Toplevel(parent)
        win.title("ELN · 帮助")
        win.geometry("560x420")
        tk.Label(win, text="找不到 MANUAL.md，手册内容缺失。\n"
                           "把它放回程序目录就能恢复。",
                 font=(UI_FONT, 11), padx=24, pady=24).pack(expand=True)
        return None
    return HelpWindow(parent)
