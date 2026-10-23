"""术语表页：表格增删改、CSV 导入导出、TM 统计与并入。

所有 SQLite 访问都包在 :class:`~linguaforge.ui.worker.CallWorker` 里：
DAO 约定「每个线程各自 connect」，所以 Store 必须在工作线程内部创建。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..store import Store
from .i18n import tr
from .worker import CallWorker

#: 表格列
_COL_SRC, _COL_DST, _COL_NOTE = 0, 1, 2


class GlossaryPage(QWidget):
    """术语表管理页。"""

    def __init__(self, cfg, main_window=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.main_window = main_window
        self.lang = getattr(cfg, "ui_lang", "zh-CN") or "zh-CN"
        self._workers: list[CallWorker] = []
        self._build_ui()
        self.retranslateUi()

    @property
    def lang_code(self) -> str:
        """当前界面语言（跟随主窗口，保证切语言后同步）。"""
        if self.main_window is not None:
            return self.main_window.lang
        return self.lang

    @property
    def pair(self) -> tuple[str, str]:
        """当前语言对（源, 目标）。"""
        return self.cfg.lang_src or "auto", self.cfg.lang_dst or "zh-Hans"

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        self.lbl_pair = QLabel()
        root.addWidget(self.lbl_pair)

        bar = QHBoxLayout()
        self.btn_add = QPushButton()
        self.btn_delete = QPushButton()
        self.btn_save = QPushButton()
        self.btn_reload = QPushButton()
        self.btn_import = QPushButton()
        self.btn_export = QPushButton()
        for b in (self.btn_add, self.btn_delete, self.btn_save, self.btn_reload,
                  self.btn_import, self.btn_export):
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        self.table = QTableWidget(0, 3)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(_COL_SRC, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(_COL_DST, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(_COL_NOTE, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        tm = QGroupBox()
        tm_layout = QHBoxLayout(tm)
        self.lbl_tm = QLabel()
        self.btn_tm_import = QPushButton()
        tm_layout.addWidget(self.lbl_tm, 1)
        tm_layout.addWidget(self.btn_tm_import)
        root.addWidget(tm)
        self.box_tm = tm
        self._tm_layout = tm_layout

        self.btn_add.clicked.connect(self._on_add)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_save.clicked.connect(self._on_save)
        self.btn_reload.clicked.connect(self.reload)
        self.btn_import.clicked.connect(self._on_import)
        self.btn_export.clicked.connect(self._on_export)
        self.btn_tm_import.clicked.connect(self._on_tm_import)

    # ---------------------------------------------------------------- 生命周期
    def on_shown(self) -> None:
        """首次可见时载入数据与 TM 统计。"""
        if self.table.rowCount() == 0 and not self._workers:
            self.reload()

    # ---------------------------------------------------------------- 载入
    def reload(self) -> None:
        """异步从 SQLite 载入当前语言对的术语。"""
        src, dst = self.pair

        def _load() -> list[dict[str, Any]]:
            with Store() as store:
                return store.list_glossary(src, dst)

        self._run(_load, self._on_loaded)

    def _on_loaded(self, rows: object) -> None:
        data = list(rows or [])  # type: ignore[arg-type]
        self.table.setRowCount(0)
        for r in data:
            self._append_row(str(r.get("term", "")), str(r.get("translation", "")),
                             str(r.get("note", "")), int(r.get("id", 0) or 0))
        self._status(tr("glossary.loaded", self.lang_code, n=len(data)))
        self._refresh_tm_stats()

    # ---------------------------------------------------------------- 表格
    def _append_row(self, src: str = "", dst: str = "", note: str = "", gid: int = 0) -> None:
        idx = self.table.rowCount()
        self.table.insertRow(idx)
        for col, text in ((_COL_SRC, src), (_COL_DST, dst), (_COL_NOTE, note)):
            self.table.setItem(idx, col, QTableWidgetItem(text))
        self.table.item(idx, _COL_SRC).setData(Qt.ItemDataRole.UserRole, gid)

    def _row_values(self) -> list[tuple[str, str, str]]:
        out: list[tuple[str, str, str]] = []
        for i in range(self.table.rowCount()):
            src = self.table.item(i, _COL_SRC)
            dst = self.table.item(i, _COL_DST)
            note = self.table.item(i, _COL_NOTE)
            if src is None or dst is None:
                continue
            term = src.text().strip()
            trans = dst.text().strip()
            if not term and not trans:
                continue
            out.append((term, trans, note.text().strip() if note else ""))
        return out

    # ---------------------------------------------------------------- 动作
    def _on_add(self) -> None:
        self._append_row()
        self.table.selectRow(self.table.rowCount() - 1)

    def _on_delete(self) -> None:
        for model_idx in sorted((m.row() for m in self.table.selectionModel().selectedRows()),
                                reverse=True):
            self.table.removeRow(model_idx)

    def _on_save(self) -> None:
        lang = self.lang_code
        values = self._row_values()
        src, dst = self.pair
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("msg.info", lang))
        box.setText(tr("glossary.confirm_save", lang, src=src, dst=dst, n=len(values)))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        def _save() -> int:
            with Store() as store:
                store.clear_glossary(src, dst)
                n = 0
                for term, trans, note in values:
                    if not term or not trans:
                        continue
                    store.add_glossary(term, trans, src, dst, note=note)
                    n += 1
                return n

        self._run(_save, self._on_saved)

    def _on_saved(self, count: object) -> None:
        src, dst = self.pair
        self._status(tr("glossary.saved", self.lang_code, n=int(count or 0), src=src, dst=dst))
        self.reload()

    def _on_import(self) -> None:
        lang = self.lang_code
        path, _ = QFileDialog.getOpenFileName(
            self, tr("glossary.import", lang), "", tr("msg.csv_filter", lang)
        )
        if not path:
            return

        def _read() -> list[tuple[str, str, str]]:
            out: list[tuple[str, str, str]] = []
            with open(path, encoding="utf-8-sig", newline="") as fh:
                for row in csv.reader(fh):
                    if len(row) >= 2 and row[0].strip() and row[1].strip():
                        out.append((row[0].strip(), row[1].strip(),
                                    row[2].strip() if len(row) > 2 else ""))
            return out

        self._run(_read, self._on_imported)

    def _on_imported(self, rows: object) -> None:
        data = list(rows or [])  # type: ignore[arg-type]
        for term, trans, note in data:
            self._append_row(term, trans, note)
        self._status(tr("glossary.imported", self.lang_code, n=len(data)))

    def _on_export(self) -> None:
        lang = self.lang_code
        path, _ = QFileDialog.getSaveFileName(
            self, tr("glossary.export", lang), "glossary.csv", tr("msg.csv_filter", lang)
        )
        if not path:
            return
        values = self._row_values()
        target = str(Path(path))

        def _write() -> int:
            with open(target, "w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.writer(fh)
                for term, trans, note in values:
                    writer.writerow([term, trans, note])
            return len(values)

        self._run(_write, lambda n: self._status(
            tr("glossary.exported", self.lang_code, n=int(n or 0), path=target)))

    def _on_tm_import(self) -> None:
        """把 TM 里已有的对照并入术语表（按原文去重，需再点保存）。"""

        def _read() -> dict[str, str]:
            with Store() as store:
                return store.tm_export()

        self._run(_read, self._on_tm_loaded)

    def _on_tm_loaded(self, mapping: object) -> None:
        data = dict(mapping or {})  # type: ignore[arg-type]
        exist = {s for s, _d, _n in self._row_values()}
        added = 0
        for term, trans in data.items():
            t = str(term).strip()
            if not t or t in exist or not str(trans).strip():
                continue
            self._append_row(t, str(trans))
            exist.add(t)
            added += 1
        self._status(tr("glossary.tm_imported", self.lang_code, n=added))

    def _refresh_tm_stats(self) -> None:
        """异步读取 TM 统计并刷新标签。"""

        def _read() -> dict[str, int]:
            with Store() as store:
                return store.tm_stats()

        self._run(_read, self._on_tm_stats)

    def _on_tm_stats(self, stats: object) -> None:
        d = dict(stats or {})  # type: ignore[arg-type]
        self.lbl_tm.setText(tr("glossary.tm_stats", self.lang_code,
                               entries=int(d.get("entries", 0)), hits=int(d.get("hits", 0))))

    # ---------------------------------------------------------------- 工具
    def _run(self, fn, on_result) -> None:
        """在后台线程执行 fn，结果回到主线程。"""
        worker = CallWorker(fn, parent=self)
        worker.sig_result.connect(on_result)
        worker.sig_error.connect(self._on_error)
        worker.finished.connect(self._cleanup_worker)
        self._workers.append(worker)
        worker.start()

    def _cleanup_worker(self) -> None:
        """线程结束后回收，避免 worker 堆积。"""
        alive: list[CallWorker] = []
        for w in self._workers:
            if w.isRunning():
                alive.append(w)
            else:
                w.deleteLater()
        self._workers = alive

    def _on_error(self, message: str) -> None:
        QMessageBox.critical(self, tr("msg.error", self.lang_code), message)

    def _status(self, text: str) -> None:
        if self.main_window is not None:
            self.main_window.status(text)

    # ---------------------------------------------------------------- 语言
    def retranslateUi(self) -> None:  # noqa: N802 —— Qt 命名约定
        """切语言时重刷全部文案。"""
        lang = self.lang_code
        self.lang = lang
        src, dst = self.pair
        self.lbl_pair.setText(tr("glossary.pair", lang, src=src, dst=dst))
        self.btn_add.setText(tr("glossary.add", lang))
        self.btn_delete.setText(tr("glossary.delete", lang))
        self.btn_save.setText(tr("glossary.save", lang))
        self.btn_reload.setText(tr("glossary.reload", lang))
        self.btn_import.setText(tr("glossary.import", lang))
        self.btn_export.setText(tr("glossary.export", lang))
        self.btn_tm_import.setText(tr("glossary.tm_import", lang))
        self.box_tm.setTitle(tr("glossary.tm", lang))
        self.table.setHorizontalHeaderLabels([
            tr("glossary.col_src", lang),
            tr("glossary.col_dst", lang),
            tr("glossary.col_note", lang),
        ])
