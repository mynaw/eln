# -*- coding: utf-8 -*-
"""修复「database disk image is malformed」：重建 FTS5 全文索引。

症状：打开/浏览正常，但一保存就弹 malformed；PRAGMA integrity_check 却是 ok。
原因：FTS5 索引与主表不同步（索引内部不一致 integrity_check 查不出来），
      写入时触发器执行 'delete' 找不到对应词条 → SQLITE_CORRUPT。

用法：
    python tools/repair_fts.py            # 自动备份后修复
    python tools/repair_fts.py --check    # 只体检，不改
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "eln.db")
TABLES = ("fts_samples", "fts_reactions", "fts_blocks")


def write_test(conn) -> tuple[bool, str]:
    """做一次『改一行再回滚』，模拟应用保存路径。"""
    try:
        conn.execute("BEGIN")
        conn.execute("UPDATE reactions SET note=note WHERE id=(SELECT MIN(id) FROM reactions)")
        conn.execute("UPDATE samples SET name=name WHERE id=(SELECT MIN(id) FROM samples)")
        conn.rollback()
        return True, "写入正常"
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser(description="重建 ELN 的 FTS5 索引")
    ap.add_argument("--check", action="store_true", help="只体检")
    ap.add_argument("--db", default=DB)
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print("找不到数据库:", args.db)
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    ok, msg = write_test(conn)
    print(f"[体检] 写入测试：{msg}")
    print(f"[体检] integrity_check：{conn.execute('PRAGMA integrity_check').fetchone()[0]}")
    for t in TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"        {t}: {n} 行")
    if args.check:
        conn.close()
        return 0 if ok else 2

    # 备份
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak_dir = os.path.join(ROOT, "_backups", f"eln_db_{stamp}")
    os.makedirs(bak_dir, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        src = args.db + suffix
        if os.path.exists(src):
            shutil.copy2(src, bak_dir)
    print(f"[备份] {bak_dir}")

    # 重建
    for t in TABLES:
        try:
            conn.execute(f"INSERT INTO {t}({t}) VALUES('rebuild')")
            conn.commit()
            print(f"[重建] {t}: OK")
        except Exception as exc:  # noqa: BLE001
            print(f"[重建] {t}: 失败 {exc}")
            conn.rollback()

    ok2, msg2 = write_test(conn)
    print(f"[复检] 写入测试：{msg2}")
    print(f"[复检] integrity_check：{conn.execute('PRAGMA integrity_check').fetchone()[0]}")
    conn.close()
    return 0 if ok2 else 2


if __name__ == "__main__":
    sys.exit(main())
