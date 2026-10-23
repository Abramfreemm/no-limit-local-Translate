"""持久化层：SQLite schema / DAO / 迁移。

对外只需 from linguaforge.store import Store, stable_block_id。
"""

from .dao import Store, new_task_id, stable_block_id, text_sha256
from .schema import SCHEMA_VERSION, connect, resolve_db_path, schema_version

__all__ = [
    "Store",
    "stable_block_id",
    "new_task_id",
    "text_sha256",
    "connect",
    "resolve_db_path",
    "schema_version",
    "SCHEMA_VERSION",
]
