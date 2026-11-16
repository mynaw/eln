# -*- coding: utf-8 -*-
"""给 ELN 建快捷方式：项目文件夹里一个，桌面上一个。

    python make_shortcut.py               创建 / 更新两个快捷方式
    python make_shortcut.py --remove      删掉这两个快捷方式
    python make_shortcut.py --name ELN2   自定义名字

图标用 assets/app.ico；目标优先指向 conda 的 pythonw.exe（无控制台窗口），
找不到就退回 Start.bat。不会覆盖指向别处的同名快捷方式。
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

import win32com.client

HERE = os.path.dirname(os.path.abspath(__file__))
def _find_pythonw() -> str:
    """用当前解释器同目录的 pythonw.exe（无控制台窗口）；找不到就退回 PATH。"""
    exe = sys.executable or ""
    cand = exe.replace("python.exe", "pythonw.exe")
    return cand if os.path.isfile(cand) else "pythonw"


PYW = _find_pythonw()
ICO = os.path.join(HERE, "assets", "app.ico")
GUI = os.path.join(HERE, "gui.py")
START_BAT = os.path.join(HERE, "Start.bat")
DEFAULT_NAME = "ELN"
CSIDL_DESKTOPDIRECTORY = 0x0010


def desktop_dir() -> str:
    buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    if ctypes.windll.shell32.SHGetFolderPathW(
            None, CSIDL_DESKTOPDIRECTORY, None, 0, buf) == 0:
        return buf.value
    return os.path.join(os.path.expanduser("~"), "Desktop")


def targets(name: str) -> list[str]:
    return [os.path.join(HERE, name + ".lnk"),
            os.path.join(desktop_dir(), name + ".lnk")]


def create(name: str = DEFAULT_NAME) -> list[str]:
    shell = win32com.client.Dispatch("WScript.Shell")
    made = []
    for path in targets(name):
        if os.path.exists(path):
            try:
                old = shell.CreateShortcut(path).TargetPath
            except Exception:
                old = ""
            # 不是本程序的快捷方式就别动它，另起一个新名字
            if old and not (old == PYW or os.path.normcase(old)
                            == os.path.normcase(START_BAT)):
                path = os.path.join(os.path.dirname(path), name + "-ELN.lnk")
        lnk = shell.CreateShortcut(path)
        if os.path.exists(PYW):
            lnk.TargetPath = PYW
            lnk.Arguments = f'"{GUI}"'
        else:
            lnk.TargetPath = START_BAT
            lnk.Arguments = ""
        lnk.WorkingDirectory = HERE
        if os.path.exists(ICO):
            lnk.IconLocation = ICO + ",0"
        lnk.Description = "ELN · 电子实验记录（单机版）"
        lnk.WindowStyle = 1
        lnk.Save()
        made.append(path)
    return made


def remove(name: str = DEFAULT_NAME) -> list[str]:
    gone = []
    for path in targets(name):
        if os.path.exists(path):
            os.remove(path)
            gone.append(path)
    return gone


def verify(name: str = DEFAULT_NAME):
    shell = win32com.client.Dispatch("WScript.Shell")
    for path in targets(name):
        if not os.path.exists(path):
            print("  [缺失]", path)
            continue
        s = shell.CreateShortcut(path)
        print("  ", path)
        print("     目标:", s.TargetPath, s.Arguments)
        print("     图标:", s.IconLocation)


if __name__ == "__main__":
    argv = sys.argv[1:]
    name = DEFAULT_NAME
    if "--name" in argv:
        name = argv[argv.index("--name") + 1]
    if "--remove" in argv:
        for p in remove(name):
            print("已删除:", p)
    else:
        for p in create(name):
            print("已创建:", p)
        print("--- 校验 ---")
        verify(name)
