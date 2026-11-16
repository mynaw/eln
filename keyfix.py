# -*- coding: utf-8 -*-
"""修 Windows 上 Tk 文本框「吞字符」的毛病（典型症状：`-` 打不进去）。

现象
----
在 ELN 的「文本」块里输入 ``7-48/7-49``，存下来却成了 ``748/749``；
而同一个键在标题（Entry）里完全正常。

原因
----
这台机器的键盘布局 / 输入法把减号键报成 keysym ``Insert``（``event.char``
仍然是 ``'-'``）。Tk 的 Text 类绑定 ``tk::TextInsert %W %A`` 只对“字符键”
生效，遇到 ``Insert`` 这种非字符 keysym 就不插；Entry 的插入在 C 层做、
不看 keysym，所以没这问题。

做法
----
给所有 ``tk.Text`` 补一条 **widget 级** ``<KeyPress>`` 兜底：当 keysym 是
非字符键、但 ``event.char`` 是单个可见字符时，自己插进去并 ``break``。
widget 级绑定先于类绑定执行，``break`` 之后 Tk 不会再插一次，所以不会重复。

只改“非字符 keysym + 可见字符”这一种组合：真正按 Insert / 方向键时
``event.char`` 是空串，不会误触发。
"""

from __future__ import annotations

import tkinter as tk

#: keysym 属于“按键本身”，正常不带字符；若这类 keysym 却带上了可见字符，
#: 说明是键盘布局 / 输入法把某个符号键报错了，需要手动补插。
_NON_CHAR_KEYSYMS = {
    "Insert", "Delete", "Home", "End", "Prior", "Next",
    "Up", "Down", "Left", "Right",
}

_installed = False


def _on_key(event):
    ch = event.char
    if len(ch) != 1 or ch == " " or not ch.isprintable():
        return None
    if event.keysym not in _NON_CHAR_KEYSYMS:
        return None
    try:
        w = event.widget
        if str(w.cget("state")) == "disabled":
            return None
        w.insert("insert", ch)
        w.see("insert")
    except Exception:            # noqa: BLE001  只读 / 已销毁的控件
        return None
    return "break"               # 别让类绑定再插一次


def install() -> None:
    """给 ``tk.Text`` 装上兜底插入。重复调用安全。"""
    global _installed
    if _installed:
        return
    _installed = True

    orig_init = tk.Text.__init__

    def _init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        self.bind("<KeyPress>", _on_key, add="+")

    tk.Text.__init__ = _init
