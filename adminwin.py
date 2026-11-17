# -*- coding: utf-8 -*-
"""管理员账号管理窗口（桌面版：设置 ▾ → 管理员账号…）。

权限模型（2026-11-17 与用户确认）：
* 管理员 = 「当前本地账号」，即建号时沿用根目录数据的那个账户；
  它的名字**不可修改**、账户**不可删除**、不参与硬盘配额。
* 子账号由管理员创建：**只存不可逆哈希**（PBKDF2-HMAC-SHA256 + 随机盐），
  不写可解密的找回副本——密码丢了只能由管理员重置，无法找回。
* 可给每个子账号分配「可用硬盘空间」（MB，0 = 不限制），写入账户文件，
  网页端写入时按数据目录实际占用执行限制。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import auth

UI = "Microsoft YaHei UI"


class AdminDialog(tk.Toplevel):
    """子账号管理对话框。调用方需先确认当前用户是管理员（auth.is_root）。"""

    def __init__(self, master, user: dict):
        super().__init__(master)
        self.user = user
        self.title("管理员账号")
        self.configure(bg="#f4f6fa")
        self.transient(master)
        self.grab_set()

        root = auth.admin_user() or {}
        top = tk.Frame(self, bg="#f4f6fa")
        top.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(top, text=f"管理员：{root.get('name', '')}",
                 font=(UI, 11, "bold"), bg="#f4f6fa").pack(side="left")
        tk.Button(top, text="管理员", font=(UI, 9),
                  command=self._reset_admin_pwd).pack(side="right")

        mid = tk.Frame(self, bg="#f4f6fa")
        mid.pack(fill="both", expand=True, padx=14)
        self.tv = ttk.Treeview(mid, columns=("name", "created", "used", "quota"),
                               show="headings", height=8)
        for col, text, w in (("name", "子账号", 140), ("created", "创建时间", 130),
                             ("used", "已用 (MB)", 90), ("quota", "配额 (MB，0=不限)", 120)):
            self.tv.heading(col, text=text)
            self.tv.column(col, width=w, anchor="w")
        self.tv.pack(fill="both", expand=True)
        self.tv.bind("<Double-1>", lambda _e: self._reset_sub())

        btns = tk.Frame(self, bg="#f4f6fa")
        btns.pack(fill="x", padx=14, pady=10)
        for text, cmd in (("子账号", self._new_sub),
                          ("重置", self._reset_sub),
                          ("删除", self._del_sub),
                          ("空间", self._set_quota),
                          ("刷新", self.refresh),
                          ("关闭", self.destroy)):
            tk.Button(btns, text=text, font=(UI, 9), command=cmd,
                      padx=8).pack(side="left", padx=3)
        tk.Label(self, text="子账号密码只以不可逆哈希（PBKDF2）存放，丢失后只能重置，不能找回。",
                 font=(UI, 8), fg="#9ca3af", bg="#f4f6fa").pack(anchor="w", padx=14,
                                                                pady=(0, 10))
        self.refresh()

    # ------------------------------------------------------------ 数据
    def refresh(self):
        for iid in self.tv.get_children():
            self.tv.delete(iid)
        for u in auth._load()["users"]:
            if auth.is_root(u):
                continue
            st = auth.quota_state(u["name"])
            self.tv.insert("", "end", iid=u["id"],
                           values=(u["name"], u.get("created", ""),
                                   f"{st['used']:.1f}", st["quota"]))

    def _sel_name(self) -> str | None:
        iid = self.tv.focus()
        if not iid:
            messagebox.showinfo("先选中一个", "先在列表里选中一个子账号。", parent=self)
            return None
        vals = self.tv.item(iid, "values")
        return str(vals[0])

    # ------------------------------------------------------------ 操作
    def _new_sub(self):
        name = simpledialog.askstring("新建子账号", "子账号名：", parent=self)
        if not name:
            return
        pwd = simpledialog.askstring("新建子账号", f"「{name}」的密码（至少 6 位）：",
                                     show="●", parent=self)
        if not pwd:
            return
        quota = simpledialog.askinteger(
            "新建子账号", "可用硬盘空间（MB，留空或 0 = 不限制）：",
            parent=self, minvalue=0, initialvalue=0)
        try:
            auth.create_sub(name, pwd, quota_mb=quota or 0)
        except auth.AuthError as e:
            messagebox.showerror("建号失败", str(e), parent=self)
            return
        self.refresh()
        messagebox.showinfo("完成", f"子账号「{name.strip()}」已创建。\n"
                                    "密码只存了不可逆哈希，请让本人记好；"
                                    "丢了由管理员在这里重置。", parent=self)

    def _reset_sub(self):
        name = self._sel_name()
        if not name:
            return
        new_name = simpledialog.askstring(
            "重置名称与密码", f"新的账号名（保持「{name}」不变就直接确定）：",
            initialvalue=name, parent=self)
        if new_name is None:
            return
        pwd = simpledialog.askstring("重置名称与密码", "新密码（至少 6 位）：",
                                     show="●", parent=self)
        if not pwd:
            return
        try:
            if new_name.strip() and new_name.strip() != name:
                auth.rename_user(name, new_name.strip())
                name = new_name.strip()
            auth.set_password(name, pwd)
        except auth.AuthError as e:
            messagebox.showerror("重置失败", str(e), parent=self)
            return
        self.refresh()
        messagebox.showinfo("完成", f"「{name}」已重置为新名称 / 新密码。", parent=self)

    def _del_sub(self):
        name = self._sel_name()
        if not name:
            return
        if not messagebox.askyesno(
                "删除子账号",
                f"删除「{name}」？\n\n"
                "只删账号本身，它在 users/ 下的数据目录会保留（需要可手动清理）。",
                parent=self):
            return
        try:
            auth.delete_user(name)
        except auth.AuthError as e:
            messagebox.showerror("删除失败", str(e), parent=self)
            return
        self.refresh()

    def _set_quota(self):
        name = self._sel_name()
        if not name:
            return
        st = auth.quota_state(name)
        quota = simpledialog.askinteger(
            "分配硬盘空间",
            f"「{name}」可用硬盘空间（MB）\n当前已用 {st['used']:.1f} MB，"
            f"配额 {st['quota']} MB\n（0 = 不限制）",
            parent=self, minvalue=0, initialvalue=st["quota"] or 0)
        if quota is None:
            return
        try:
            auth.set_quota(name, quota)
        except auth.AuthError as e:
            messagebox.showerror("设置失败", str(e), parent=self)
            return
        self.refresh()

    def _reset_admin_pwd(self):
        pwd = simpledialog.askstring("改管理员密码",
                                     f"管理员「{self.user.get('name', '')}」的新密码（至少 6 位）：",
                                     show="●", parent=self)
        if not pwd:
            return
        try:
            auth.set_password(self.user.get("name", ""), pwd)
        except auth.AuthError as e:
            messagebox.showerror("修改失败", str(e), parent=self)
            return
        messagebox.showinfo("完成", "管理员密码已更新。", parent=self)
