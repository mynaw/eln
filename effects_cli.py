# -*- coding: utf-8 -*-
"""
命令行入口。用法：

    python cli.py 甲氧基
    python cli.py -NO2 OMe CF3          # 一次问多个
    python cli.py --rank                # 全部基团按 σp 排序
    python cli.py --compare OMe NO2     # 两个基团对比
    python cli.py --smiles "*S(=O)(=O)N"  # 直接给结构
    python cli.py --hybrid "CC(=O)N"    # 判断每个原子的杂化（也可给基团名或结构文件）
    python cli.py 结构.cdx              # 直接给 ChemDraw 文件（也可 --file）
    python cli.py 结构.cdx --atoms 7,8,9  # 只判指定的这几个原子
    python cli.py 结构.cdx --select mark  # 按 CDXML 里画的圈判（默认就是它）
    python cli.py 结构.cdx --no-mark     # 忽略图上画的圈，按默认规则找
    python cli.py --clip                 # 判剪贴板里的结构（ChemDraw 里复制）
    python cli.py --plugins              # 看已注册的扩展
    python cli.py -i                    # 交互模式，可连续问

结构文件支持 .cdx / .cdxml / .mol / .sdf / .mol2 / .smi / .rxn / .pdb
默认自动找出芳环上的每个取代基分别判定；在 CDXML 里画了圈/框就按圈里的原子判；
也可以用 --atoms 自己点名（原子序号从 1 数起）。
"""

from __future__ import annotations

import json
import os
import sys

import engine

FLAGS = {
    "-h": "help", "--help": "help", "help": "help", "/?": "help",
    "-l": "list", "--list": "list",
    "-r": "rank", "--rank": "rank", "--table": "rank",
    "-i": "interactive", "--interactive": "interactive",
    "-j": "json", "--json": "json",
    "-s": "analyze", "--smiles": "analyze",
    "-c": "compare", "--compare": "compare",
    "-f": "file", "--file": "file",
    "--hybrid": "hybrid", "-y": "hybrid",
}

W = 62


def usage():
    print(__doc__)


def axis(v: float | None, half: int = 10) -> str:
    """把 σ 值画在一根以 H 为零点的轴上。"""
    if v is None:
        return " " * (2 * half + 1)
    pos = int(round((max(-1.0, min(1.0, v)) + 1.0) / 2.0 * 2 * half))
    cells = ["-"] * (2 * half + 1)
    cells[half] = "|"
    cells[pos] = "o"
    return "".join(cells)


def cmd_rank():
    rows = engine.ranked()
    print("按 σp 从最给电子排到最吸电子。o = 这个基团的位置，| = 参比 H 的零点。")
    print("-" * W)
    print("        σp    ← 给电子        |        吸电子 →")
    print("-" * W)
    for r in rows:
        conf = {"文献": " ", "近似": "~", "定性": "?", "推断": "*"}.get(r["conf"], " ")
        print(f"  {r['sp']:>+6.2f}  {axis(r['sp'])}  {conf} {r['name']} ({r['key']})")
    print("-" * W)
    print("  标记列：空格 = 文献值，~ = 近似，? = 仅定性，* = 结构推断")
    print(f"  共 {len(rows)} 个基团（另有 {len(engine.GROUPS) - len(rows)} 个无数值、只能定性）。")


def cmd_list():
    print(f"{'编号':<10}{'中文名':<18}{'σp':>7}  类别")
    print("-" * W)
    for g in sorted(engine.GROUPS, key=lambda x: (x["sp"] is None, x["sp"] or 0)):
        cls, _ = engine.total_effect(g)
        sp = f"{g['sp']:+.2f}" if g["sp"] is not None else "—"
        print(f"{g['key']:<10}{g['zh']:<18}{sp:>7}  {cls}")
    print("-" * W)
    print(f"共 {len(engine.GROUPS)} 个。用 --rank 看排序，直接输入名字或 SMILES 问单个基团。")


def cmd_analyze(queries: list[str], as_json: bool = False):
    code = 0
    out = []
    for i, q in enumerate(queries):
        rec, err = engine.analyze(q)
        if i:
            print()
        if not rec:
            print(f"[?] {err}")
            code = 1
            continue
        if as_json:
            out.append(rec)
        else:
            print(engine.format_report(rec, W))
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return code


def cmd_file(path: str, picked=None, use_mark: bool = True, selection=None):
    import structure
    try:
        res = structure.analyze_file(path, picked=picked, use_mark=use_mark,
                                     selection=selection)
    except structure.FileError as e:
        print("[?] " + str(e))
        return 1
    print(structure.summarize(res))
    return 0


def cmd_clip(picked=None, selection=None):
    import structure
    try:
        res = structure.analyze_clipboard(picked=picked, selection=selection)
    except structure.FileError as e:
        print("[?] " + str(e))
        return 1
    print(structure.summarize(res))
    return 0


def cmd_plugins():
    import ext
    import structure  # noqa: F401  导入以注册内置选法
    print(ext.describe())
    return 0


