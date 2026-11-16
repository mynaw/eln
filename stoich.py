# -*- coding: utf-8 -*-
"""反应组成双向实时计算引擎（纯函数，不依赖 GUI，可单独自检）。

核心思路：
- 摩尔量：质量单位按 g 换算（mg/kg 自动折算），配合分子量算 mmol；
  直接写 mmol / mol 的行按摩尔数入账。
- 双向之一（改用量）：被改的行成为「基准」——其它行里
  · 当量已填、有分子量的 → 反推所需用量（计划投料量）；
  · 当量没填但用量已填的 → 逆算出它相对基准的实际当量。
  基准自己当量为空时补成 1.0（限量试剂惯例）。
- 双向之二（改当量）：按基准的摩尔量 × 该行当量，直接算该行所需用量。
- 溶剂不参与化学计量（一般过量、不按当量算），只在它自己被编辑时动。
- 限量试剂：反应物/试剂里「摩尔量 ÷ 当量」最小者。
- 理论产量：限量试剂摩尔量 × 产物当量 × 产物分子量。
- 实际产率：产物行填了实测称量（克）→ 实测摩尔 ÷ 理论摩尔 × 100%。

「用量」列是计划投料量，可以被双向计算改写；实际称了多少填「实测」列，
两者分开，不会互相覆盖。
"""
from __future__ import annotations

import re

# 角色：参与化学计量的行
REACTIVE_ROLES = ("反应物", "试剂", "产物", "催化剂")

MASS_UNITS = {"g": 1.0, "克": 1.0, "mg": 0.001, "毫克": 0.001,
              "kg": 1000.0, "千克": 1000.0, "公斤": 1000.0}
MOL_UNITS = {"mmol": 1.0, "mol": 1000.0}


def _unit(text):
    return (text or "g").strip().lower() or "g"


def _asdict(c):
    """sqlite3.Row 和 dict 都接受。"""
    return dict(c) if not isinstance(c, dict) else c


_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _float(v):
    """把字段值转成 float。

    库里 REAL 列可能存着「5.0 g」「≥98%」这类文本：先整体转，转不了就取
    开头那段数字；实在没有数字才当缺失。
    """
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        pass
    m = _NUM_RE.search(str(v))
    return float(m.group()) if m else None


def to_g(amount, unit):
    """把数值折成克；不是质量单位返回 None。"""
    amount = _float(amount)
    if amount is None:
        return None
    f = MASS_UNITS.get(_unit(unit))
    return amount * f if f else None


def from_g(grams, unit):
    """把克数折回目标单位；不是质量单位返回 None。"""
    if grams is None:
        return None
    f = MASS_UNITS.get(_unit(unit))
    return grams / f if f else None


def row_mmol(c):
    """这一行的摩尔量（mmol）。算不出返回 None。

    需要三者有二：用量 + 单位 +（质量单位时的）分子量。
    """
    c = _asdict(c)
    amt = _float(c.get("amount"))
    if amt is None:
        return None
    u = _unit(c.get("unit"))
    if u in MOL_UNITS:
        return amt * MOL_UNITS[u]
    mw = _float(c.get("s_mw") or c.get("mw"))
    g = to_g(amt, u)
    if g is None or not mw:
        return None
    return g / mw * 1000.0


def eff_eq(c):
    """有效当量：没填按 1.0（溶剂除外——溶剂没有化学计量意义）。"""
    c = _asdict(c)
    eq = _float(c.get("equivalents"))
    if eq is not None:
        return eq
    return None if c.get("role") == "溶剂" else 1.0


def amount_for_mmol(mmol, unit, mw):
    """把目标摩尔量写成该行单位下的数值；写不出来返回 None。"""
    u = _unit(unit)
    mw = _float(mw)
    if u in MOL_UNITS:
        return mmol / MOL_UNITS[u]
    if not mw:
        return None
    g = mw / 1000.0 if mmol is None else mmol * mw / 1000.0
    return from_g(g, u)


def _fmt(x, nd=2):
    if x is None:
        return None
    x = round(float(x), nd)
    return int(x) if x == int(x) else x


