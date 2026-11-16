# -*- coding: utf-8 -*-
"""
结构文件读取：把 ChemDraw / MDL 文件变成分子，再找出「芳环上接了哪些取代基」。

支持格式
    .cdxml        自己解析（XML，原子用原子序数标注）——最稳
    .cdx          ChemDraw 二进制，交给 Open Babel 转（Read-only）
    .mol / .mdl   RDKit 直接读
    .sdf / .sd    RDKit 读，多分子时取最大的那个
    .mol2         Open Babel 转
    .smi/.smiles  文本
    .rxn          反应文件，取产物

关键点：σ 值是在芳环上测的，所以「基团」必须是挂在环上的那一坨。
本模块自动找出环系、沿环外单键做广度优先，把每个取代基切成独立的
带 * 连接点的 SMILES（*OC、*[N+](=O)[O-] …），再交给 engine 判定。
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import unicodedata
import tempfile
import xml.etree.ElementTree as ET

import ext as ext_api

try:
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog("rdApp.*")
except Exception:                                   # pragma: no cover
    Chem = None

FORMAT_NAME = {
    ".cdx": "ChemDraw 二进制 (CDX)",
    ".cdxml": "ChemDraw XML (CDXML)",
    ".mol": "MDL MOL",
    ".mdl": "MDL MOL",
    ".sdf": "MDL SD",
    ".sd": "MDL SD",
    ".mol2": "Tripos MOL2",
    ".smi": "SMILES 文本",
    ".smiles": "SMILES 文本",
    ".can": "SMILES 文本",
    ".pdb": "PDB",
    ".rxn": "MDL RXN 反应",
}

SUPPORTED = tuple(FORMAT_NAME)


class FileError(Exception):
    """读文件失败，消息直接给用户看。"""


# ---------------------------------------------------------------- 外部工具

def find_obabel() -> str | None:
    env = os.environ.get("OBABEL")
    if env and os.path.exists(env):
        return env
    p = shutil.which("obabel")
    if p:
        return p
    # 跟着当前解释器找（conda 会把 obabel 放在 Scripts 或 Library/bin）
    base = os.path.dirname(os.path.abspath(sys.executable))
    for rel in ("Scripts/obabel.exe", "Library/bin/obabel.exe",
                "bin/obabel", "Scripts/obabel"):
        cand = os.path.join(base, *rel.split("/"))
        if os.path.exists(cand):
            return cand
    return None


def obabel_version() -> str:
    exe = find_obabel()
    if not exe:
        return "未安装"
    try:
        r = subprocess.run([exe, "-V"], capture_output=True, text=True, timeout=20)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else "未知"
    except Exception:
        return "未知"


class _AsciiPath:
    """Open Babel 对中文路径不稳，必要时复制到临时目录。"""

    def __init__(self, path: str):
        self.path = path
        self.tmp = None

    def __enter__(self) -> str:
        try:
            self.path.encode("ascii")
            return self.path
        except UnicodeEncodeError:
            pass
        d = tempfile.mkdtemp(prefix="ee_struct_")
        self.tmp = d
        dst = os.path.join(d, "input" + os.path.splitext(self.path)[1].lower())
        shutil.copy2(self.path, dst)
        return dst

    def __exit__(self, *exc):
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
        return False


def _run_obabel(path: str, infmt: str, outfmt: str = "smi") -> str:
    exe = find_obabel()
    if not exe:
        raise FileError(
            "这种格式需要 Open Babel 转换，但没找到 obabel。\n"
            "  在 ChemDraw 里改存为 CDXML 或 MOL 也可以（这两种不需要外部工具）。")
    with _AsciiPath(path) as p:
        try:
            r = subprocess.run([exe, "-i", infmt, p, "-o", outfmt, "-am"],
                               capture_output=True, text=True, timeout=120,
                               errors="replace")
        except subprocess.TimeoutExpired:
            raise FileError("Open Babel 转换超时（文件过大？）")
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not out:
        msg = (r.stderr or "").strip().splitlines()
        tip = msg[-1] if msg else "没有输出"
        raise FileError(f"Open Babel 读不了这个 {infmt.upper()} 文件：{tip}\n"
                        f"  在 ChemDraw 里另存为 CDXML 或 MOL 通常可以解决。")
    return out


# ---------------------------------------------------------------- 读文件

def _read_text(path: str) -> str:
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-16", "gbk"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("latin-1")


def load(path: str) -> dict:
    """读一个结构文件，返回 {mol, fmt, name, note}。失败抛 FileError。"""
    if Chem is None:
        raise FileError("没有 RDKit，无法解析结构。")
    if not os.path.exists(path):
        raise FileError(f"文件不存在：{path}")

    ext = os.path.splitext(path)[1].lower()

    # 扩展注册过的格式优先（见 ext.py）
    custom = ext_api.run_loader(ext, path)
    if custom is not None:
        mol, cnotes, cmarks = custom
        if mol is None or mol.GetNumAtoms() == 0:
            raise FileError("扩展读到了文件，但里面没有结构。")
        mol = _tidy(mol)
        if mol is None:
            raise FileError("扩展读出的结构化合价不合法。")
        return {"mol": mol, "fmt": f"{ext}（扩展）", "ext": ext,
                "name": os.path.splitext(os.path.basename(path))[0],
                "note": list(cnotes or []), "marks": list(cmarks or []),
                "smiles": Chem.MolToSmiles(mol),
                "path": path, "file": os.path.basename(path)}

    fmt = FORMAT_NAME.get(ext)
    if fmt is None:
        raise FileError(f"不支持的格式 {ext}。可用：" + "、".join(SUPPORTED) +
                        "；也可以在 ext.py 里注册新格式。")

    name = os.path.splitext(os.path.basename(path))[0]
    notes: list[str] = []
    marks: list[dict] = []

    if ext == ".cdxml":
        mol, notes, marks = parse_cdxml(path)
    elif ext == ".cdx":
        mol, n_mol = _load_by_obabel(path, "cdx")
        notes.append("CDX 是二进制格式，经 Open Babel 转换；如结果不对，请改存 CDXML。")
        if n_mol > 1:
            notes.append(f"文件里有 {n_mol} 个互不相连的结构（ChemDraw 一页画了多个？），"
                         f"这里取了最大的一个。想看别的，在 ChemDraw 里单独复制出来另存。")
    elif ext in (".mol", ".mdl"):
        mol = _load_mol_file(path)
    elif ext in (".sdf", ".sd"):
        mol, note = _load_sdf(path)
        if note:
            notes.append(note)
    elif ext in (".smi", ".smiles", ".can"):
        mol, note = _load_smiles_file(path)
        if note:
            notes.append(note)
    elif ext == ".mol2":
        mol, _n = _load_by_obabel(path, "mol2")
        notes.append("MOL2 经 Open Babel 转换。")
    elif ext == ".pdb":
        mol = Chem.MolFromPDBBlock(open(path, "rb").read().decode("latin-1"),
                                   removeHs=False, sanitize=True)
        if mol is None:
            raise FileError("PDB 里没有可识别的有机小分子（蛋白质大分子不支持）。")
    elif ext == ".rxn":
        smi = _run_obabel(path, "rxn", "smi")
        prod = smi.split(">>")[-1].split("\t")[0]
        mol = Chem.MolFromSmiles(prod)
        if mol is None:
            raise FileError("RXN 里没读出产物结构。")
        notes.append("反应文件，只判断产物一侧。")
    else:
        raise FileError(f"暂不支持 {ext}")

    if mol is None or mol.GetNumAtoms() == 0:
        raise FileError("文件读到了，但里面没有可识别的结构。")

    mol = _tidy(mol)
    if mol is None:
        raise FileError("结构能读出来，但化合价不合法（常见原因：电荷没标、"
                        "芳香键画成单双键以外的形式）。在 ChemDraw 里用 Structure → "
                        "Check Structure 检查一下。")

    return {"mol": mol, "fmt": fmt, "ext": ext, "name": name, "note": notes,
            "marks": marks, "smiles": Chem.MolToSmiles(mol),
            "path": path, "file": os.path.basename(path)}


def _strip_dummies(mol):
    """去掉画图时留下的 * / A 标记原子，否则它们会混进片段里。"""
    idx = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() == 0]
    if not idx:
        return mol
    rw = Chem.RWMol(mol)
    for i in sorted(idx, reverse=True):
        rw.RemoveAtom(i)
    m = rw.GetMol()
    try:
        Chem.SanitizeMol(m)
    except Exception:
        pass
    return m


def _tidy(mol):
    """去标记原子、去氢、补芳香性，尽量让它能参与后续匹配。"""
    if mol is None:
        return None
    mol = _strip_dummies(mol)
    try:
        mol = Chem.RemoveHs(mol)
    except Exception:
        pass
    try:
        Chem.SanitizeMol(mol)
    except Exception:
        try:
            Chem.SanitizeMol(mol, Chem.SanitizeFlags.SANITIZE_ALL ^
                             Chem.SanitizeFlags.SANITIZE_PROPERTIES)
        except Exception:
            return None
    return mol


def _load_mol_file(path: str):
    # 不走 MolFromMolFile：RDKit 在 Windows 上遇到中文路径会直接抛 OSError
    block = open(path, "rb").read().decode("latin-1")
    mol = Chem.MolFromMolBlock(block, sanitize=True, removeHs=False)
    if mol is None:
        mol = Chem.MolFromMolBlock(block, sanitize=False, removeHs=False)
    if mol is None:
        raise FileError("MOL 文件解析失败（不是标准 MDL 格式？）。")
    return mol


def _load_sdf(path: str):
    raw = open(path, "rb").read()
    supp = Chem.ForwardSDMolSupplier(io.BytesIO(raw), sanitize=True, removeHs=False)
    best, best_n, total = None, -1, 0
    for m in supp:
        if m is None:
            continue
        total += 1
        if m.GetNumAtoms() > best_n:
            best, best_n = m, m.GetNumAtoms()
    if best is None:
        raise FileError("SDF 里没有成功解析出分子。")
    note = ""
    if total > 1:
        note = f"SDF 里有 {total} 个结构，取原子数最多的一个（{best_n} 个原子）。"
    return best, note


def _load_smiles_file(path: str):
    lines = [ln for ln in _read_text(path).splitlines() if ln.strip()
             and not ln.strip().startswith("#")]
    if not lines:
        raise FileError("SMILES 文件是空的。")
    best, best_n = None, -1
    for ln in lines:
        smi = ln.split("\t")[0].strip().split()[0]
        m = Chem.MolFromSmiles(smi)
        if m is not None and m.GetNumAtoms() > best_n:
            best, best_n = m, m.GetNumAtoms()
    if best is None:
        raise FileError("SMILES 文件里的结构一个都解析不了。")
    note = f"文件里有 {len(lines)} 条 SMILES，取原子数最多的一个。" if len(lines) > 1 else ""
    return best, note


def _load_by_obabel(path: str, infmt: str):
    """返回 (分子, 文件里独立结构的个数)。"""
    smi_text = _run_obabel(path, infmt, "smi")
    best, best_n, n_ok = None, -1, 0
    for ln in smi_text.splitlines():
        if not ln.strip():
            continue
        smi = ln.split("\t")[0].strip()
        if not smi:
            continue
        m = Chem.MolFromSmiles(smi)
        if m is None:
            m = Chem.MolFromSmiles(smi, sanitize=False)
            if m is not None:
                try:
                    Chem.SanitizeMol(m)
                except Exception:
                    m = None
        if m is not None:
            n_ok += 1
            if m.GetNumAtoms() > best_n:
                best, best_n = m, m.GetNumAtoms()
    if best is None:
        raise FileError("转换出来了，但没有一个结构能被识别。")
    return best, n_ok


# ---------------------------------------------------------------- 剪贴板

def _as_bytes(data):
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("latin-1", errors="ignore")
    try:
        return bytes(data or b"")
    except Exception:
        return b""


def _mol_from_text(txt: str):
    """文本里可能是 MOL 块，也可能就一条 SMILES。"""
    if not txt or len(txt.strip()) < 3:
        return None
    # 注意不能 strip()：MOL 块第一行是（可能为空的）标题行，去掉就会错位
    t = txt.replace("\r\n", "\n").rstrip()
    if "V2000" in t or "V3000" in t:
        return Chem.MolFromMolBlock(t, removeHs=False, sanitize=True)
    if "$$$$" in t:
        supp = Chem.ForwardSDMolSupplier(io.BytesIO(t.encode("utf-8")), removeHs=False)
        best = None
        for m in supp:
            if m is not None and (best is None or m.GetNumAtoms() > best.GetNumAtoms()):
                best = m
        return best
    smis = [ln.split("\t")[0].strip() for ln in t.splitlines() if ln.strip()]
    if smis and len(smis[0]) < 200:
        return Chem.MolFromSmiles(smis[0])
    return None


def _clip_info(mol, fmt: str, note: str) -> dict:
    mol = _tidy(mol)
    if mol is None:
        raise FileError("剪贴板里的结构化合价不合法（电荷没标？），判不了。")
    return {"mol": mol, "fmt": fmt, "ext": ".cdx", "name": "剪贴板",
            "note": [note] if note else [], "marks": [],
            "smiles": Chem.MolToSmiles(mol), "file": "（剪贴板）", "path": None}


def load_clipboard() -> dict:
    """从剪贴板读一个结构。在 ChemDraw 里选中片段按 Ctrl+C 即可。"""
    try:
        import win32clipboard as wcb
        import win32con
    except Exception:
        raise FileError("读剪贴板要 pywin32，装一下：pip install pywin32")
    if Chem is None:
        raise FileError("没有 RDKit，无法解析结构。")

    entries = []
    wcb.OpenClipboard()
    try:
        f = 0
        while True:
            f = wcb.EnumClipboardFormats(f)
            if not f:
                break
            try:
                name = wcb.GetClipboardFormatName(f) or ""
            except Exception:
                name = ""
            entries.append((f, name))
        if not entries:
            raise FileError("剪贴板是空的。先在 ChemDraw 里选中要判的片段，按 Ctrl+C。")

        # 1) ChemDraw 复制时放进去的二进制格式
        for f, name in entries:
            if "chemdraw" not in name.lower():
                continue
            try:
                raw = _as_bytes(wcb.GetClipboardData(f))
            except Exception:
                continue
            if len(raw) < 32:
                continue
            d = tempfile.mkdtemp(prefix="ee_clip_")
            try:
                fp = os.path.join(d, "clip.cdx")
                open(fp, "wb").write(raw)
                mol, n_mol = _load_by_obabel(fp, "cdx")
            except FileError as e:
                raise FileError("读到 ChemDraw 的剪贴板数据了，但解析失败：" + str(e))
            finally:
                shutil.rmtree(d, ignore_errors=True)
            note = "结构来自剪贴板（ChemDraw 复制）。"
            if n_mol > 1:
                note += f" 你一次复制了 {n_mol} 个结构，这里取最大的一个。"
            return _clip_info(mol, "剪贴板 · ChemDraw 格式", note)

        # 2) 文本（复制成 SMILES / MOL 时走这条）
        for f, _name in entries:
            if f not in (win32con.CF_UNICODETEXT, win32con.CF_TEXT):
                continue
            try:
                txt = wcb.GetClipboardData(win32con.CF_UNICODETEXT)
            except Exception:
                continue
            mol = _mol_from_text(txt or "")
            if mol is not None:
                return _clip_info(mol, "剪贴板 · 文本", "结构来自剪贴板（文本格式）。")
    finally:
        wcb.CloseClipboard()

    raise FileError("剪贴板里没找到结构。\n"
                    "  在 ChemDraw 里用选择工具框住片段 → Ctrl+C，再点「从剪贴板」。\n"
                    "  只复制了图片是读不出来的，要复制结构本身。")


# ---------------------------------------------------------------- CDXML

_BOND_ORDER = {
    "1": Chem.BondType.SINGLE if Chem else None,
    "2": Chem.BondType.DOUBLE if Chem else None,
    "3": Chem.BondType.TRIPLE if Chem else None,
    "4": Chem.BondType.QUADRUPLE if Chem else None,
    "1.5": Chem.BondType.AROMATIC if Chem else None,
}

_PT_TO_ANG = 1.5 / 14.4      # ChemDraw 默认键长 14.4 pt ≈ 1.5 Å


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# CDXML 里手画的圈/框就是这些图形元素，带 BoundingBox（单位 pt）
_GRAPHIC_TAGS = {"ellipse", "circle", "oval", "rect", "roundedrect", "polygon"}

# 这些 NodeType 不是真原子：缩写基团、外部连接点、R 基、查询原子
_SKIP_NODETYPES = {"Fragment", "Nickname", "GenericNickname",
                   "ExternalConnectionPoint", "Rgroup", "Unspecified"}


def _bbox_of(node):
    bb = node.get("BoundingBox")
    if not bb:
        return None
    nums = []
    for tok in bb.replace(",", " ").split():
        try:
            nums.append(float(tok))
        except ValueError:
            return None
    if len(nums) < 4:
        return None
    return (min(nums[0], nums[2]), min(nums[1], nums[3]),
            max(nums[0], nums[2]), max(nums[1], nums[3]))


def _walk(node, atoms, bonds, warns, marks=None, alias=None):
    """遍历 CDXML。

    `alias` 用来处理“折叠片段”：ChemDraw 会把一个通过外部连接点挂上去的
    基团写成一个 `<n NodeType="Fragment">`，真正的原子在它内部的
    `<fragment>` 里（坐标是全图绝对坐标）。这时要展开内部原子，并把外层
    节点的 id 映射到连接点附近的那个原子，父级指向它的键才不会丢。
    """
    if alias is None:
        alias = {}
    for ch in node:
        tag = _local(ch.tag)
        if tag == "n":
            node_type = (ch.get("NodeType") or "").strip()
            inner = [x for x in ch if _local(x.tag) == "fragment"]
            if inner:
                before = len(atoms)
                inner_alias = {}
                for fr in inner:
                    _walk(fr, atoms, bonds, warns, marks, inner_alias)
                added = atoms[before:]
                if not added:
                    label = ch.get("Label") or node_type or "缩写"
                    warns.append(f"缩写基团「{label}」没有可展开的结构，已跳过。")
                    continue
                # 连接点：ExternalConnectionPoint 的坐标 → 最近的内部原子
                target = None
                ecps = [x for x in ch.iter()
                        if _local(x.tag) == "n" and
                        (x.get("NodeType") or "") == "ExternalConnectionPoint"]
                probe = _pos(ecps[0].get("p")) if ecps else _pos(ch.get("p"))
                if probe:
                    best, bd = None, 1e9
                    for a in added:
                        if not a.get("p"):
                            continue
                        d = (a["p"][0] - probe[0]) ** 2 + (a["p"][1] - probe[1]) ** 2
                        if d < bd:
                            best, bd = a, d
                    target = best
                target = target or added[0]
                alias[str(ch.get("id"))] = str(target["id"])
                for x in ecps:      # 连接点本身不是原子，键挂在它上面时要转向
                    eid = x.get("id")
                    if eid is not None:
                        alias[str(eid)] = str(target["id"])
                for k, v in inner_alias.items():
                    alias[k] = v
                continue
            if node_type in _SKIP_NODETYPES:
                # ExternalConnectionPoint / R 基之类：不是原子，静默跳过
                continue
            z = _element_number(ch)
            if z is None:
                warns.append("有 1 个原子没有元素标记（可能是查询原子 / A 标记），已跳过。")
                continue
            atoms.append({
                "id": str(ch.get("id")),
                "z": z,
                "chg": _int_attr(ch, "Charge"),
                "nh": _int_attr(ch, "NumHydrogens"),
                "p": _pos(ch.get("p")),
            })
        elif tag == "b":
            bonds.append({
                "B": str(ch.get("B")), "E": str(ch.get("E")),
                "order": (ch.get("Order") or "1").strip(),
            })
        else:
            if marks is not None:
                low = tag.lower()
                if low in _GRAPHIC_TAGS or low == "graphic":
                    bb = _bbox_of(ch)
                    if bb:
                        marks.append({"kind": low, "box": bb})
            _walk(ch, atoms, bonds, warns, marks, alias)


def _element_number(node) -> int | None:
    el = node.get("Element")
    if el is not None:
        el = el.strip()
        if el.isdigit():
            n = int(el)
            return n or None          # Element="0" 是查询原子/占位，不是真元素
        sym = el[:1].upper() + el[1:].lower()
        a = Chem.GetPeriodicTable().GetAtomicNumber(sym) if Chem else 0
        return a or None
    # 没有 Element 但有 Label="O" 之类
    lbl = (node.get("Label") or "").strip()
    if lbl and lbl[:1].isalpha():
        sym = lbl[:1].upper() + lbl[1:2].lower()
        try:
            a = Chem.GetPeriodicTable().GetAtomicNumber(sym) if Chem else 0
        except Exception:
            a = 0
        if a:
            return a
    # CDXML 的约定：不写 Element 就是碳（ChemDraw 保存时会把 C 省略掉，
    # 一个 75 个碳的结构只显式写 O/N/Cl 等杂原子）
    return 6


def _int_attr(node, key) -> int | None:
    v = node.get(key)
    if v is None or not str(v).strip():
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _pos(p: str | None):
    if not p:
        return None
    parts = p.split()
    if len(parts) < 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def _atoms_in_box(mol, box, kind="graphic") -> list[int]:
    """落在圈/框里的原子。椭圆按椭圆判，其它按矩形判，都留点余量。"""
    if mol.GetNumConformers() == 0:
        return []
    conf = mol.GetConformer()
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = max((x1 - x0) / 2, 0.15), max((y1 - y0) / 2, 0.15)
    out = []
    for a in mol.GetAtoms():
        if a.GetAtomicNum() <= 1:
            continue
        p = conf.GetAtomPosition(a.GetIdx())
        if kind in ("ellipse", "circle", "oval"):
            v = ((p.x - cx) / (rx * 1.12)) ** 2 + ((p.y - cy) / (ry * 1.12)) ** 2
            if v <= 1.0:
                out.append(a.GetIdx())
        elif x0 - 0.25 <= p.x <= x1 + 0.25 and y0 - 0.25 <= p.y <= y1 + 0.25:
            out.append(a.GetIdx())
    return out


def _page_objects(root):
    """取箭头与独立文字（不含连在原子上的标签）。

    ChemDraw 把独立文字和箭头放在页面里，原子标签则嵌在 `<n>` 里。
    箭头可能直接挂在 `<page>` 下，也可能嵌在 `<scheme>` 里，所以整页递归找；
    遇到 `<n>` 就停止收集文字，避免把原子标签当成独立文字。
    """
    arrows, labels = [], []

    def walk(node, in_atom):
        for ch in node:
            tag = _local(ch.tag)
            if tag == "arrow":
                head = _pos(ch.get("Head3D"))
                tail = _pos(ch.get("Tail3D"))
                if head and tail:
                    arrows.append({"x1": tail[0], "y1": tail[1],
                                   "x2": head[0], "y2": head[1]})
            elif tag == "t" and not in_atom:
                text = "".join(x.text or "" for x in ch.iter()
                               if _local(x.tag) == "s").strip()
                p = _pos(ch.get("p"))
                if text and p:
                    labels.append({"x": p[0], "y": p[1], "text": text})
            if tag != "n":
                walk(ch, in_atom)

    for node in root.iter():
        if _local(node.tag) == "page":
            walk(node, False)
    return arrows, labels


def parse_cdxml_full(path: str | None = None, text: str | None = None) -> dict:
    """CDXML → 结构 + 箭头 + 文字（给画板读回用）。

    可以直接给文件路径，也可以给 ``text``（Ketcher 回写的内容不落盘）。
    返回 {"atoms", "bonds", "arrows", "labels", "notes", "marks", "error"}，
    坐标为 ChemDraw 的点（pt），y 轴朝上，由调用方决定怎么映射到画布。
    """
    out = {"atoms": [], "bonds": [], "arrows": [], "labels": [],
           "notes": [], "marks": [], "error": ""}
    if Chem is None:
        out["error"] = "没有 RDKit，无法解析 CDXML。"
        return out
    try:
        root = ET.fromstring(text if text is not None else _read_text(path))
    except ET.ParseError as e:
        out["error"] = f"CDXML 不是合法的 XML：{e}"
        return out
    alias = {}
    _walk(root, out["atoms"], out["bonds"], out["notes"], out["marks"], alias)
    if alias:                       # 折叠片段：把外层节点 id 换成内部真实原子
        for b in out["bonds"]:
            b["B"] = alias.get(b["B"], b["B"])
            b["E"] = alias.get(b["E"], b["E"])
        # 连接点常与所连原子重合，映射后会剩下自环和零长度“键”，要去掉
        pos = {a["id"]: a.get("p") for a in out["atoms"]}
        keep = []
        for b in out["bonds"]:
            if b["B"] == b["E"]:
                continue
            p, q = pos.get(b["B"]), pos.get(b["E"])
            if p and q and ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) < 1.0:
                continue
            keep.append(b)
        out["bonds"] = keep
    out["arrows"], out["labels"] = _page_objects(root)
    tbl = Chem.GetPeriodicTable()
    for a in out["atoms"]:
        try:
            a["sym"] = tbl.GetElementSymbol(int(a["z"]))
        except Exception:                                    # noqa: BLE001
            a["sym"] = "C"
    if not out["atoms"] and not out["arrows"] and not out["labels"]:
        out["error"] = ("这份 CDXML 里没有可读回的内容：既没有结构，"
                        "也没有箭头或文字。")
    elif not out["atoms"]:
        out["notes"].append("文件里只有箭头 / 文字，没有结构——已按反应式读回。")
    return out


def parse_cdxml(path: str):
    """CDXML → RDKit 分子。返回 (mol, notes, marks)。"""
    if Chem is None:
        raise FileError("没有 RDKit，无法解析 CDXML。")
    data = parse_cdxml_full(path)
    if data["error"]:
        raise FileError(data["error"])
    atoms, bonds, warns, raw_marks = (data["atoms"], data["bonds"],
                                      data["notes"], data["marks"])
    if not atoms:
        raise FileError("这份 CDXML 里没有结构：可能只画了箭头 / 文字，"
                        "或者结构全是缩写基团（需在 ChemDraw 里右键 Expand 后另存）。")

    rw = Chem.RWMol()
    id2idx: dict[str, int] = {}
    coords: list[tuple[float, float] | None] = []
    for a in atoms:
        at = Chem.Atom(a["z"])
        if a["chg"]:
            at.SetFormalCharge(a["chg"])
        if a["nh"] is not None:
            at.SetNoImplicit(True)
            at.SetNumExplicitHs(max(0, a["nh"]))
        idx = rw.AddAtom(at)
        id2idx[a["id"]] = idx
        coords.append(a["p"])

    skipped = 0
    for b in bonds:
        i = id2idx.get(b["B"])
        j = id2idx.get(b["E"])
        if i is None or j is None:
            skipped += 1
            continue
        if i == j:              # 折叠片段的“外层节点→连接点”会被映射成同一原子
            continue
        bt = _BOND_ORDER.get(b["order"])
        if bt is None:
            bt = Chem.BondType.SINGLE
        rw.AddBond(i, j, bt)
    if skipped:
        warns.append(f"{skipped} 根键连到了被跳过的原子上，已忽略。")

    mol = rw.GetMol()
    if any(c is not None for c in coords):
        conf = Chem.Conformer(mol.GetNumAtoms())
        for i, c in enumerate(coords):
            x, y = (c if c else (0.0, 0.0))
            conf.SetAtomPosition(i, (x * _PT_TO_ANG, y * _PT_TO_ANG, 0.0))
        mol.AddConformer(conf, assignId=True)

    try:
        Chem.SanitizeMol(mol)
    except Exception:
        try:
            Chem.SanitizeMol(mol, Chem.SanitizeFlags.SANITIZE_ALL ^
                             Chem.SanitizeFlags.SANITIZE_PROPERTIES)
            warns.append("化合价有点问题（电荷可能没标），已按容错模式处理。")
        except Exception:
            raise FileError("CDXML 的结构化合价不合法，无法判定。\n"
                            "  在 ChemDraw 里检查是否有未标电荷的 N/O 或超价原子。")

    # 把圈/框的坐标换成 Å（和原子坐标同一套），挑出里面装了原子的那些
    marks: list[dict] = []
    heavy = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() > 1]
    seen_boxes: set[tuple] = set()
    for m in raw_marks:
        box = tuple(v * _PT_TO_ANG for v in m["box"])
        key = tuple(round(v, 2) for v in box)
        if key in seen_boxes:
            continue
        seen_boxes.add(key)
        inside = _atoms_in_box(mol, box, m["kind"])
        if not inside:
            continue
        if len(inside) >= max(3, int(len(heavy) * 0.85)):
            warns.append("图上有一个框几乎套住了整个结构，当成注释框忽略了。")
            continue
        marks.append({"kind": m["kind"], "box": box, "atoms": inside})
    marks.sort(key=lambda m: -len(m["atoms"]))
    return mol, warns, marks


# ---------------------------------------------------------------- 环与取代基

def ring_systems(mol) -> list[set[int]]:
    """把共享原子的环合并成一个稠环体系。"""
    rings = [set(r) for r in mol.GetRingInfo().AtomRings() if len(r) >= 3]
    merged = True
    while merged:
        merged = False
        for i in range(len(rings)):
            for j in range(i + 1, len(rings)):
                if rings[i] & rings[j]:
                    rings[i] |= rings[j]
                    del rings[j]
                    merged = True
                    break
            if merged:
                break
    return rings


def _is_aromatic(mol, atoms) -> bool:
    return all(mol.GetAtomWithIdx(i).GetIsAromatic() for i in atoms)


def ring_label(mol, atoms) -> str:
    syms = sorted({mol.GetAtomWithIdx(i).GetSymbol() for i in atoms})
    n = len(atoms)
    if syms == ["C"]:
        return {5: "五元碳环", 6: "苯环", 7: "七元碳环"}.get(n, f"{n} 元碳环")
    het = "".join(s for s in syms if s != "C")
    kind = "芳环" if _is_aromatic(mol, atoms) else "脂环"
    return f"{n} 元{kind}（含 {het}）"


def _fragment_atoms(mol, start: int, core: set[int]) -> set[int]:
    """从 start 出发、不穿过 core 能到达的所有原子。"""
    seen = {start}
    stack = [start]
    while stack:
        i = stack.pop()
        for nb in mol.GetAtomWithIdx(i).GetNeighbors():
            j = nb.GetIdx()
            if j in seen or j in core:
                continue
            seen.add(j)
            stack.append(j)
    return seen


def fragment_smiles(mol, atoms: set[int], root: int) -> str | None:
    """把一坨原子切出来，在 root 上接一个 * 连接点。"""
    keep = sorted(atoms)
    order = {old: new for new, old in enumerate(keep)}
    rw = Chem.RWMol(mol)
    for i in sorted((x for x in range(mol.GetNumAtoms()) if x not in atoms), reverse=True):
        rw.RemoveAtom(i)
    d = rw.AddAtom(Chem.Atom(0))
    rw.AddBond(order[root], d, Chem.BondType.SINGLE)
    m = rw.GetMol()
    try:
        Chem.SanitizeMol(m)
    except Exception:
        try:
            Chem.SanitizeMol(m, Chem.SanitizeFlags.SANITIZE_ALL ^
                             Chem.SanitizeFlags.SANITIZE_PROPERTIES)
        except Exception:
            return None
    return Chem.MolToSmiles(m)


def fragment_smiles_multi(mol, atoms: set[int], roots: list[int]) -> str | None:
    """把一坨原子切出来，在每个 root 上各接一个 * —— 桥连基团（两点连接）用。"""
    keep = sorted(atoms)
    order = {old: new for new, old in enumerate(keep)}
    rw = Chem.RWMol(mol)
    for i in sorted((x for x in range(mol.GetNumAtoms()) if x not in atoms), reverse=True):
        rw.RemoveAtom(i)
    for r in roots:
        d = rw.AddAtom(Chem.Atom(0))
        rw.AddBond(order[r], d, Chem.BondType.SINGLE)
    m = rw.GetMol()
    try:
        Chem.SanitizeMol(m)
    except Exception:
        try:
            Chem.SanitizeMol(m, Chem.SanitizeFlags.SANITIZE_ALL ^
                             Chem.SanitizeFlags.SANITIZE_PROPERTIES)
        except Exception:
            return None
    return Chem.MolToSmiles(m)


def _heavy_degree(mol, idx: int) -> int:
    return sum(1 for a in mol.GetAtomWithIdx(idx).GetNeighbors()
               if a.GetAtomicNum() > 1)


def find_substituents(mol) -> list[dict]:
    """找出所有「挂在环上的基团」。结构里完全没环时，才退化为整分子候选。"""
    systems = ring_systems(mol)
    out: list[dict] = []
    seen: set[frozenset] = set()

    if systems:
        # 有环就只在环上找取代基；找不到就返回空（说明是裸环，没有基团可判）
        aromatic = [s for s in systems if _is_aromatic(mol, s)]
        targets = aromatic or systems      # 没有芳环就用脂环，后面会标注

        for sysatoms in targets:
            for idx in sorted(sysatoms):
                atom = mol.GetAtomWithIdx(idx)
                for b in atom.GetBonds():
                    if b.IsInRing():
                        continue
                    other = b.GetOtherAtom(atom)
                    if other.GetAtomicNum() <= 1:      # 显式 H / 连接点 * 不算取代基
                        continue
                    if other.GetIdx() in sysatoms:
                        continue
                    frag = _fragment_atoms(mol, other.GetIdx(), sysatoms)
                    key = frozenset(frag)
                    if key in seen:
                        continue
                    seen.add(key)
                    smi = fragment_smiles(mol, frag, other.GetIdx())
                    if not smi:
                        continue
                    out.append({
                        "atoms": sorted(frag),
                        "root": other.GetIdx(),
                        "site": idx,          # 环上连接的那个原子，用来算邻/间/对
                        "smiles": smi,
                        "ring_atoms": sorted(sysatoms),
                        "ring_name": ring_label(mol, sysatoms),
                        "aromatic": _is_aromatic(mol, sysatoms),
                        "mode": "环上取代基",
                    })
        # 两个环互为取代基（联苯、二苯甲烷）时只留一条，否则会报两个一模一样的"苯基"
        keep = []
        for a in out:
            dup = False
            for b in keep:
                if (set(a["atoms"]) == set(b["ring_atoms"])
                        and set(b["atoms"]) == set(a["ring_atoms"])):
                    dup = True
                    break
            if not dup:
                keep.append(a)
        return keep

    # ---- 完全无环：整段结构当基团，连接点给几个候选 ----
    # 连接点越"重"越可能是主链（CF3 的 C 度为 4，F 只有 1），所以按重原子邻居数降序
    cand = []
    for a in mol.GetAtoms():
        if a.GetAtomicNum() <= 1:
            continue
        cand.append((-_heavy_degree(mol, a.GetIdx()), a.GetIdx()))
    cand.sort()
    for _, idx in cand[:4]:
        frag = _fragment_atoms(mol, idx, set())
        frag = {i for i in frag if mol.GetAtomWithIdx(i).GetAtomicNum() > 1}
        smi = fragment_smiles(mol, frag, idx)
        if not smi:
            continue
        sym = mol.GetAtomWithIdx(idx).GetSymbol()
        out.append({
            "atoms": sorted(frag), "root": idx, "smiles": smi,
            "ring_atoms": [], "ring_name": "（无环）",
            "aromatic": False,
            "mode": f"整段结构，连接点按 {sym}（第 {idx + 1} 个原子）算",
        })
    return out


def _ring_path_len(mol, ring_atoms: set[int], a: int, b: int) -> int | None:
    if a not in ring_atoms or b not in ring_atoms:
        return None
    dist = {a: 0}
    queue = [a]
    while queue:
        cur = queue.pop(0)
        if cur == b:
            return dist[cur]
        for nb in mol.GetAtomWithIdx(cur).GetNeighbors():
            j = nb.GetIdx()
            if j in ring_atoms and j not in dist:
                dist[j] = dist[cur] + 1
                queue.append(j)
    return None


POS_NAME = {1: "邻位", 2: "间位", 3: "对位"}


# ---------------------------------------------------------------- 自定义片段

def selection_candidates(mol, picked) -> list[tuple[set[int], set[int], str]]:
    """把用户圈的原子切分成「环骨架 + 基团本体」，给出几种可能，由调用方挑一个能用的。

    1. 圈里没有完整环 → 圈的就是基团本身（如圈 -O-CH2-O-）
    2. 圈里有完整环 → 环是骨架，剩下的是基团（如圈苯环 + -OCH3）
    3. 圈里是稠环的一部分 → 被切开的那些环原子只是连接点
       （如苯并二氧戊环只圈五元环，两个芳碳是连接点，基团是 -O-CH2-O-）
    """
    picked = {i for i in picked if mol.GetAtomWithIdx(i).GetAtomicNum() > 1}
    rings = [set(r) for r in mol.GetRingInfo().AtomRings()]
    out: list[tuple[set[int], set[int], str]] = []

    full = [r for r in rings if r <= picked]
    if full:
        core = set().union(*full)
        ring_atoms = set().union(*rings) if rings else set()
        severed = {i for i in core
                   if any(nb.GetIdx() in ring_atoms and nb.GetIdx() not in picked
                          for nb in mol.GetAtomWithIdx(i).GetNeighbors())}
        if severed:
            out.append((severed, picked - severed, "稠环被切开，切开的环原子当连接点"))
        out.append((core, picked - core, "圈里包含完整环，环当骨架"))

    out.append((set(), picked, "圈的就是整块基团"))
    return [(c, g, why) for c, g, why in out if g]


def _attach_pairs(mol, group: set[int]) -> list[tuple[int, int]]:
    """基团与外界相连的键：[(基团里的原子, 外面的原子)]。"""
    out = []
    for g in sorted(group):
        for nb in mol.GetAtomWithIdx(g).GetNeighbors():
            j = nb.GetIdx()
            if j in group or nb.GetAtomicNum() <= 1:
                continue
            out.append((g, j))
    return out


def _has_pi_to_hetero(atom, group: set[int]) -> bool:
    """这个原子是否（在片段内）双键连到 O/N/S —— 用来认羰基、磺酰。"""
    for b in atom.GetBonds():
        if b.GetBondType() != Chem.BondType.DOUBLE:
            continue
        other = b.GetOtherAtom(atom)
        if other.GetAtomicNum() in (7, 8, 16) and other.GetIdx() in group:
            return True
    return False


def atom_effect(mol, idx: int, group: set[int]) -> tuple[str, int]:
    """基团里这个连接原子往母体上递电子还是拉电子。返回 (说明, +1给/-1吸/0不定)。"""
    a = mol.GetAtomWithIdx(idx)
    sym = a.GetSymbol()
    inside = [n for n in a.GetNeighbors() if n.GetIdx() in group]

    if sym in ("O", "S"):
        if any(_has_pi_to_hetero(n, group) for n in inside):
            return "连着羰基/磺酰，-I 压过 +M，偏吸电子", -1
        return "孤对直接共轭到环上，+M 强于 -I，给电子", 1
    if sym == "N":
        if any(_has_pi_to_hetero(n, group) for n in inside):
            return "酰胺型氮，孤对被羰基拉走，接近中性", 0
        return "孤对参与共轭，+M 给电子", 1
    if sym == "C":
        if any(b.GetBondType() == Chem.BondType.DOUBLE for b in a.GetBonds()):
            return "sp2 碳且带双键，-M / -I 吸电子", -1
        if all(n.GetAtomicNum() in (1, 6) for n in a.GetNeighbors()):
            return "烷基碳，只有弱的 +I", 1
        return "碳上接了杂原子，-I 与 +M 互相抵消，方向不明", 0
    if sym in ("F", "Cl", "Br", "I"):
        return "-I 远强于 +M，吸电子", -1
    return "不在判断规则内，只能看它连的是什么", 0


def _bridge_item(mol, smi: str, group: set[int], pairs, no: int) -> dict:
    """桥连基团（两端都连在母体上）：没有 Hammett 常数，只给定性方向。"""
    sites = sorted({o for _g, o in pairs})
    ring_atoms: set[int] = set()
    for s in sites:
        for sysatoms in ring_systems(mol):
            if s in sysatoms:
                ring_atoms |= sysatoms

    dist = None
    if len(sites) == 2 and ring_atoms:
        dist = _ring_path_len(mol, ring_atoms, sites[0], sites[1])

    attach = f"{len(pairs)} 处（{'、'.join(mol.GetAtomWithIdx(g).GetSymbol() for g, _ in pairs)}）"
    if len(sites) == 2 and ring_atoms:
        attach += f"，两点在环上相隔 {dist} 根键（{POS_NAME.get(dist, '')}），都直接连在同一个环上"
    elif ring_atoms:
        attach += "，连在环上"

    lines = [("结构", smi), ("连接点", attach)]

    total = 0
    for g, _o in pairs:
        text, sign = atom_effect(mol, g, group)
        total += sign
        lines.append((mol.GetAtomWithIdx(g).GetSymbol() + "（连接原子）", text))

    if total > 0:
        verdict = "给电子"
        arom = "两个给电子点叠加，环被明显活化；亲电取代比苯容易，落在它们的邻、对位"
    elif total < 0:
        verdict = "吸电子"
        arom = "整体拉电子，环被钝化；亲电取代变难，主要上它们的间位"
    else:
        verdict = "方向不明"
        arom = "几个连接点的作用互相抵消，得看具体反应条件"

    lines.append(("合并结论", f"{verdict}（按各连接点的 ±I / ±M 定性相加）"))
    lines.append(("芳环表现", arom))
    lines.append(("提醒", "Hammett σ 只对单价基团有定义。桥连基团（两端同时挂在母体上）"
                          "没有可靠的 σ 值，上面只是方向判断，不能当数值用。"))
    return {"no": no, "frag": smi, "rec": None, "err": "",
            "lines": lines, "bridge": True, "custom": True,
            "atoms": sorted(group), "roots": [g for g, _ in pairs]}


def _disp_width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def bridge_text(item: dict, indent: str = "    ", width: int = 62) -> list[str]:
    """把桥连说明排成对齐的多行（续行缩进到正文位置）。"""
    import engine
    out = []
    for label, text in item["lines"]:
        pad = indent + " " * (_disp_width(label) + 1)
        body = engine._wrap(text, pad, width).split("\n")
        out.append(indent + label + " " + body[0][len(pad):])
        out.extend(body[1:])
    return out


def analyze_selection(mol, picked, no: int = 1) -> dict:
    """把「用户圈出来的一坨原子」变成一条可判定的记录。"""
    import engine

    heavy = {i for i in picked if mol.GetAtomWithIdx(i).GetAtomicNum() > 1}
    n_heavy = sum(1 for a in mol.GetAtoms() if a.GetAtomicNum() > 1)
    if n_heavy >= 3 and len(heavy) >= n_heavy:
        raise FileError("圈的是整个分子，没有「取代基」可判。\n"
                        "  只圈环外那一块（可以连上它连着的那个环原子），"
                        "或者干脆不圈——默认会自动找出所有取代基。")

    cands = selection_candidates(mol, heavy)
    if not cands:
        raise FileError("没圈到能判的原子。")

    bad_bond = "这块原子的化合价不合法，切不出片段。检查一下是不是圈到了半个双键。"
    for core, group, _why in cands:
        pairs = _attach_pairs(mol, group)
        if not pairs:
            continue

        # 圈的正是一整个环、环上还挂着别的基团 → 环本身不是取代基
        if len(pairs) > 1 and _is_whole_ring(mol, group):
            raise FileError(f"你圈的是一个完整的环，环上还连着 {len(pairs)} 处别的基团，"
                            f"整个环本身不是取代基。\n"
                            f"  改成只圈环外那一块（可以连上环上那个碳），它才会被当成基团。")

        if len(pairs) > 1:                    # 桥连，σ 体系不适用
            smi = fragment_smiles_multi(mol, group, [g for g, _ in pairs])
            if not smi:
                continue
            return _bridge_item(mol, smi, group, pairs, no)

        g, site = pairs[0]
        smi = fragment_smiles(mol, group, g)
        if not smi:
            continue
        return _single_item(mol, smi, group, g, site, no)

    raise FileError(bad_bond)


def _is_whole_ring(mol, atoms) -> bool:
    atoms = set(atoms)
    return any(set(r) == atoms for r in mol.GetRingInfo().AtomRings())


def _single_item(mol, smi: str, group: set[int], root: int, site: int, no: int) -> dict:
    """单价片段：正常查表 / 推断，给 σ 值。"""
    import engine

    grp = engine.lookup_smiles(smi) or engine.infer_from_smiles(smi)
    if grp is None:
        return {"no": no, "frag": smi, "rec": None, "custom": True,
                "err": f"这个片段（{smi}）既不在表里，也没法按结构推断"}

    ring_atoms: set[int] = set()
    for sysatoms in ring_systems(mol):
        if site in sysatoms:
            ring_atoms |= sysatoms

    rec = engine.report(grp)
    rec["src"] = {
        "atoms": sorted(group), "root": root, "site": site, "smiles": smi,
        "ring_atoms": sorted(ring_atoms),
        "ring_name": ring_label(mol, ring_atoms) if ring_atoms else "（无环）",
        "aromatic": _is_aromatic(mol, ring_atoms) if ring_atoms else False,
        "mode": "圈选片段",
    }
    if len(group) > 15:
        rec["tips"].insert(0, "这个片段很大，σ 值本来只对简单基团有定义；"
                              "这里只能按连接原子的性质定个性。")
    if ring_atoms and not rec["src"]["aromatic"]:
        rec["tips"].insert(0, "连的是脂环不是芳环，σ 值严格说不上适用；只能按诱导效应看方向。")
    return {"no": no, "frag": smi, "rec": rec, "err": "", "custom": True}


# ---------------------------------------------------------------- 对外主入口

def analyze_file(path: str, picked=None, use_mark: bool = True,
                 selection: str | None = None) -> dict:
    """读文件 → 找取代基 → 逐个判定。返回给 CLI / GUI 共用的结构。

    picked 给了就只判这一坨原子（用户自己圈的），否则自动找环上取代基；
    CDXML 里画了圈/框时，默认按圈里的原子来（use_mark=False 可关掉）。
    """
    return _analyze_loaded(load(path), picked, use_mark, selection)


def analyze_mol(mol, name: str = "绘制结构", notes=None,
                file: str = "绘制结构") -> dict:
    """把一个已经构造好的 RDKit 分子送进与 analyze_file() 完全相同的分析链。

    ELN 的「绘制结构」「当前记录」「剪贴板 SMILES」都是先有 mol 再有结论，
    走这里就不用临时落盘再读回来。返回结构与 analyze_file() 一致
    （mol / items / notes / smiles / file / fmt …）。
    """
    if mol is None or mol.GetNumAtoms() == 0:
        raise FileError("这个结构里没有原子，先画几个原子再判定。")
    info = {
        "mol": mol,
        "fmt": "绘制结构",
        "ext": "",
        "name": name,
        "note": list(notes or []),
        "marks": [],
        "smiles": Chem.MolToSmiles(mol),
        "path": "",
        "file": file,
    }
    return _analyze_loaded(info)


def analyze_clipboard(picked=None, selection: str | None = None) -> dict:
    """判剪贴板里的结构（在 ChemDraw 里选中片段 Ctrl+C 即可）。"""
    return _analyze_loaded(load_clipboard(), picked, use_mark=False, selection=selection)


def _analyze_loaded(info: dict, picked=None, use_mark: bool = True,
                    selection: str | None = None) -> dict:
    import engine

    path = info.get("path") or "（剪贴板）"
    mol = info["mol"]
    auto = False

    if selection:
        picked = ext_api.run_selection(selection, mol,
                                       {"path": path, "marks": info.get("marks") or [],
                                        "picked": picked})
    elif not picked and use_mark and info.get("marks"):
        best = info["marks"][0]
        picked = best["atoms"]
        auto = True
        info["note"].append(
            f"图上检测到你画的一个圈/框，包含 {len(picked)} 个原子，"
            f"就按这一块判。不想这样的话，把那个图形删掉再存。")

    if mol.GetNumAtoms() > 40:
        info["note"].append(
            f"这个结构有 {mol.GetNumAtoms()} 个原子，σ 值是给简单基团用的；"
            f"对大侧链只能看趋势，别当数值依据。")

    if picked:
        items = [analyze_selection(mol, picked, no=1)]
        subs = []
    else:
        subs = find_substituents(mol)
        items = []
        for n, s in enumerate(subs, 1):
            g = engine.lookup_smiles(s["smiles"]) or engine.infer_from_smiles(s["smiles"])
            if g is None:
                items.append({"no": n, "frag": s["smiles"], "rec": None,
                              "err": f"这个片段（{s['smiles']}）既不在表里，也没法按结构推断"})
                continue
            rec = engine.report(g)
            rec["src"] = dict(s, no=n)
            if len(s["atoms"]) > 15:
                rec["tips"].insert(0, "这个取代基很大，σ 值本来只对简单基团有定义；"
                                      "这里只能按连接原子的性质定个性。")
            if s["ring_atoms"] and not s["aromatic"]:
                rec["tips"].insert(0, "结构里画的是脂环不是芳环，σ 值严格说不适用；"
                                      "这里只能按诱导效应看方向。")
            items.append({"no": n, "frag": s["smiles"], "rec": rec, "err": ""})

        # 无环结构会给出多个连接点候选，判不出来的是错误尝试，别拿去干扰
        if any(it["rec"] for it in items):
            items = [it for it in items if it["rec"]]
            for n, it in enumerate(items, 1):
                it["no"] = n
                it["rec"]["src"]["no"] = n

    # 同一环上多个取代基 → 标出相对位置
    for it in items:
        if not it["rec"]:
            continue
        src = it["rec"]["src"]
        mates = []
        for other in items:
            if other is it or not other["rec"]:
                continue
            o = other["rec"]["src"]
            if o["ring_atoms"] != src["ring_atoms"] or not src["ring_atoms"]:
                continue
            d = _ring_path_len(mol, set(src["ring_atoms"]),
                               src.get("site", -1), o.get("site", -1))
            mates.append((other["no"], rec_name(other), d))
        it["rec"]["src"]["mates"] = mates

    return ext_api.run_hooks({
        "path": path,
        "file": info.get("file") or os.path.basename(path),
        "name": info["name"],
        "fmt": info["fmt"],
        "smiles": info["smiles"],
        "notes": info["note"],
        "mol": mol,
        "items": items,
        "picked": sorted(picked) if picked else [],
        "from_mark": auto,
        "n_atoms": mol.GetNumAtoms(),
        "n_rings": len(ring_systems(mol)),
    })


def rec_name(item: dict) -> str:
    return item["rec"]["name"] if item["rec"] else item["frag"]


def position_note(src: dict) -> str:
    """同一环上多个取代基时，说明它和别人的相对位置。"""
    mates = src.get("mates") or []
    if not mates:
        return ""
    bits = []
    for no, _name, dist in mates:
        if dist is None:
            continue
        bits.append(f"与 {no} 号{POS_NAME.get(dist, f'相隔 {dist} 根键')}")
    return "；".join(bits)


def summarize(res: dict) -> str:
    """命令行用的汇总。"""
    import engine
    W = 62
    out = [f"文件    {res['file']}",
           f"格式    {res['fmt']}",
           f"结构    {res['smiles']}   （{res['n_atoms']} 个重原子，{res['n_rings']} 个环系）"]
    for note in res["notes"]:
        out.append(engine._wrap(note, "提示    ", W))
    if not res["items"]:
        out.append(engine._wrap("没有在结构里找到挂在环上的取代基（只画了裸环？）。"
                                "取代基要画在环外面，通过一根单键连上去；"
                                "也可以在图上圈出要判的那一块，或者用 --atoms 指定原子。",
                                "结果    ", W))
        return "\n".join(out)

    custom = bool(res.get("picked"))
    out.append("")
    out.append("判定你圈出来的这一块：" if custom
               else f"检出 {len(res['items'])} 个取代基：")
    for it in res["items"]:
        if it.get("bridge"):
            out.append(f"  {it['no']}. 自定义片段 {it['frag']}  （桥连，只定性）")
            continue
        if not it["rec"]:
            out.append(f"  {it['no']}. {it['frag']}  （无法判定：{it['err']}）")
            continue
        r = it["rec"]
        sp = f"σp {engine.signed(r['sp'])}" if r["sp"] is not None else "无 σp"
        out.append(f"  {it['no']}. {r['name']:<12} {sp:<12} {r['cls']}")
        pos = position_note(r["src"])
        if pos:
            out.append(f"     {pos}")
    out.append("")
    for it in res["items"]:
        if it.get("bridge"):
            out.append("=" * W)
            out.append(f"[{it['no']}] 自定义片段 · 桥连（多个连接点）")
            out.extend(bridge_text(it, "    ", W))
            continue
        if not it["rec"]:
            continue
        src = it["rec"]["src"]
        out.append("=" * W)
        out.append(f"[{it['no']}] {src['mode']} · {src['ring_name']}")
        out.append(engine.format_report(it["rec"], W))
    return "\n".join(out)


# ---------------------------------------------------------------- 内置选法
# 这些也走 ext 的注册表：想加新选法，照抄一个就行，不用改 analyze_file。

@ext_api.selection("auto", "自动找环上的取代基")
def _pick_auto(mol, ctx):
    return None                     # None = 交给默认的自动查找


@ext_api.selection("mark", "按 ChemDraw 里画的圈/框")
def _pick_mark(mol, ctx):
    marks = ctx.get("marks") or []
    if not marks:
        raise FileError("这个文件里没有画圈/框。在 ChemDraw 里用椭圆或矩形工具圈一下，"
                        "另存为 CDXML 再打开。")
    return list(marks[0]["atoms"])


@ext_api.selection("atoms", "按指定的原子序号")
def _pick_atoms(mol, ctx):
    picked = ctx.get("picked") or []
    if not picked:
        raise FileError("没有指定原子（--atoms 7,8,9）。")
    return list(picked)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("用法：python structure.py 文件.cdx")
        print("Open Babel：", obabel_version())
        raise SystemExit(0)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        print(summarize(analyze_file(sys.argv[1])))
    except FileError as e:
        print("[?] " + str(e))
        raise SystemExit(1)
