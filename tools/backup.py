# -*- coding: utf-8 -*-
"""ELN 备份工具（项目内置）：数据快照 + Git bundle，全部落在 _backups/。

    python tools/backup.py                 # 数据快照 + git bundle（默认）
    python tools/backup.py --data-only     # 只备份数据
    python tools/backup.py --bundle-only   # 只备份代码/文档版本
    python tools/backup.py --keep 10       # 保留最近 10 份（默认 5）

产物：
    _backups/data/eln_<时间>.zip           eln.db + attachments + users + accounts.json
    _backups/bundle/ELN_<时间>.bundle      git 全量历史

数据快照用 SQLite 在线备份 API 取，**不需要关程序**，也不会拿到写了一半的库。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BACKUP = os.path.join(ROOT, "_backups")
DATA_DIR = os.path.join(BACKUP, "data")
BUNDLE_DIR = os.path.join(BACKUP, "bundle")

DATA_ITEMS = ["eln.db", "accounts.json", "cas_cache.json", "attachments", "users"]


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def snapshot_db(src: str, dst: str) -> bool:
    """在线备份单个 sqlite 文件（一致性快照）。"""
    s = d = None
    try:
        s = sqlite3.connect(src)
        d = sqlite3.connect(dst)
        s.backup(d)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [警告] {os.path.basename(src)} 快照失败：{exc}")
        try:
            shutil.copy2(src, dst)
            return True
        except Exception:  # noqa: BLE001
            return False
    finally:
        for conn in (d, s):          # 必须显式关闭，否则 Windows 上临时文件删不掉
            try:
                if conn is not None:
                    conn.close()
            except Exception:  # noqa: BLE001
                pass


def backup_data() -> str | None:
    os.makedirs(DATA_DIR, exist_ok=True)
    out = os.path.join(DATA_DIR, f"eln_{stamp()}.zip")
    with tempfile.TemporaryDirectory() as tmp:
        staged: list[str] = []
        db = os.path.join(ROOT, "eln.db")
        if os.path.exists(db):
            snap = os.path.join(tmp, "eln.db")
            if snapshot_db(db, snap):
                staged.append(snap)
        for name in DATA_ITEMS:
            if name == "eln.db":
                continue
            src = os.path.join(ROOT, name)
            if os.path.exists(src):
                staged.append(src)
        if not staged:
            print("  [跳过] 没有可备份的数据")
            return None
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in staged:
                if os.path.isdir(path):
                    for base, _dirs, files in os.walk(path):
                        for f in files:
                            full = os.path.join(base, f)
                            zf.write(full, os.path.relpath(full, ROOT))
                else:
                    zf.write(path, os.path.basename(path))
    return out


def git_commit() -> None:
    """把当前改动提交一次（bundle 只含已提交内容）。"""
    try:
        subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True, capture_output=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
        if diff.returncode != 0:
            subprocess.run(["git", "commit", "-q", "-m",
                            f"backup: 自动提交 {datetime.now():%Y-%m-%d %H:%M}"],
                           cwd=ROOT, check=True, capture_output=True)
            print("  [版本] 已提交当前改动")
    except Exception as exc:  # noqa: BLE001
        print("  [警告] 自动提交失败：", str(exc)[:120])


def backup_bundle() -> str | None:
    os.makedirs(BUNDLE_DIR, exist_ok=True)
    out = os.path.join(BUNDLE_DIR, f"ELN_{stamp()}.bundle")
    try:
        subprocess.run(["git", "bundle", "create", out, "--all"], cwd=ROOT,
                       check=True, capture_output=True, timeout=300)
        return out
    except Exception as exc:  # noqa: BLE001
        print("  [警告] git bundle 失败：", str(exc)[:200])
        return None


def prune(folder: str, pattern: str, keep: int) -> None:
    if not os.path.isdir(folder):
        return
    files = sorted(
        (os.path.join(folder, f) for f in os.listdir(folder) if f.startswith(pattern)),
        key=os.path.getmtime, reverse=True)
    for old in files[keep:]:
        try:
            os.remove(old)
            print("  [清理] 删除旧备份", os.path.basename(old))
        except OSError:
            pass


def human(path: str | None) -> str:
    if not path:
        return "-"
    size = os.path.getsize(path)
    return f"{size / 1048576:.2f} MB"


def main() -> int:
    ap = argparse.ArgumentParser(description="ELN 备份工具")
    ap.add_argument("--data-only", action="store_true")
    ap.add_argument("--bundle-only", action="store_true")
    ap.add_argument("--keep", type=int, default=5, help="保留最近几份（默认 5）")
    ap.add_argument("--commit", action="store_true", help="备份前先 git commit 当前改动")
    args = ap.parse_args()
    do_data = not args.bundle_only
    do_bundle = not args.data_only

    print(f"备份目录：{BACKUP}")
    made = []
    if do_data:
        print("[1/2] 数据快照（eln.db + 附件 + 账户）…")
        p = backup_data()
        if p:
            made.append(("数据", p))
            prune(DATA_DIR, "eln_", args.keep)
    if do_bundle:
        print("[2/2] Git 版本备份 …")
        if args.commit:
            git_commit()
        p = backup_bundle()
        if p:
            made.append(("版本", p))
            prune(BUNDLE_DIR, "ELN_", args.keep)

    if not made:
        print("没有产生任何备份")
        return 1
    print("\n完成：")
    for label, path in made:
        print(f"  {label}: {os.path.relpath(path, ROOT)}  ({human(path)})")
    print("\n恢复方法见 MANUAL.md「二十、备份与恢复」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
