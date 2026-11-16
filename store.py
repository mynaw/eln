# -*- coding: utf-8 -*-
"""
数据库层。SQLite 单文件，跟着程序走，拷走就是完整备份。

七张表：
    collections          集合（相当于项目文件夹，可嵌套）
    samples              样品：结构、性质、库存
    reactions            反应：条件、操作、产率
    reaction_components  反应的组成：谁参加、什么角色、几当量
    attachments          附件：谱图、照片、任何文件，只存路径不存内容
    drawings             绘制区：可再编辑的结构式 / 反应式（JSON + SMILES）
    blocks               实验笔记：按顺序排的块（文本 / 步骤 / 化学 / 表格 / 计算）
    meta                 键值对，记一次性标记（比如演示笔记是否已灌过）

设计上刻意不做的：多用户、权限、审计追踪。单机个人用，这些是负担。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from datetime import datetime

from paths import app_dir

HERE = app_dir()
DB_PATH = os.path.join(HERE, "eln.db")            # 默认：第一个账户 / 命令行
ATTACH_DIR = os.path.join(HERE, "attachments")    # 兼容旧调用

# 集合选择器的哨兵：代表「collection_id IS NULL」的未归类条目。
# 数据库里永不允许样品/反应落 NULL（见 default_collection_id / _coerce_coll），
# 这个哨兵只用于「万一出现 NULL」时仍能从界面查到它们，以及自检审计。
ORPHAN = "__orphan__"

# 当前登录账户的数据子目录（"" = 根目录，其余形如 users/u_xxxx）。
# 每个账户一套 eln.db + attachments/，这就是「各用户数据隔离」的落点。
_DATA_DIR = ""


def set_data_dir(rel: str = ""):
    """在打开 Store 之前调用，切到某个账户的数据目录。"""
    global _DATA_DIR
    _DATA_DIR = rel or ""
    os.makedirs(attach_dir_path(), exist_ok=True)


def data_root() -> str:
    return os.path.join(app_dir(), _DATA_DIR) if _DATA_DIR else app_dir()


def db_path() -> str:
    return os.path.join(data_root(), "eln.db")


def attach_dir_path() -> str:
    return os.path.join(data_root(), "attachments")


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS collections (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    parent_id INTEGER REFERENCES collections(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS samples (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT,
    name          TEXT NOT NULL,
    cas           TEXT,
    smiles        TEXT,
    molfile       TEXT,
    formula       TEXT,
    mw            REAL,
    amount        REAL,
    unit          TEXT DEFAULT 'g',
    purity        TEXT,
    state         TEXT,
    location      TEXT,
    note          TEXT,
    collection_id INTEGER REFERENCES collections(id) ON DELETE SET NULL,
    created       TEXT,
    updated       TEXT,
    locked        INTEGER DEFAULT 0,
    locked_at     TEXT
);

CREATE TABLE IF NOT EXISTS reactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT,
    title         TEXT NOT NULL,
    procedure     TEXT,
    conditions    TEXT,
    yield_pct     REAL,
    note          TEXT,
    collection_id INTEGER REFERENCES collections(id) ON DELETE SET NULL,
    created       TEXT,
    updated       TEXT,
    locked        INTEGER DEFAULT 0,
    locked_at     TEXT
);

CREATE TABLE IF NOT EXISTS reaction_components (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reaction_id INTEGER NOT NULL REFERENCES reactions(id) ON DELETE CASCADE,
    sample_id   INTEGER REFERENCES samples(id) ON DELETE SET NULL,
    role        TEXT NOT NULL,
    equivalents REAL,
    amount      REAL,
    unit        TEXT,
    actual      REAL,               -- 实测称量（固定存克），驱动实际产率
    label       TEXT
);

CREATE TABLE IF NOT EXISTS attachments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_type TEXT NOT NULL,
    owner_id   INTEGER NOT NULL,
    kind       TEXT,
    title      TEXT,
    path       TEXT,
    note       TEXT
);

CREATE TABLE IF NOT EXISTS drawings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_type TEXT NOT NULL,
    owner_id   INTEGER NOT NULL,
    title      TEXT,
    kind       TEXT DEFAULT 'structure',   -- structure / scheme
    data       TEXT,                      -- JSON: 原子、键、标签、箭头，可再编辑
    smiles     TEXT,
    created    TEXT,
    updated    TEXT
);

CREATE TABLE IF NOT EXISTS blocks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_type TEXT NOT NULL,             -- sample / reaction
    owner_id   INTEGER NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'text',  -- text / step / chem / table / calc
    content    TEXT,                      -- JSON，按 kind 解释
    position   INTEGER DEFAULT 0,         -- 从 0 开始，越大越靠下
    created    TEXT,
    updated    TEXT
);

-- 记录版本快照（保险）：LWW 寄存器实现。
-- 主键 (owner_type, owner_id, kind) 保证同一种记录同一种类型永远只存 1 行——
-- INSERT OR REPLACE 直接覆盖旧快照，无需「累加后删旧」的剪枝，零堆积、无竞态。
-- kind='save' 由「保存」按钮写入，kind='finalize' 由「定稿」写入；二者各只留最新一份。
CREATE TABLE IF NOT EXISTS record_versions (
    owner_type TEXT    NOT NULL,
    owner_id   INTEGER NOT NULL,
    kind       TEXT    NOT NULL,          -- 'save' | 'finalize'
    created    TEXT,
    data       TEXT,                      -- JSON：字段 + 组成/绘制/笔记块
    PRIMARY KEY (owner_type, owner_id, kind)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_samples_coll ON samples(collection_id);
CREATE INDEX IF NOT EXISTS idx_reactions_coll ON reactions(collection_id);
CREATE INDEX IF NOT EXISTS idx_att_owner ON attachments(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_draw_owner ON drawings(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_blocks_owner ON blocks(owner_type, owner_id, position);
"""

