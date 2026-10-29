"""安全护栏的单元测试：zip 炸弹 / 图片炸弹 / 页面尺寸 / 嵌套深度 / 总超时。

这些用例全部离线，不依赖 Ollama，也不读写用户的真实文件（只用 tmp_path）。
"""

from __future__ import annotations

import time
import zipfile
from pathlib import Path

import pytest

from linguaforge.core.paths import safe_filename, short_hash
from linguaforge.core.problems import Code, DocumentParseError, Severity
from linguaforge.core.safeguards import (
    LIMITS,
    Deadline,
    check_image_pixels,
    check_nesting_depth,
    check_page_size,
    check_zip_safety,
    guard_input,
    guard_page,
)


# ---------------- zip 炸弹 ----------------
def _make_zip(path: Path, n_files: int, payload: bytes) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i in range(n_files):
            zf.writestr(f"part_{i:06d}.txt", payload)
    return path


def test_zip_normal_file_passes(tmp_path):
    p = _make_zip(tmp_path / "ok.docx", 5, b"x" * 10_000)
    assert check_zip_safety(p) is None


def test_zip_bomb_by_ratio(tmp_path):
    """10 MB 全零数据可压到约 10 KB，压缩比远超 200:1。"""
    p = _make_zip(tmp_path / "bomb.docx", 1, b"\0" * (10 << 20))
    prob = check_zip_safety(p)
    assert prob is not None
    assert prob.code == Code.ZIP_BOMB
    assert prob.severity == Severity.FAILURE
    assert prob.params["ratio"] > LIMITS["zip_max_ratio"]


def test_zip_bomb_by_file_count(tmp_path):
    p = _make_zip(tmp_path / "many.docx", LIMITS["zip_max_files"] + 10, b"a")
    prob = check_zip_safety(p)
    assert prob is not None
    assert prob.code == Code.ZIP_BOMB
    assert prob.params["files"] > LIMITS["zip_max_files"]


def test_zip_not_a_zip_is_left_to_parser(tmp_path):
    """不是 zip 时不在此判定，交给 parser 报「文件损坏」，避免错误码抢跑。"""
    p = tmp_path / "broken.docx"
    p.write_bytes(b"not a zip at all")
    assert check_zip_safety(p) is None


def test_guard_zip_ignores_non_ooxml(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(b"%PDF-1.4")
    assert p.suffix == ".pdf"
    # guard_zip 只对 OOXML 生效
    from linguaforge.core.safeguards import guard_zip

    assert guard_zip(p) is None


# ---------------- 图片炸弹 ----------------
def test_image_pixels_within_limit():
    assert check_image_pixels(1920, 1080) is None
    # A0 @ 300 DPI ≈ 116 MP —— 真实扫描件的上限，必须放行
    assert check_image_pixels(11_600, 10_000) is None


def test_image_pixels_over_limit():
    prob = check_image_pixels(20_000, 20_000)  # 4 亿像素，炸弹
    assert prob is not None
    assert prob.code == Code.IMAGE_TOO_LARGE
    assert prob.severity == Severity.FAILURE


# ---------------- 页面尺寸 ----------------
def test_page_size_normal():
    assert check_page_size(595.0, 842.0) is None


def test_page_size_exceeded():
    prob = check_page_size(20_000.0, 842.0)
    assert prob is not None
    assert prob.code == Code.PAGE_SIZE_EXCEEDED
    # 降级级：跳过该页继续，而不是整份文档报废
    assert prob.severity == Severity.DEGRADED
    assert prob.is_fatal is False


def test_guard_page_raises_structured_error():
    with pytest.raises(DocumentParseError) as ei:
        guard_page(30_000.0, 30_000.0, page_no=7)
    prob = ei.value.problem
    assert prob.code == Code.PAGE_SIZE_EXCEEDED
    assert prob.page == 7
    assert prob.params["fmt"] == "pdf"


# ---------------- 嵌套深度 ----------------
def test_nesting_depth_ok():
    assert check_nesting_depth(1) is None
    assert check_nesting_depth(LIMITS["max_nesting_depth"]) is None


def test_nesting_depth_exceeded():
    prob = check_nesting_depth(LIMITS["max_nesting_depth"] + 1, what="书签")
    assert prob is not None
    assert prob.code == Code.STRUCT_TOO_DEEP
    assert prob.params["what"] == "书签"


# ---------------- 总超时 ----------------
def test_deadline_not_expired_initially():
    dl = Deadline(60.0)
    assert not dl.expired()
    assert dl.elapsed_s < 1.0


def test_deadline_expires():
    dl = Deadline(0.05)
    time.sleep(0.08)
    assert dl.expired()
    prob = dl.problem(last_page=3)
    assert prob.code == Code.PARSE_TIMEOUT
    assert prob.page == 3
    assert prob.severity == Severity.FAILURE


# ---------------- 输入前置检查 ----------------
def test_guard_input_missing_file():
    with pytest.raises(DocumentParseError) as ei:
        guard_input("/definitely/not/here.pdf", "pdf")
    assert ei.value.problem.code == Code.FILE_NOT_FOUND


def test_guard_input_empty_file(tmp_path):
    p = tmp_path / "empty.pdf"
    p.write_bytes(b"")
    with pytest.raises(DocumentParseError) as ei:
        guard_input(p, "pdf")
    assert ei.value.problem.code == Code.FILE_EMPTY


def test_guard_input_ok(tmp_path):
    p = tmp_path / "ok.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    guard_input(p, "pdf")  # 不抛即通过


# ---------------- 文件名净化 ----------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("../../etc/passwd", "etcpasswd"),
        ("CON", "CON_"),
        ("nul.txt", "nul.txt_"),
        ("a/b\\c.doc", "abc.doc"),
        ("  ", "output"),
        ("", "output"),
    ],
)
def test_safe_filename(raw, expected):
    assert safe_filename(raw) == expected


def test_safe_filename_truncates_keeping_suffix():
    name = "x" * 300 + ".pdf"
    out = safe_filename(name)
    assert out.endswith(".pdf")
    assert len(out) <= 120


def test_short_hash_stable():
    assert short_hash("abc") == short_hash("abc")
    assert short_hash("abc") != short_hash("abd")
    assert len(short_hash("abc")) == 8