def recalc(rows, edited_cid, mode):
    """双向重算。

    rows      : store.components(rid) 的行（list[dict-like]，能 .get）
    edited_cid: 刚被编辑的组成 id
    mode      : "amount"（改了用量）| "equiv"（改了当量）

    返回 (updates, note)：
      updates: [(cid, {字段: 值}), ...]  —— 需要写库的改动，不含没有变化的行
      note   : 一句话说明，出错时给原因（空串 = 正常）
    """
    rows = [dict(r) for r in rows]
    edited = next((r for r in rows if r["id"] == edited_cid), None)
    if edited is None:
        return [], "找不到被编辑的行"

    updates = []
    mmol_a = None

    if mode == "amount":
        mmol_a = row_mmol(edited)
        if mmol_a is None:
            return [], ("基准行算不出摩尔量：需要用量（g/mg/mmol）"
                        "和分子量（关联样品才有）。")
        if _float(edited.get("equivalents")) is None:
            updates.append((edited_cid, {"equivalents": 1.0}))
            edited["equivalents"] = 1.0
        a_eq = eff_eq(edited)
        for r in rows:
            if r["id"] == edited_cid or r.get("role") == "溶剂":
                continue
            mw = _float(r.get("s_mw"))
            eq = _float(r.get("equivalents"))
            if eq is not None:
                # 有当量 → 反推所需用量
                if mw is None:
                    continue
                need = mmol_a * eq / a_eq
                amt = amount_for_mmol(need, r.get("unit"), mw)
                if amt is not None:
                    updates.append((r["id"], {"amount": _fmt(amt)}))
            else:
                # 没当量但有用量 → 逆算当量
                mmol_r = row_mmol(r)
                if mmol_r is not None:
                    updates.append((r["id"],
                                    {"equivalents": _fmt(mmol_r / mmol_a, 2)}))
    elif mode == "equiv":
        # 基准 = 第一条能算出摩尔量的反应物/试剂（退而求其次任何行）
        base = None
        for want in ("反应物", "试剂"):
            base = next((r for r in rows
                         if r["id"] != edited_cid
                         and r.get("role") == want
                         and row_mmol(r) is not None), None)
            if base:
                break
        if base is None:
            base = next((r for r in rows
                         if r["id"] != edited_cid and row_mmol(r) is not None),
                        None)
        if base is None:
            return [], "先给一条反应物填上用量（要有关联样品的分子量），才能按当量算其它行。"
        mmol_a = row_mmol(base)
        a_eq = eff_eq(base)
        mw = _float(edited.get("s_mw"))
        if edited.get("role") == "溶剂":
            return [], "溶剂不按当量算，请直接填用量。"
        if not mw:
            return [], "这一行没有分子量（要关联样品），算不出所需用量。"
        eq_x = _float(edited.get("equivalents"))
        if eq_x is None:
            return [], "当量为空，没什么可算的。"
        need = mmol_a * eq_x / (a_eq if a_eq else 1.0)
        amt = amount_for_mmol(need, edited.get("unit"), mw)
        if amt is None:
            return [], "单位不是 g/mg/mmol，算不出用量。"
        updates.append((edited_cid, {"amount": _fmt(amt)}))
    else:
        return [], "未知模式"

    return updates, ""


def limiting_row(rows):
    """限量试剂：反应物/试剂里 摩尔量÷有效当量 最小者。"""
    rows = [_asdict(r) for r in rows]
    best, best_v = None, None
    for r in rows:
        if r.get("role") not in ("反应物", "试剂"):
            continue
        mmol = row_mmol(r)
        if mmol is None:
            continue
        eq = eff_eq(r)
        v = mmol / eq if eq else mmol
        if best_v is None or v < best_v:
            best, best_v = r, v
    return best


def yield_report(rows):
    """理论产量与实际产率。

    返回 dict：
      base      基准行（第一条能算摩尔量的反应物/试剂）
      base_mmol 基准摩尔量
      limiting  限量试剂行（可能为 None）
      items     [{row, theo_mmol, theo_g, actual_g, pct}] 只含算得动的产物
      pct       汇总产率（产物都有实测且都算得动时取第一个产物；否则 None）
    """
    rows = [dict(r) for r in rows]
    base = None
    for want in ("反应物", "试剂"):
        base = next((r for r in rows
                     if r.get("role") == want and row_mmol(r) is not None), None)
        if base:
            break
    if base is None:
        base = next((r for r in rows if row_mmol(r) is not None), None)
    lim = limiting_row(rows)
    lim_mmol = row_mmol(lim) if lim else None
    items = []
    for r in rows:
        if r.get("role") != "产物":
            continue
        mw = _float(r.get("s_mw"))
        eq = eff_eq(r)
        if not mw or not lim_mmol:
            continue
        theo_mmol = lim_mmol * (eq if eq else 1.0)
        theo_g = theo_mmol * mw / 1000.0
        actual_g = _float(r.get("actual"))
        pct = (actual_g / mw * 1000.0 / theo_mmol * 100.0
               if actual_g is not None and actual_g >= 0 else None)
        items.append({"row": r, "theo_mmol": theo_mmol, "theo_g": theo_g,
                      "actual_g": actual_g, "pct": pct})
    pct = None
    if items:
        pcts = [it["pct"] for it in items if it["pct"] is not None]
        if pcts:
            pct = pcts[0]
    return {"base": base, "base_mmol": row_mmol(base) if base else None,
            "limiting": lim, "items": items, "pct": pct}


def actual_to_g(text):
    """把实测输入折成克存储；解析不了返回 None。

    只认质量单位（g/mg/kg），写 mL 这类体积单位会让调用方提示。
    返回 (grams, unit_display, err)；grams None 且 err 空 = 空输入。
    """
    from gui import parse_amount  # 局部 import 避免循环
    amt, unit = parse_amount(text)
    if amt is None:
        return None, None, ("用量要带数字" if (text or "").strip() else "")
    u = _unit(unit)
    if u in MASS_UNITS:
        return amt * MASS_UNITS[u], _unit(unit), ""
    return None, unit, "实测称量只认质量单位（g / mg / kg），体积请先换算成质量。"


def summary_text(rows, rep=None):
    """组成表下面那行汇总。"""
    rep = rep or yield_report(rows)
    parts = []
    base, mmol = rep.get("base"), rep.get("base_mmol")
    if base is not None and mmol is not None:
        name = base.get("s_name") or base.get("label") or "基准"
        parts.append(f"基准 {name} {_fmt(mmol, 2)} mmol")
    lim = rep.get("limiting")
    if lim is not None:
        name = lim.get("s_name") or lim.get("label") or "限量"
        parts.append(f"限量 {name}")
    for it in rep.get("items", []):
        r = it["row"]
        name = r.get("s_name") or r.get("label") or "产物"
        seg = f"理论 {name} {it['theo_g']:.2f} g"
        if it["pct"] is not None:
            seg += f" · 实测 {it['actual_g']:g} g → {it['pct']:.0f}%"
        parts.append(seg)
    return "　·　".join(parts)