ROLES = ["反应物", "试剂", "催化剂", "溶剂", "产物"]


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class Store:
    def __init__(self, path: str | None = None, attach_dir: str | None = None):
        # path 省略时按当前登录账户解析；显式传路径（命令行 / 自检）保持旧行为
        self.path = path or db_path()
        self.attach_dir = attach_dir or attach_dir_path()
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        os.makedirs(self.attach_dir, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._migrate()
        self._seed()

    def _migrate(self):
        """老库补新列（SQLite 没有 ADD COLUMN IF NOT EXISTS）。"""
        for table in ("samples", "reactions"):
            cols = {r["name"] for r in self.q(f"PRAGMA table_info({table})")}
            for col, ddl in (("locked", "INTEGER DEFAULT 0"),
                             ("locked_at", "TEXT")):
                if col not in cols:
                    self.conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        comp_cols = {r["name"] for r in self.q(
            "PRAGMA table_info(reaction_components)")}
        if "actual" not in comp_cols:
            self.conn.execute(
                "ALTER TABLE reaction_components ADD COLUMN actual REAL")
        self._migrate_fts()
        self._migrate_templates()
        self.conn.commit()

    # ------------------------------------------------------------ FTS5 全文索引
    def _migrate_fts(self):
        """建 FTS5 全文索引（外部内容表 + 触发器），旧库自动回填。

        SQLite 没编 FTS5 时静默跳过，搜索退回原来的 LIKE。
        """
        try:
            self.q("CREATE VIRTUAL TABLE IF NOT EXISTS fts_probe USING fts5(x)")
            self.q("DROP TABLE IF EXISTS fts_probe")
        except sqlite3.OperationalError:
            self.fts = False
            return
        self.fts = True
        # 触发器每次重建（开发期语义可能变过，IF NOT EXISTS 会留旧版）
        for t in ("trg_samples_ai", "trg_samples_au", "trg_samples_ad",
                  "trg_reactions_ai", "trg_reactions_au", "trg_reactions_ad",
                  "trg_blocks_ai", "trg_blocks_au", "trg_blocks_ad"):
            self.conn.execute(f"DROP TRIGGER IF EXISTS {t}")
        self.conn.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_samples USING fts5(
                name, code, cas, formula, note, smiles,
                content='samples', content_rowid='id');
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_reactions USING fts5(
                title, code, conditions, procedure, note,
                content='reactions', content_rowid='id');
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_blocks USING fts5(
                text, owner_type UNINDEXED, owner_id UNINDEXED);
            CREATE TRIGGER trg_samples_ai AFTER INSERT ON samples BEGIN
                INSERT INTO fts_samples(rowid, name, code, cas, formula, note, smiles)
                VALUES (new.id, new.name, new.code, new.cas, new.formula,
                        new.note, new.smiles); END;
            CREATE TRIGGER trg_samples_au AFTER UPDATE ON samples BEGIN
                INSERT INTO fts_samples(fts_samples, rowid, name, code, cas, formula, note, smiles)
                VALUES ('delete', old.id, old.name, old.code, old.cas, old.formula,
                        old.note, old.smiles);
                INSERT INTO fts_samples(rowid, name, code, cas, formula, note, smiles)
                VALUES (new.id, new.name, new.code, new.cas, new.formula,
                        new.note, new.smiles); END;
            CREATE TRIGGER trg_samples_ad AFTER DELETE ON samples BEGIN
                INSERT INTO fts_samples(fts_samples, rowid, name, code, cas, formula, note, smiles)
                VALUES ('delete', old.id, old.name, old.code, old.cas, old.formula,
                        old.note, old.smiles); END;
            CREATE TRIGGER trg_reactions_ai AFTER INSERT ON reactions BEGIN
                INSERT INTO fts_reactions(rowid, title, code, conditions, procedure, note)
                VALUES (new.id, new.title, new.code, new.conditions,
                        new.procedure, new.note); END;
            CREATE TRIGGER trg_reactions_au AFTER UPDATE ON reactions BEGIN
                INSERT INTO fts_reactions(fts_reactions, rowid, title, code, conditions, procedure, note)
                VALUES ('delete', old.id, old.title, old.code, old.conditions,
                        old.procedure, old.note);
                INSERT INTO fts_reactions(rowid, title, code, conditions, procedure, note)
                VALUES (new.id, new.title, new.code, new.conditions,
                        new.procedure, new.note); END;
            CREATE TRIGGER trg_reactions_ad AFTER DELETE ON reactions BEGIN
                INSERT INTO fts_reactions(fts_reactions, rowid, title, code, conditions, procedure, note)
                VALUES ('delete', old.id, old.title, old.code, old.conditions,
                        old.procedure, old.note); END;
            CREATE TRIGGER trg_blocks_ai AFTER INSERT ON blocks BEGIN
                INSERT INTO fts_blocks(rowid, text, owner_type, owner_id)
                VALUES (new.rowid, new.content, new.owner_type, new.owner_id); END;
            CREATE TRIGGER trg_blocks_au AFTER UPDATE ON blocks BEGIN
                DELETE FROM fts_blocks WHERE rowid = old.rowid;
                INSERT INTO fts_blocks(rowid, text, owner_type, owner_id)
                VALUES (new.rowid, new.content, new.owner_type, new.owner_id); END;
            CREATE TRIGGER trg_blocks_ad AFTER DELETE ON blocks BEGIN
                DELETE FROM fts_blocks WHERE rowid = old.rowid;
            END;
        """)
        # 旧库回填：索引空了就灌一遍（fts_blocks 用 blocks.id 做 rowid 对齐）
        n_f = self.one("SELECT COUNT(*) AS n FROM fts_samples")["n"]
        n_d = self.one("SELECT COUNT(*) AS n FROM samples")["n"]
        if n_d and not n_f:
            self.conn.execute(
                "INSERT INTO fts_samples(rowid, name, code, cas, formula, note, smiles) "
                "SELECT id, name, code, cas, formula, note, smiles FROM samples")
            self.conn.execute(
                "INSERT INTO fts_reactions(rowid, title, code, conditions, procedure, note) "
                "SELECT id, title, code, conditions, procedure, note FROM reactions")
            self.conn.execute("DELETE FROM fts_blocks")
            self.conn.execute(
                "INSERT INTO fts_blocks(rowid, text, owner_type, owner_id) "
                "SELECT id, content, owner_type, owner_id FROM blocks")

    @staticmethod
    def _fts_query(keyword: str) -> str:
        """把用户输入转成 FTS5 前缀查询：'benz 苯' -> '"benz"* "苯"*'。"""
        toks = [t for t in re.split(r"\s+", keyword.strip()) if t]
        return " ".join(f'"{t.replace(chr(34), "")}"*' for t in toks)

    def _match_ids(self, table: str, keyword: str) -> list[int]:
        """FTS5 查一组 rowid；查询语法不合法就退回普通词。"""
        try:
            q = self._fts_query(keyword)
            rows = self.q(f"SELECT rowid FROM {table} WHERE {table} MATCH ?",
                          (q,))
            ids = [r["rowid"] for r in rows]
            if ids:
                return ids
            # 前缀没命中再试整词
            return [r["rowid"] for r in
                    self.q(f"SELECT rowid FROM {table} WHERE {table} MATCH ?",
                           (f'"{keyword}"',))]
        except sqlite3.OperationalError:
            return []

    def _match_blocks(self, owner_type: str, keyword: str) -> list[int]:
        """笔记内容命中的 owner_id 列表。"""
        try:
            q = self._fts_query(keyword)
            rows = self.q("SELECT owner_id FROM fts_blocks "
                          "WHERE fts_blocks MATCH ? AND owner_type=?",
                          (q, owner_type))
            ids = [r["owner_id"] for r in rows]
            if ids:
                return ids
            rows = self.q("SELECT owner_id FROM fts_blocks "
                          "WHERE fts_blocks MATCH ? AND owner_type=?",
                          (f'"{keyword}"', owner_type))
            return [r["owner_id"] for r in rows]
        except sqlite3.OperationalError:
            return []

    # ------------------------------------------------------------ 反应模板
    def _migrate_templates(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS templates (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT NOT NULL,
                kind    TEXT DEFAULT 'reaction',
                content TEXT,
                created TEXT
            )""")

    def templates(self, kind="reaction"):
        return self.q("SELECT * FROM templates WHERE kind=? ORDER BY id DESC",
                      (kind,))

    def add_template(self, name: str, content: str, kind="reaction") -> int:
        return self.run("INSERT INTO templates(name, kind, content, created) "
                        "VALUES (?,?,?,?)", (name, kind, content, now()))

    def update_template(self, tid: int, **kw):
        if not kw:
            return
        sets = ", ".join(f"{k}=?" for k in kw)
        self.run(f"UPDATE templates SET {sets} WHERE id=?",
                 tuple(kw.values()) + (tid,))

    def delete_template(self, tid: int):
        self.run("DELETE FROM templates WHERE id=?", (tid,))

    # ------------------------------------------------------------ 基础
    def _seed(self):
        cur = self.conn.execute("SELECT COUNT(*) FROM collections")
        if cur.fetchone()[0] == 0:
            self.conn.execute("INSERT INTO collections(name) VALUES (?)", ("我的实验",))
            self.conn.commit()
        self._seed_notebook()

    def _seed_notebook(self):
        """演示库灌一份示例笔记，只灌一次。

        用 meta 打标记而不是「blocks 为空就灌」——否则用户把笔记删干净，
        下次启动又会被塞回来。
        """
        if self.get_meta("notebook_seeded"):
            return
        row = self.one("SELECT id FROM reactions ORDER BY id LIMIT 1")
        if row is None:
            return
        rid = row["id"]
        demo = [
            ("text", {"md": "## 目标\n把苯甲醛氧化成苯甲酸，验证 Pinnick 条件放大到 5 g 还稳不稳。\n\n"
                             "**注意**：NaClO₂ 要分批加，内温压在 25 ℃ 以下，否则容易放出 ClO₂。"}),
            ("step", {"title": "配亚氯酸钠溶液", "time": "10 min",
                      "body": "NaClO₂（1.2 eq）溶于 20 mL 水，冰浴预冷备用。",
                      "done": True}),
            ("step", {"title": "滴加氧化剂", "time": "30 min",
                      "body": "0–5 ℃ 下 30 min 内滴完，TLC 跟踪（EA:PE = 1:2）。",
                      "done": False}),
            ("chem", {"smiles": "O=C(O)c1ccccc1", "caption": "产物：苯甲酸"}),
            ("table", {"cols": ["时间点", "内温 / ℃", "转化率 / %"],
                       "rows": [["0 min", "3", "0"],
                                ["30 min", "7", "62"],
                                ["90 min", "22", "100"]]}),
            ("calc", {"expr": 'n = 5.0 / mw("O=Cc1ccccc1")', "note": "底物摩尔数"}),
            ("calc", {"expr": 'yld(4.6, 0.85 * n * mw("O=C(O)c1ccccc1"))',
                      "note": "按 85% 理论量算实测收率"}),
        ]
        for i, (kind, content) in enumerate(demo):
            self.add_block("reaction", rid, kind, json.dumps(content, ensure_ascii=False), i)
        self.set_meta("notebook_seeded", "1")

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def q(self, sql: str, args=()):
        return self.conn.execute(sql, args).fetchall()

    def one(self, sql: str, args=()):
        return self.conn.execute(sql, args).fetchone()

    def run(self, sql: str, args=()):
        cur = self.conn.execute(sql, args)
        self.conn.commit()
        return cur.lastrowid

    # ------------------------------------------------------------ 集合
    def collections(self):
        return self.q("SELECT * FROM collections ORDER BY parent_id, name")

    def default_collection_id(self) -> int:
        """保证存在一个集合并把它当成默认归宿。

        用作「漏归类 / 删集合」时的兜底，确保样品/反应永远不会游离到 NULL。
        """
        row = self.one("SELECT id FROM collections ORDER BY id LIMIT 1")
        if row:
            return row["id"]
        # 极端情况：库里一个集合都没有，先造一个
        return self.run("INSERT INTO collections(name) VALUES (?)", ("我的实验",))

    def orphan_counts(self) -> tuple[int, int]:
        """返回 (NULL 样品数, NULL 反应数)。"""
        ns = self.one("SELECT COUNT(*) AS n FROM samples WHERE collection_id IS NULL")["n"]
        nr = self.one("SELECT COUNT(*) AS n FROM reactions WHERE collection_id IS NULL")["n"]
        return ns, nr

    def reassign_orphans(self) -> tuple[int, int]:
        """保险网：把残留的 collection_id IS NULL 条目归到默认集合，返回修复数。

        正常情况下写入层已经杜绝 NULL，这里只兜底外部导入 / 手工改库 / 旧库迁移
        可能留下的孤儿，并让自检能校验「绝不丢记录」。
        """
        default = self.default_collection_id()
        c1 = self.conn.execute(
            "UPDATE samples SET collection_id=? WHERE collection_id IS NULL", (default,))
        n1 = c1.rowcount
        self.conn.commit()
        c2 = self.conn.execute(
            "UPDATE reactions SET collection_id=? WHERE collection_id IS NULL", (default,))
        n2 = c2.rowcount
        self.conn.commit()
        return n1, n2

    def add_collection(self, name: str, parent_id=None) -> int:
        return self.run("INSERT INTO collections(name, parent_id) VALUES (?,?)",
                        (name, parent_id))

    def rename_collection(self, cid: int, name: str):
        self.run("UPDATE collections SET name=? WHERE id=?", (name, cid))

    def delete_collection(self, cid: int):
        """删除集合，但绝不产生孤儿。

        原始外键是 `ON DELETE SET NULL` / `ON DELETE CASCADE`：直接删会把名下
        条目置空、把子集合一起删掉。这里在删之前先把条目改挂默认集合、把子集合
        上提，从根上消除「删集合 → 记录消失」这种假丢失。删的是默认集合本身时，
        先造一个替代默认再挪。
        """
        default = self.default_collection_id()
        if cid == default:
            alt = self.one("SELECT id FROM collections WHERE id<>? ORDER BY id LIMIT 1",
                           (cid,))
            if alt is None:
                alt = self.run("INSERT INTO collections(name) VALUES (?)", ("我的实验",))
            default = alt
        self.run("UPDATE samples SET collection_id=? WHERE collection_id=?",
                 (default, cid))
        self.run("UPDATE reactions SET collection_id=? WHERE collection_id=?",
                 (default, cid))
        self.run("UPDATE collections SET parent_id=? WHERE parent_id=?",
                 (default, cid))
        self.run("DELETE FROM collections WHERE id=?", (cid,))

    # ------------------------------------------------------------ 样品
    def samples(self, collection_id=None, keyword="", order="id DESC"):
        sql = "SELECT * FROM samples WHERE 1=1"
        args: list = []
        if collection_id == ORPHAN:
            sql += " AND collection_id IS NULL"
        elif collection_id:
            sql += " AND collection_id=?"
            args.append(collection_id)
        if keyword:
            hit_ids = []
            if getattr(self, "fts", False):
                hit_ids = self._match_ids("fts_samples", keyword)
                for i in self._match_blocks("sample", keyword):
                    if i not in hit_ids:
                        hit_ids.append(i)
            if hit_ids:
                sql += f" AND id IN ({','.join('?' * len(hit_ids))})"
                args += hit_ids
            else:
                k = f"%{keyword}%"
                sql += (" AND (name LIKE ? OR code LIKE ? OR cas LIKE ?"
                        " OR formula LIKE ? OR note LIKE ? OR smiles LIKE ?"
                        " OR id IN (SELECT owner_id FROM blocks"
                        "           WHERE owner_type='sample' AND content LIKE ?))")
                args += [k] * 7
        sql += f" ORDER BY {order}"
        return self.q(sql, args)

    def sample(self, sid: int):
        return self.one("SELECT * FROM samples WHERE id=?", (sid,))

    def add_sample(self, **kw) -> int:
        kw.setdefault("collection_id", self.default_collection_id())
        kw.setdefault("created", now())
        kw["updated"] = now()
        cols = ", ".join(kw)
        marks = ", ".join("?" * len(kw))
        return self.run(f"INSERT INTO samples({cols}) VALUES ({marks})", tuple(kw.values()))

    def update_sample(self, sid: int, **kw):
        if "collection_id" in kw and kw["collection_id"] in (None, ""):
            kw["collection_id"] = self.default_collection_id()
        kw["updated"] = now()
        sets = ", ".join(f"{k}=?" for k in kw)
        self.run(f"UPDATE samples SET {sets} WHERE id=?", tuple(kw.values()) + (sid,))

    def delete_sample(self, sid: int):
        self.run("DELETE FROM samples WHERE id=?", (sid,))
        self.run("DELETE FROM attachments WHERE owner_type='sample' AND owner_id=?", (sid,))
        self.run("DELETE FROM drawings WHERE owner_type='sample' AND owner_id=?", (sid,))
        self.run("DELETE FROM blocks WHERE owner_type='sample' AND owner_id=?", (sid,))

    def all_molfiles(self):
        """结构检索用：把带结构的样品全捞出来。"""
        return self.q("SELECT id, name, code, molfile FROM samples WHERE molfile IS NOT NULL")

    # ------------------------------------------------------------ 反应
    def reactions(self, collection_id=None, keyword="", order="id DESC"):
        sql = "SELECT * FROM reactions WHERE 1=1"
        args: list = []
        if collection_id == ORPHAN:
            sql += " AND collection_id IS NULL"
        elif collection_id:
            sql += " AND collection_id=?"
            args.append(collection_id)
        if keyword:
            hit_ids = []
            if getattr(self, "fts", False):
                hit_ids = self._match_ids("fts_reactions", keyword)
                for i in self._match_blocks("reaction", keyword):
                    if i not in hit_ids:
                        hit_ids.append(i)
            if hit_ids:
                sql += f" AND id IN ({','.join('?' * len(hit_ids))})"
                args += hit_ids
            else:
                k = f"%{keyword}%"
                sql += (" AND (title LIKE ? OR code LIKE ? OR procedure LIKE ?"
                        " OR conditions LIKE ?"
                        " OR id IN (SELECT owner_id FROM blocks"
                        "           WHERE owner_type='reaction' AND content LIKE ?))")
                args += [k] * 5
        sql += f" ORDER BY {order}"
        return self.q(sql, args)

    def reaction(self, rid: int):
        return self.one("SELECT * FROM reactions WHERE id=?", (rid,))

    def reaction_ids_by_samples(self, ids) -> set[int]:
        """结构检索命中一批样品后，找出「组成里用到它们」的反应。

        样品 id 和反应 id 是两套编号，不能直接拿命中集合去过滤反应列表。
        """
        ids = list(ids)
        if not ids:
            return set()
        marks = ", ".join("?" * len(ids))
        rows = self.q(f"""SELECT DISTINCT c.reaction_id FROM reaction_components c
                          WHERE c.sample_id IN ({marks})""", ids)
        return {r["reaction_id"] for r in rows}

    def add_reaction(self, **kw) -> int:
        kw.setdefault("collection_id", self.default_collection_id())
        kw.setdefault("created", now())
        kw["updated"] = now()
        cols = ", ".join(kw)
        marks = ", ".join("?" * len(kw))
        return self.run(f"INSERT INTO reactions({cols}) VALUES ({marks})", tuple(kw.values()))

    def update_reaction(self, rid: int, **kw):
        if "collection_id" in kw and kw["collection_id"] in (None, ""):
            kw["collection_id"] = self.default_collection_id()
        kw["updated"] = now()
        sets = ", ".join(f"{k}=?" for k in kw)
        self.run(f"UPDATE reactions SET {sets} WHERE id=?", tuple(kw.values()) + (rid,))

    def delete_reaction(self, rid: int):
        self.run("DELETE FROM reactions WHERE id=?", (rid,))
        self.run("DELETE FROM attachments WHERE owner_type='reaction' AND owner_id=?", (rid,))
        self.run("DELETE FROM drawings WHERE owner_type='reaction' AND owner_id=?", (rid,))
        self.run("DELETE FROM blocks WHERE owner_type='reaction' AND owner_id=?", (rid,))

    # ------------------------------------------------------------ 定稿锁定
    @staticmethod
    def _lock_table(owner_type: str) -> str:
        return "samples" if owner_type == "sample" else "reactions"

    def is_locked(self, owner_type: str, oid: int) -> bool:
        row = self.one(f"SELECT locked FROM {self._lock_table(owner_type)} WHERE id=?",
                       (oid,))
        return bool(row and row["locked"])

    def locked_at(self, owner_type: str, oid: int) -> str:
        row = self.one(f"SELECT locked_at FROM {self._lock_table(owner_type)} WHERE id=?",
                       (oid,))
        return (row["locked_at"] or "") if row else ""

    def set_locked(self, owner_type: str, oid: int, locked: bool):
        self.run(f"UPDATE {self._lock_table(owner_type)} "
                 f"SET locked=?, locked_at=? WHERE id=?",
                 (1 if locked else 0, now() if locked else None, oid))

    def components(self, rid: int):
        return self.q("""SELECT c.*, s.name AS s_name, s.formula AS s_formula,
                                s.mw AS s_mw, s.smiles AS s_smiles
                         FROM reaction_components c
                         LEFT JOIN samples s ON s.id = c.sample_id
                         WHERE c.reaction_id=? ORDER BY c.id""", (rid,))

    def add_component(self, rid: int, **kw) -> int:
        kw["reaction_id"] = rid
        cols = ", ".join(kw)
        marks = ", ".join("?" * len(kw))
        return self.run(f"INSERT INTO reaction_components({cols}) VALUES ({marks})",
                        tuple(kw.values()))

    def update_component(self, cid: int, **kw):
        """就地改一条组成（角色 / 当量 / 用量 / 单位 / 手写名）。"""
        if not kw:
            return
        sets = ", ".join(f"{k}=?" for k in kw)
        self.run(f"UPDATE reaction_components SET {sets} WHERE id=?",
                 tuple(kw.values()) + (cid,))

    def delete_component(self, cid: int):
        self.run("DELETE FROM reaction_components WHERE id=?", (cid,))

    # ------------------------------------------------------------ 附件
    def attachments(self, owner_type: str, owner_id: int):
        return self.q("""SELECT * FROM attachments
                         WHERE owner_type=? AND owner_id=? ORDER BY id""",
                      (owner_type, owner_id))

    def import_attachment(self, owner_type: str, owner_id: int, src_path: str,
                          kind="其他", title=None) -> int:
        """把文件复制到该账户的 attachments/ 下，数据库只记路径。"""
        os.makedirs(self.attach_dir, exist_ok=True)
        base = os.path.basename(src_path)
        stem, ext = os.path.splitext(base)
        dst = os.path.join(self.attach_dir, base)
        n = 1
        while os.path.exists(dst):
            dst = os.path.join(self.attach_dir, f"{stem}_{n}{ext}")
            n += 1
        try:
            shutil.copy2(src_path, dst)
        except Exception:
            dst = src_path          # 复制失败就退回原始路径
        return self.run("""INSERT INTO attachments(owner_type, owner_id, kind, title, path)
                           VALUES (?,?,?,?,?)""",
                        (owner_type, owner_id, kind, title or base, dst))

    def link_attachment(self, owner_type: str, owner_id: int, path: str,
                        kind="其他", title=None) -> int:
        return self.run("""INSERT INTO attachments(owner_type, owner_id, kind, title, path)
                           VALUES (?,?,?,?,?)""",
                        (owner_type, owner_id, kind, title or os.path.basename(path), path))

    def delete_attachment(self, aid: int):
        self.run("DELETE FROM attachments WHERE id=?", (aid,))

    # ------------------------------------------------------------ 绘制区
    def drawings(self, owner_type: str, owner_id: int):
        return self.q("""SELECT * FROM drawings WHERE owner_type=? AND owner_id=?
                         ORDER BY id DESC""", (owner_type, owner_id))

    def drawing(self, did: int):
        return self.one("SELECT * FROM drawings WHERE id=?", (did,))

    def add_drawing(self, owner_type: str, owner_id: int, title="",
                    kind="structure", data="", smiles="") -> int:
        return self.run("""INSERT INTO drawings
                           (owner_type, owner_id, title, kind, data, smiles, created, updated)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (owner_type, owner_id, title, kind, data, smiles, now(), now()))

    def update_drawing(self, did: int, **kw):
        kw["updated"] = now()
        sets = ", ".join(f"{k}=?" for k in kw)
        self.run(f"UPDATE drawings SET {sets} WHERE id=?", tuple(kw.values()) + (did,))

    def delete_drawing(self, did: int):
        self.run("DELETE FROM drawings WHERE id=?", (did,))

    # ------------------------------------------------------------ 实验笔记
    def blocks(self, owner_type: str, owner_id: int):
        return self.q("""SELECT * FROM blocks WHERE owner_type=? AND owner_id=?
                         ORDER BY position, id""", (owner_type, owner_id))

    def block(self, bid: int):
        return self.one("SELECT * FROM blocks WHERE id=?", (bid,))

    def block_counts(self, owner_type: str, owner_id: int) -> dict:
        rows = self.q("""SELECT kind, COUNT(*) AS n FROM blocks
                         WHERE owner_type=? AND owner_id=? GROUP BY kind""",
                      (owner_type, owner_id))
        return {r["kind"]: r["n"] for r in rows}

    def add_block(self, owner_type: str, owner_id: int, kind: str = "text",
                  content: str = "{}", position=None) -> int:
        if position is None:
            row = self.one("""SELECT MAX(position) AS p FROM blocks
                              WHERE owner_type=? AND owner_id=?""",
                           (owner_type, owner_id))
            position = 0 if row is None or row["p"] is None else int(row["p"]) + 1
        return self.run("""INSERT INTO blocks
                           (owner_type, owner_id, kind, content, position, created, updated)
                           VALUES (?,?,?,?,?,?,?)""",
                        (owner_type, owner_id, kind, content, position, now(), now()))

    def update_block(self, bid: int, content=None, kind=None):
        sets, args = ["updated=?"], [now()]
        if content is not None:
            sets.append("content=?")
            args.append(content)
        if kind is not None:
            sets.append("kind=?")
            args.append(kind)
        args.append(bid)
        self.run(f"UPDATE blocks SET {', '.join(sets)} WHERE id=?", tuple(args))

    def move_block(self, bid: int, delta: int) -> bool:
        """和上/下一块换位置。到头返回 False。"""
        b = self.block(bid)
        if b is None:
            return False
        rows = self.blocks(b["owner_type"], b["owner_id"])
        ids = [r["id"] for r in rows]
        i = ids.index(bid)
        j = i + delta
        if not (0 <= j < len(ids)):
            return False
        ids[i], ids[j] = ids[j], ids[i]
        for pos, bid2 in enumerate(ids):
            self.conn.execute("UPDATE blocks SET position=? WHERE id=?", (pos, bid2))
        self.conn.commit()
        return True

    def duplicate_block(self, bid: int) -> int | None:
        b = self.block(bid)
        if b is None:
            return None
        self._open_slot(b["owner_type"], b["owner_id"], int(b["position"]) + 1)
        return self.run("""INSERT INTO blocks
                           (owner_type, owner_id, kind, content, position, created, updated)
                           VALUES (?,?,?,?,?,?,?)""",
                        (b["owner_type"], b["owner_id"], b["kind"], b["content"],
                         int(b["position"]) + 1, now(), now()))

    def _open_slot(self, owner_type: str, owner_id: int, at: int):
        """把 at 及之后的块整体下移一格，给新块腾位置。"""
        self.conn.execute("""UPDATE blocks SET position = position + 1
                             WHERE owner_type=? AND owner_id=? AND position >= ?""",
                          (owner_type, owner_id, at))
        self.conn.commit()

    def delete_block(self, bid: int):
        self.run("DELETE FROM blocks WHERE id=?", (bid,))

    def clear_blocks(self, owner_type: str, owner_id: int):
        self.run("DELETE FROM blocks WHERE owner_type=? AND owner_id=?",
                 (owner_type, owner_id))

    # ------------------------------------------------------------ 杂项
    def get_meta(self, key: str, default=None):
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else default

    def set_meta(self, key: str, value):
        self.run("""INSERT INTO meta(key, value) VALUES (?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                 (key, str(value)))

    def stats(self) -> dict:
        g = lambda sql: self.one(sql)[0]
        return {
            "samples": g("SELECT COUNT(*) FROM samples"),
            "reactions": g("SELECT COUNT(*) FROM reactions"),
            "attachments": g("SELECT COUNT(*) FROM attachments"),
            "drawings": g("SELECT COUNT(*) FROM drawings"),
            "blocks": g("SELECT COUNT(*) FROM blocks"),
            "collections": g("SELECT COUNT(*) FROM collections"),
        }

    # ------------------------------------------------------------ 记录版本快照（保险）
    # 成熟方案：LWW 寄存器。主键 (owner_type, owner_id, kind) + INSERT OR REPLACE，
    # 保证每种记录每种类型只保留「最新一份」，天然防堆积、无竞态。
    def save_snapshot(self, owner_type: str, oid: int, kind: str):
        """把当前记录整份序列化成快照，按 LWW 覆盖同键旧快照（只留最新）。"""
        if owner_type == "sample":
            row = self.sample(oid)
            if not row:
                return None
            payload = {
                "fields": {k: row[k] for k in (
                    "code", "name", "cas", "smiles", "molfile", "formula",
                    "mw", "amount", "unit", "purity", "state", "location",
                    "note", "collection_id")},
                "drawings": [dict(d) for d in self.drawings("sample", oid)],
                "blocks": [dict(b) for b in self.blocks("sample", oid)],
            }
        else:
            row = self.reaction(oid)
            if not row:
                return None
            payload = {
                "fields": {k: row[k] for k in (
                    "code", "title", "procedure", "conditions", "yield_pct",
                    "note", "collection_id")},
                "components": [dict(c) for c in self.components(oid)],
                "drawings": [dict(d) for d in self.drawings("reaction", oid)],
                "blocks": [dict(b) for b in self.blocks("reaction", oid)],
            }
        self.run("""INSERT OR REPLACE INTO record_versions
                       (owner_type, owner_id, kind, created, data)
                    VALUES (?,?,?,?,?)""",
                 (owner_type, oid, kind, now(),
                  json.dumps(payload, ensure_ascii=False)))
        return payload

    def get_snapshot(self, owner_type: str, oid: int, kind: str | None = None):
        """取最新快照。kind 省略时取 created 最新的一份（save/finalize 二选一）。"""
        if kind:
            row = self.one(
                "SELECT * FROM record_versions "
                "WHERE owner_type=? AND owner_id=? AND kind=?",
                (owner_type, oid, kind))
        else:
            row = self.one(
                "SELECT * FROM record_versions "
                "WHERE owner_type=? AND owner_id=? ORDER BY created DESC LIMIT 1",
                (owner_type, oid))
        if not row:
            return None
        data = json.loads(row["data"])
        data["kind"] = row["kind"]
        data["created"] = row["created"]
        return data

    def restore_snapshot(self, owner_type: str, oid: int,
                         kind: str | None = None) -> bool:
        """把最新快照写回活记录（恢复字段 + 组成/绘制/笔记块）。

        不动 id / created / locked / locked_at：恢复不会解除定稿，也不改归属时间。
        附件文件不在此快照内（仅记路径），恢复时保留现有附件，不回滚文件。
        """
        snap = self.get_snapshot(owner_type, oid, kind)
        if not snap:
            return False
        fields = dict(snap["fields"])
        fields["updated"] = now()
        if owner_type == "sample":
            self.update_sample(oid, **fields)
            self.clear_blocks("sample", oid)
            for b in snap.get("blocks", []):
                self.add_block("sample", oid, kind=b.get("kind", "text"),
                               content=b.get("content", "{}"),
                               position=b.get("position", 0))
            self.conn.execute(
                "DELETE FROM drawings WHERE owner_type='sample' AND owner_id=?",
                (oid,))
            for d in snap.get("drawings", []):
                self.add_drawing("sample", oid, title=d.get("title", ""),
                                kind=d.get("kind", "structure"),
                                data=d.get("data", ""), smiles=d.get("smiles", ""))
        else:
            self.update_reaction(oid, **fields)
            for c in self.components(oid):
                self.delete_component(c["id"])
            for c in snap.get("components", []):
                self.add_component(oid, sample_id=c.get("sample_id"),
                                   role=c.get("role", "反应物"),
                                   equivalents=c.get("equivalents"),
                                   amount=c.get("amount"), unit=c.get("unit"),
                                   actual=c.get("actual"), label=c.get("label"))
            self.clear_blocks("reaction", oid)
            for b in snap.get("blocks", []):
                self.add_block("reaction", oid, kind=b.get("kind", "text"),
                               content=b.get("content", "{}"),
                               position=b.get("position", 0))
            self.conn.execute(
                "DELETE FROM drawings WHERE owner_type='reaction' AND owner_id=?",
                (oid,))
            for d in snap.get("drawings", []):
                self.add_drawing("reaction", oid, title=d.get("title", ""),
                                kind=d.get("kind", "structure"),
                                data=d.get("data", ""), smiles=d.get("smiles", ""))
        self.conn.commit()
        return True

    def backup_to(self, dst: str) -> str:
        """整库快照，用于备份。"""
        self.conn.commit()
        shutil.copy2(self.path, dst)
        return dst
