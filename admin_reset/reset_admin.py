# -*- coding: utf-8 -*-
"""管理员账号重置工具（忘记管理员密码时使用，直接在本机双击 reset_admin.bat）。

作用：把 ELN 的管理员账户（当前本地账号 / 根账户）重置为
    账号：Eln
    密码：ZZU@2026
* 如果还没有任何账户，会直接创建这个管理员账户。
* 如果已有管理员账户，只改它的名字和密码，**数据目录不动**——
  所有实验记录、药剂、附件都还在。
* 密码只以不可逆哈希（PBKDF2-HMAC-SHA256 + 随机盐）写入 accounts.json，
  文件里查不出明文。
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth

ADMIN_NAME = "Eln"
ADMIN_PASSWORD = "ZZU@2026"


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    print("=" * 56)
    print("ELN 管理员账号重置工具")
    print(f"账户文件：{auth.AUTH_FILE}")
    print("=" * 56)

    data = auth._load()
    root = None
    for u in data["users"]:
        if not (u.get("data_dir") or ""):
            root = u
            break

    if root is None:
        print("· 还没有账户，直接创建管理员。")
        user = auth.create_user(ADMIN_NAME, ADMIN_PASSWORD, role="admin")
        # create_user 会写找回密文副本；按约定改成只存不可逆哈希
        d2 = auth._load()
        for row in d2["users"]:
            if row["id"] == user["id"]:
                row.pop("recover", None)
        auth._save(d2)
    else:
        print(f"· 找到管理员账户「{root.get('name')}」，重置名称与密码（数据不动）。")
        root["name"] = ADMIN_NAME
        salt = os.urandom(16)
        root["salt"] = salt.hex()
        root["hash"] = auth._hash(ADMIN_PASSWORD, salt)
        root["iter"] = auth.PBKDF2_ITER
        root["role"] = "admin"
        root.pop("recover", None)            # 只存不可逆哈希，不留可解密副本
        auth._save(data)

    # 清掉旧会话，下次打开必须用新账号登录
    try:
        auth.clear_session()
        print("· 已清除旧的自动登录会话。")
    except Exception:                        # noqa: BLE001
        pass

    print()
    print("重置完成！管理员账号与密码：")
    print(f"    账号：{ADMIN_NAME}")
    print(f"    密码：{ADMIN_PASSWORD}")
    print("（本文件所在文件夹的 README.txt 里有同样的明文记录）")
    input("按回车键关闭窗口…")
    return 0


if __name__ == "__main__":
    if os.environ.get("ELN_RESET_CONFIRM") != "1":
        print()
        print("⚠ 这会把管理员账号重置为 Eln / ZZU@2026，且清除自动登录。")
        ok = input("确认继续？(y/N)：").strip().lower()
        if ok != "y":
            print("已取消，什么都没改。")
            input("按回车键关闭窗口…")
            sys.exit(0)
    try:
        sys.exit(main())
    except auth.AuthError as e:
        print("失败：", e)
        input("按回车键关闭窗口…")
        sys.exit(1)
