# -*- coding: utf-8 -*-
"""程序路径：源码运行与 PyInstaller 便携版共用一套规则。

* ``app_dir()``  —— **可写数据根目录**。源码运行时是项目目录；
  打包成 exe 后是 exe 所在目录（不是 PyInstaller 解包的临时目录），
  所以 eln.db / accounts.json / users/ / attachments/ 都会落在便携文件夹里，
  拷走整个文件夹数据就跟着走，不会被当作临时文件清掉。
* ``res_path()`` —— 只读资源（assets、MANUAL.md 等）。优先 exe 同目录，
  其次 PyInstaller 的 _MEIPASS（用 --add-data 打进去时）。
"""
from __future__ import annotations

import os
import sys


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def res_path(*parts: str) -> str:
    d = os.path.join(app_dir(), *parts)
    if os.path.exists(d):
        return d
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return os.path.join(meipass, *parts)
    return d
