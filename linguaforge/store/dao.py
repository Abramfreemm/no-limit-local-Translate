"""数据访问层（DAO）。

性能约定：
  - 批量写必须走 executemany + 单事务（目标 ≥ 5000 块/秒）；
  - 查询按 (task_id, page_index) 走索引，禁止全表扫；
  - 所有 JSON 字段延迟解析，读块时才 load，避免大文档开销。
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from .schema import connect, resolve_db_path

# ---------------------------------------------------------------- 稳定 ID


def stable_block_id(page_index: int, seq: int, text: str) -> str:
    """生成与解析次数无关的稳定块 ID。

    断点续翻的前提：第二次打开同一文件时，同一个 block 必须拿到同一个 ID，
    否则无法判断"这块已经翻过了"。Parser 生成的随机 uuid 不满足这个要求，
    所以落盘前统一用 (页码, 页内序号, 原文) 三元组重算。
    """
    raw = f"{page_index}|{seq}|{text}".encode("utf-8", errors="ignore")
    return "b-" + hashlib.sha1(raw).hexdigest()[:16]


def new_task_id() -> str:
    return "t-" + uuid.uuid4().hex[:16]


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


# ---------------------------------------------------------------- Store


class Store:
    """SQLite 存储门面。线程安全：每个线程各自 connect。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = resolve_db_path(db_path)
        self.conn = connect(self.db_path)

    # ---------------- 生命周期 ----------------
    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ================= 任务 =================
    def create_task(
        self,
        source_path: str,
        *,
        source_sha256: str = "",
        source_format: str = "",
        source_size: int = 0,
        page_count: int = 0,
        lang_src: str = "auto",
        lang_dst: str = "zh-Hans",
        model: str = "",
        output_mode: str = "markdown",
        output_path: str = "",
        settings: dict[str, Any] | None = None,
    ) -> str:
        tid = new_task_id()
        now = time.time()
        self.conn.execute(
            "INSERT INTO task(id, source_path, source_sha256, source_format, source_size,"
            " page_count, lang_src, lang_dst, model, output_mode, output_path, status,"
            " created_at, updated_at, settings_json)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,'running',?,?,?)",
            (
                tid,
                str(source_path),
                source_sha256,
                source_format,
                source_size,
                page_count,
                lang_src,
                lang_dst,
                model,
                output_mode,
                output_path,
                now,
                now,
                json.dumps(settings or {}, ensure_ascii=False),
            ),
        )
        return tid

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM task WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def find_task_by_source(self, source_sha256: str, lang_dst: str) -> dict[str, Any] | None:
        """按源文件指纹找历史任务 —— 续翻用。"""
        row = self.conn.execute(
            "SELECT * FROM task WHERE source_sha256=? AND lang_dst=?"
            " ORDER BY created_at DESC LIMIT 1",
            (source_sha256, lang_dst),
        ).fetchone()
        return dict(row) if row else None

    def update_task(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [task_id]
        self.conn.execute(f"UPDATE task SET {cols} WHERE id=?", vals)

    def set_status(self, task_id: str, status: str, error: str = "") -> None:
        if status in ("done", "failed", "canceled"):
            self.update_task(task_id, status=status, error=error, finished_at=time.time())
        else:
            self.update_task(task_id, status=status, error=error)

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM task ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def list_resumable(self) -> list[dict[str, Any]]:
        """中断/暂停/失败的任务 —— 重启后可续跑。"""
        rows = self.conn.execute(
            "SELECT * FROM task WHERE status IN ('running','paused','failed')"
            " ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_task(self, task_id: str) -> None:
        cur = self.conn.cursor()
        cur.execute("BEGIN")
        try:
            cur.execute("DELETE FROM block WHERE task_id=?", (task_id,))
            cur.execute("DELETE FROM page WHERE task_id=?", (task_id,))
            cur.execute("DELETE FROM task WHERE id=?", (task_id,))
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise

    # ================= 页 =================
    def upsert_page(self, task_id: str, page_index: int, **fields: Any) -> None:
        cols = ["task_id", "page_index"] + list(fields)
        qs = ", ".join("?" for _ in cols)
        upd = ", ".join(f"{k}=excluded.{k}" for k in fields)
        vals = [task_id, page_index] + list(fields.values())
        self.conn.execute(
            f"INSERT INTO page({','.join(cols)}) VALUES({qs}) "
            f"ON CONFLICT(task_id,page_index) DO UPDATE SET {upd}",
            vals,
        )

    def set_page_blocks_done(self, task_id: str, page_index: int, n: int) -> None:
        self.upsert_page(task_id, page_index, block_count=n)

    def get_done_pages(self, task_id: str) -> set:
        rows = self.conn.execute(
            "SELECT page_index FROM page WHERE task_id=? AND status='translated'",
            (task_id,),
        ).fetchall()
        return {int(r["page_index"]) for r in rows}

    # ================= 块 =================
    def upsert_blocks(self, task_id: str, blocks: Sequence[Any], page_index: int) -> int:
        """批量写入一页的块。返回写入条数。

        blocks 里的 Block.id 会被**替换**为稳定 ID（见 stable_block_id），
        保证重复解析同一文件时 ID 一致。
        """
        if not blocks:
            return 0
        rows = []
        for seq, b in enumerate(blocks):
            bid = stable_block_id(page_index, seq, b.text or "")
            b.id = bid  # 回写，让上层拿到稳定 ID
            b.page_index = page_index
            b.reading_order = seq
            rows.append(
                (
                    task_id,
                    bid,
                    page_index,
                    seq,
                    b.type.value if hasattr(b.type, "value") else str(b.type),
                    json.dumps(list(b.bbox), ensure_ascii=False),
                    b.text or "",
                    b.translated or "",
                    json.dumps(b.style.to_dict(), ensure_ascii=False),
                    json.dumps([r.to_dict() for r in b.runs], ensure_ascii=False),
                    1 if getattr(b, "is_translatable", True) else 0,
                    b.state.value if hasattr(b.state, "value") else str(b.state),
                    b.origin.value if hasattr(b.origin, "value") else str(b.origin),
                    float(b.confidence or 0.0),
                    json.dumps(b.meta or {}, ensure_ascii=False),
                )
            )
        cur = self.conn.cursor()
        cur.execute("BEGIN")
        try:
            cur.executemany(
                "INSERT INTO block(task_id, block_id, page_index, seq, type, bbox_json,"
                " text, translated, style_json, runs_json, translatable, state, origin,"
                " confidence, meta_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(task_id,block_id) DO UPDATE SET"
                " text=excluded.text, type=excluded.type, bbox_json=excluded.bbox_json,"
                " style_json=excluded.style_json, runs_json=excluded.runs_json,"
                " translatable=excluded.translatable, origin=excluded.origin,"
                " confidence=excluded.confidence, meta_json=excluded.meta_json",
                rows,
            )
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        return len(rows)

    def load_translated_map(self, task_id: str) -> dict[str, str]:
        """取出已完成译文：block_id -> translated。续翻时用于回填，避免重翻。"""
        rows = self.conn.execute(
            "SELECT block_id, translated FROM block"
            " WHERE task_id=? AND state='translated' AND translated<>''",
            (task_id,),
        ).fetchall()
        return {r["block_id"]: r["translated"] for r in rows}

    def update_translations(self, task_id: str, blocks: Sequence[Any]) -> int:
        """回写译文与状态。只更新有变化的块。"""
        rows = []
        for b in blocks:
            state = b.state.value if hasattr(b.state, "value") else str(b.state)
            rows.append((b.translated or "", state, task_id, b.id))
        if not rows:
            return 0
        cur = self.conn.cursor()
        cur.execute("BEGIN")
        try:
            cur.executemany(
                "UPDATE block SET translated=?, state=? WHERE task_id=? AND block_id=?",
                rows,
            )
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        return len(rows)

    def get_page_blocks(self, task_id: str, page_index: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM block WHERE task_id=? AND page_index=? ORDER BY seq",
            (task_id, page_index),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_blocks(self, task_id: str, state: str | None = None) -> int:
        if state:
            row = self.conn.execute(
                "SELECT COUNT(*) c FROM block WHERE task_id=? AND state=?",
                (task_id, state),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) c FROM block WHERE task_id=?", (task_id,)
            ).fetchone()
        return int(row["c"]) if row else 0

    def pending_pages(self, task_id: str, total_pages: int) -> list[int]:
        """返回尚未翻译完的页码。"""
        done = self.get_done_pages(task_id)
        return [i for i in range(total_pages) if i not in done]

    # ================= 翻译记忆 =================
    def tm_get(self, src: str, lang_src: str, lang_dst: str, model: str) -> str | None:
        h = text_sha256(src.strip())
        row = self.conn.execute(
            "SELECT dst_text FROM translation_memory"
            " WHERE lang_src=? AND lang_dst=? AND model=? AND src_hash=?",
            (lang_src, lang_dst, model, h),
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE translation_memory SET hit_count=hit_count+1"
                " WHERE lang_src=? AND lang_dst=? AND model=? AND src_hash=?",
                (lang_src, lang_dst, model, h),
            )
            return row["dst_text"]
        return None

    def tm_put_many(
        self, pairs: Iterable[tuple[str, str]], lang_src: str, lang_dst: str, model: str
    ) -> int:
        now = time.time()
        rows = []
        for s, d in pairs:
            s = (s or "").strip()
            if not s or not d:
                continue
            rows.append((lang_src, lang_dst, model, text_sha256(s), s, d, now))
        if not rows:
            return 0
        cur = self.conn.cursor()
        cur.execute("BEGIN")
        try:
            cur.executemany(
                "INSERT INTO translation_memory(lang_src, lang_dst, model, src_hash,"
                " src_text, dst_text, created_at) VALUES(?,?,?,?,?,?,?)"
                " ON CONFLICT(lang_src,lang_dst,model,src_hash) DO UPDATE SET"
                " dst_text=excluded.dst_text",
                rows,
            )
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        return len(rows)

    def tm_stats(self) -> dict[str, int]:
        row = self.conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(hit_count),0) h FROM translation_memory"
        ).fetchone()
        return {"entries": int(row["c"]), "hits": int(row["h"])}

    def tm_export(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT src_text, dst_text FROM translation_memory").fetchall()
        return {r["src_text"]: r["dst_text"] for r in rows}

    # ================= 术语表 =================
    def list_glossary(self, lang_src: str = "", lang_dst: str = "") -> list[dict[str, Any]]:
        if lang_src:
            rows = self.conn.execute(
                "SELECT * FROM glossary WHERE lang_src=? AND lang_dst=? ORDER BY id",
                (lang_src, lang_dst),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM glossary ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def add_glossary(
        self,
        term: str,
        translation: str,
        lang_src: str = "en",
        lang_dst: str = "zh-Hans",
        case_sensitive: int = 0,
        do_not_translate: int = 0,
        note: str = "",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO glossary(lang_src, lang_dst, term, translation, case_sensitive,"
            " do_not_translate, note) VALUES(?,?,?,?,?,?,?)",
            (lang_src, lang_dst, term, translation, case_sensitive, do_not_translate, note),
        )
        return int(cur.lastrowid or 0)

    def delete_glossary(self, gid: int) -> None:
        self.conn.execute("DELETE FROM glossary WHERE id=?", (gid,))

    def clear_glossary(self, lang_src: str = "", lang_dst: str = "") -> None:
        if lang_src:
            self.conn.execute(
                "DELETE FROM glossary WHERE lang_src=? AND lang_dst=?", (lang_src, lang_dst)
            )
        else:
            self.conn.execute("DELETE FROM glossary")

    # ================= 设置 =================
    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM setting WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO setting(key, value) VALUES(?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
