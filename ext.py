# -*- coding: utf-8 -*-
"""
扩展点（extension hooks）。

以后要加功能，尽量挂在这里，不要改主流程。四个注册表：

1. 输入格式
       @ext.loader(".cdx2", ".mychem")
       def my_loader(path):
           return mol, notes, marks      # 三个值都要有

   注册后 structure.load() 遇到这个扩展名就会调用它。notes 是提醒文字列表，
   marks 是「图上圈出来的区域」（没有就给空列表）。

2. 片段选法（判哪一块）
       @ext.selection("ring_system", "整个环系")
       def pick_ring_system(mol, ctx):
           return [原子的下标...]        # 返回 None 表示交给默认的自动查找

   ctx 里有：path、marks（CDXML 里画的圈）、picked（用户点选的原子）。
   命令行用 --select <名字> 调用，界面里会出现在「选法」下拉框。

3. 判定后的处理
       @ext.hook
       def add_note(res):
           res["notes"].append("我自己加的一句")

   拿到的是 analyze_file 的返回字典，可以改 items、加 notes。

4. 命令行子命令
       @ext.command("mytool", "一句话说明")
       def mytool(args):
           print("..."); return 0

   然后 python cli.py --cmd mytool。

另外 ext.CONFIG 是一个空字典，放你自己的开关/参数；界面和命令行都会读它。
"""

from __future__ import annotations

from typing import Callable

# 扩展名 -> 读取函数(path) -> (mol, notes, marks)
LOADERS: dict[str, Callable] = {}

# 名字 -> {"label": 中文说明, "fn": 函数(mol, ctx) -> list[int] | None}
SELECTIONS: dict[str, dict] = {}

# 判定完成后的处理函数列表
HOOKS: list[Callable] = []

# 命令行子命令：名字 -> {"help": 说明, "fn": 函数(list[str]) -> int}
COMMANDS: dict[str, dict] = {}

# 自由使用的配置（界面和命令行共享）
CONFIG: dict = {}


# ---------------------------------------------------------------- 注册

def loader(*exts):
    """注册新的文件格式。可以一次注册多个扩展名。"""
    def deco(fn):
        for e in exts:
            LOADERS[e.lower()] = fn
        return fn
    return deco


def selection(name: str, label: str):
    """注册一种「判哪一块」的选法。"""
    def deco(fn):
        SELECTIONS[name] = {"label": label, "fn": fn}
        return fn
    return deco


def hook(fn):
    """注册判定后的处理。"""
    HOOKS.append(fn)
    return fn


def command(name: str, help_text: str = ""):
    """注册命令行子命令。"""
    def deco(fn):
        COMMANDS[name] = {"help": help_text, "fn": fn}
        return fn
    return deco


# ---------------------------------------------------------------- 调用

def run_loader(ext: str, path: str):
    """按扩展名找注册的读取函数，没有就返回 None。"""
    fn = LOADERS.get(ext.lower())
    if fn is None:
        return None
    out = fn(path)
    if not isinstance(out, tuple) or len(out) != 3:
        raise TypeError(f"loader {fn.__name__} 必须返回 (mol, notes, marks)")
    return out


def run_selection(name: str, mol, ctx: dict):
    """调一种选法，返回原子下标列表；未注册抛 KeyError。"""
    spec = SELECTIONS.get(name)
    if spec is None:
        raise KeyError(f"没有叫「{name}」的选法。已注册：" +
                       ("、".join(SELECTIONS) or "（无）"))
    return spec["fn"](mol, ctx)


def run_hooks(res: dict) -> dict:
    for fn in HOOKS:
        try:
            fn(res)
        except Exception as e:                       # 扩展出错不能拖垮主流程
            res.setdefault("notes", []).append(
                f"扩展 {getattr(fn, '__name__', fn)} 出错，已跳过：{e}")
    return res


def describe() -> str:
    """给 --plugins 用的一页说明。"""
    lines = ["已注册的扩展", "-" * 46]
    lines.append(f"输入格式（{len(LOADERS)}）")
    for ext, fn in sorted(LOADERS.items()):
        lines.append(f"  {ext:<10} {fn.__name__}")
    lines.append(f"片段选法（{len(SELECTIONS)}）")
    for name, spec in SELECTIONS.items():
        lines.append(f"  {name:<10} {spec['label']}")
    lines.append(f"判定后处理（{len(HOOKS)}）")
    for fn in HOOKS:
        lines.append(f"  {getattr(fn, '__name__', fn)}")
    lines.append(f"命令行子命令（{len(COMMANDS)}）")
    for name, spec in COMMANDS.items():
        lines.append(f"  {name:<10} {spec['help']}")
    return "\n".join(lines)
