"""SQLite schema 定义与迁移。

设计要点：
  1. WAL 模式 —— 支持边写边读，UI 展示进度时不会阻塞流水线；
  2. block 一行一块 —— 大文档不能整份 DocIR 序列化成 JSON，否则 500 MB
     文档在内存里就爆了；
  3. block_id 必须**稳定**（同一文件重复解析得到相同 id），否则断点续翻
     时认不出哪些块已经翻过 —— 这是续翻能否成立的基石；
  4. 迁移按 schema_version 单向递增，禁止破坏性迁移。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS task (
    id            TEXT PRIMARY KEY,
    source_path   TEXT NOT NULL,
    source_sha256 TEXT,
    source_format TEXT,
    source_size   INTEGER DEFAULT 0,
    page_count    INTEGER DEFAULT 0,
    lang_src      TEXT,
    lang_dst      TEXT,
    model         TEXT,
    output_mode   TEXT,
    output_path   TEXT,
    status        TEXT,
    created_at    REAL,
    updated_at    REAL,
    finished_at   REAL,
    settings_json TEXT,
    error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_task_sha    ON task(source_sha256);
CREATE INDEX IF NOT EXISTS idx_task_status ON task(status);

CREATE TABLE IF NOT EXISTS page (
    task_id     TEXT NOT NULL,
    page_index  INTEGER NOT NULL,
    width       REAL DEFAULT 595.0,
    height      REAL DEFAULT 842.0,
    rotation    INTEGER DEFAULT 0,
    ocr_used    INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'pending',
    block_count INTEGER DEFAULT 0,
    ocr_ms      INTEGER DEFAULT 0,
    error       TEXT,
    PRIMARY KEY (task_id, page_index)
);

CREATE TABLE IF NOT EXISTS block (
    task_id      TEXT NOT NULL,
    block_id     TEXT NOT NULL,
    page_index   INTEGER NOT NULL,
    seq          INTEGER NOT NULL,
    type         TEXT,
    bbox_json    TEXT,
    text         TEXT,
    translated   TEXT,
    style_json   TEXT,
    runs_json    TEXT,
    translatable INTEGER DEFAULT 1,
    state        TEXT DEFAULT 'pending',
    origin       TEXT DEFAULT 'text_layer',
    confidence   REAL DEFAULT 0,
    meta_json    TEXT,
    PRIMARY KEY (task_id, block_id)
);
CREATE INDEX IF NOT EXISTS idx_block_page  ON block(task_id, page_index);
CREATE INDEX IF NOT EXISTS idx_block_state ON block(task_id, state);

CREATE TABLE IF NOT EXISTS translation_memory (
    lang_src    TEXT,
    lang_dst    TEXT,
    model       TEXT,
    src_hash    TEXT,
    src_text    TEXT,
    dst_text    TEXT,
    hit_count   INTEGER DEFAULT 0,
    created_at  REAL,
    PRIMARY KEY (lang_src, lang_dst, model, src_hash)
);

CREATE TABLE IF NOT EXISTS glossary (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    lang_src         TEXT,
    lang_dst         TEXT,
    term             TEXT,
    translation      TEXT,
    case_sensitive   INTEGER DEFAULT 0,
    do_not_translate INTEGER DEFAULT 0,
    note             TEXT
);
CREATE INDEX IF NOT EXISTS idx_glossary_term ON glossary(lang_src, lang_dst, term);

CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """v1 基线：executescript 已包含全部建表，这里只补默认值。"""
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', '1')")


_MIGRATIONS = {
    1: _migrate_v1,
}


def connect(db_path: str | Path, *, timeout: float = 30.0) -> sqlite3.Connection:
    """打开数据库并按需迁移到最新 schema。"""
    db_path = Path(db_path)
    if db_path.parent and not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), timeout=timeout, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")

    conn.executescript(_DDL)
    _run_migrations(conn)
    return conn


def _run_migrations(conn: sqlite3.Connection) -> None:
    cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
    row = cur.fetchone()
    current = int(row["value"]) if row else 0
    for ver in sorted(v for v in _MIGRATIONS if v > current):
        _MIGRATIONS[ver](conn)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(ver),),
        )
        current = ver


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return int(row["value"]) if row else 0


def vacuum(conn: sqlite3.Connection) -> None:
    """任务清理后回收空间。不要在流水线热路径上调用。"""
    conn.execute("VACUUM")


def resolve_db_path(custom: str | Path | None = None) -> Path:
    """数据库默认落在用户数据目录，打包后不可写安装目录。"""
    if custom:
        return Path(custom)
    from platformdirs import user_data_dir

    p = Path(user_data_dir("LinguaForge", "LinguaForge")) / "linguaforge.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
