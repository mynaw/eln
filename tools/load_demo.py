#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把仓库自带的演示库复制成可用的 eln.db（只在 eln.db 不存在时执行）。

    python tools/load_demo.py            # 复制演示库
    python tools/load_demo.py --force    # 覆盖现有 eln.db（会先备份）

演示库 demo/eln_demo.db 由 tools/make_demo.py 生成，不含任何真实实验数据。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "demo", "eln_demo.db")
DST = os.path.join(ROOT, "eln.db")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="覆盖已有的 eln.db（先备份）")
    args = ap.parse_args()

    if not os.path.isfile(SRC):
        print("找不到演示库：", SRC, "\n可先用 python tools/make_demo.py 生成。")
        return 1
    if os.path.exists(DST) and not args.force:
        size = os.path.getsize(DST) / 1024
        print("已存在 eln.db（%.0f KB），未覆盖。" % size)
        print("确实要用演示库覆盖，请加 --force（会先备份原库）。")
        return 0
    if os.path.exists(DST):
        bak = DST + ".bak-" + time.strftime("%Y%m%d_%H%M%S")
        shutil.copy2(DST, bak)
        print("已备份原库到", os.path.basename(bak))

    shutil.copyfile(SRC, DST)
    print("已写入 eln.db（%.0f KB）。双击 Start.bat 就能看到演示数据。"
          % (os.path.getsize(DST) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