def _w(s: str) -> int:
    """显示宽度，中文算 2 列。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _w(s))


def _print_hybrid_table(mol, title: str):
    import hybrid

    # 编号按「重原子」数，跳过 * 连接点（基团片段里 * 是 1 号，直接显示会让人困惑）
    order = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() > 1]
    pos = {idx: i + 1 for i, idx in enumerate(order)}
    items = [h for h in hybrid.analyze_mol(mol) if h["idx"] in pos]
    print(title)
    print("-" * W)
    print(f"{'#':>3}  {_pad('原子', 5)}{_pad('杂化', 7)}{_pad('形状', 26)}"
          f"{_pad('键角', 18)}孤对")
    print("-" * W)
    for h in items:
        extra = "  ← 共轭重杂化" if h["rehybrid"] else ""
        print(f"{pos[h['idx']]:>3}  {_pad(h['symbol'], 5)}{_pad(h['hybrid'], 7)}"
              f"{_pad(h['geometry'], 26)}{_pad(h['angle'], 18)}{h['lone']}{extra}")
    print("-" * W)

    notes = [h for h in items if h["note"] or h["rehybrid"]]
    if notes:
        print("值得注意：")
        for h in notes:
            if h["rehybrid"]:
                print(f"  {h['symbol']}{pos[h['idx']]}：按 σ 键 + 孤对算是 sp3，"
                      f"但孤对要参与共轭，实际按 sp2 处理。")
            if h["note"]:
                for line in engine._wrap(h["note"], f"  {h['symbol']}{pos[h['idx']]}：",
                                         W).split("\n"):
                    print(line)
        print()
    print("σ 键数里已经包含了氢；孤对由价电子减成键电子算出，见 hybrid.py。")


def cmd_hybrid(query: str):
    """给 SMILES 或基团名，列出每个重原子的杂化。"""
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog("rdApp.*")

    grp = engine.lookup(query)
    smiles = grp["smiles"] if grp else query
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        print(f"[?] 解析不了：{smiles}")
        return 1
    name = f"基团    {grp['zh']}   [{grp['en']}]\n结构    {smiles}" if grp else f"结构    {smiles}"
    _print_hybrid_table(mol, name)
    return 0


def cmd_hybrid_file(path: str):
    import structure

    try:
        info = structure.load(path)
    except structure.FileError as e:
        print("[?] " + str(e))
        return 1
    _print_hybrid_table(info["mol"], f"文件    {os.path.basename(path)}\n结构    {info['smiles']}")
    return 0


def cmd_compare(a: str, b: str):
    ra, _ = engine.analyze(a)
    rb, _ = engine.analyze(b)
    if not ra or not rb:
        print("[?] 有一个基团没查到")
        return 1
    print(engine.format_report(ra, W))
    print()
    print(engine.format_report(rb, W))
    print()
    print("对比")
    print("-" * W)
    print(engine.compare(a, b) or "无法比较")
    return 0


def cmd_interactive():
    print("交互模式：输入基团名/SMILES 回车查看，:rank 看排序，:q 退出。")
    while True:
        try:
            q = input("\n基团> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q in (":q", ":quit", "exit", "quit"):
            break
        if q in (":rank", ":r"):
            cmd_rank()
            continue
        if q in (":list", ":l"):
            cmd_list()
            continue
        rec, err = engine.analyze(q)
        print(engine.format_report(rec, W) if rec else "  " + err)
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        usage()
        return 0

    # --atoms 后面跟的是原子序号，不是查询词，先摘出去
    picked = None
    for flag in ("--atoms", "-a"):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 < len(argv):
                picked = [int(x) - 1 for x in
                          argv[i + 1].replace(",", " ").replace("，", " ").split()
                          if x.isdigit() and int(x) > 0]
                del argv[i:i + 2]
            else:
                print("用法：--atoms 7,8,9（原子序号从 1 数起）")
                return 2
    use_mark = "--no-mark" not in argv
    if not use_mark:
        argv.remove("--no-mark")

    selection = None
    for flag in ("--select", "--selection"):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 >= len(argv):
                print("用法：--select auto | mark | atoms（--plugins 看全部）")
                return 2
            selection = argv[i + 1]
            del argv[i:i + 2]

    want_clip = "--clip" in argv
    if want_clip:
        argv.remove("--clip")
    want_plugins = "--plugins" in argv
    if want_plugins:
        argv.remove("--plugins")

    mode = None
    queries: list[str] = []
    for a in argv:
        key = a.lower()
        if key in FLAGS:
            mode = FLAGS[key]
        else:
            queries.append(a)          # 以 - 开头的基团名（-NO2）也能进来

    if mode == "help":
        usage()
        return 0
    if mode == "list":
        cmd_list()
        return 0
    if mode == "rank":
        cmd_rank()
        return 0
    if mode == "interactive":
        return cmd_interactive()
    if mode == "compare":
        if len(queries) < 2:
            print("需要两个基团，例如：--compare OMe NO2")
            return 2
        return cmd_compare(queries[0], queries[1])
    if mode == "hybrid":
        if not queries:
            print('用法：--hybrid "-CN" 或 --hybrid "CC(=O)N" 或 --hybrid 结构.mol')
            return 2
        if len(queries) == 1 and os.path.isfile(queries[0]):
            return cmd_hybrid_file(queries[0])
        return cmd_hybrid(queries[0])
    if want_plugins:
        return cmd_plugins()
    if want_clip:
        return cmd_clip(picked, selection)
    if mode == "file":
        if not queries:
            print("用法：--file 结构.cdx")
            return 2
        return cmd_file(queries[0], picked, use_mark, selection)
    # 直接把文件拖到 bat / 命令行上时，不用写 --file
    if len(queries) == 1 and os.path.isfile(queries[0]):
        return cmd_file(queries[0], picked, use_mark, selection)
    if not queries:
        usage()
        return 2
    return cmd_analyze(queries, as_json=(mode == "json"))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
