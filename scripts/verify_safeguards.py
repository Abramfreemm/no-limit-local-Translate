"""安全护栏的端到端实跑验证（不联网、只用 tmp 目录构造恶意样本）。

对每一种攻击构造真实文件，走真实 parser 入口，断言：
  1) 进程没有崩溃 / 没有卡死；
  2) 抛出的是带**结构化错误码**的 DocumentParseError，而不是裸异常。

用法：
    python scripts/verify_safeguards.py
"""

from __future__ import annotations

import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linguaforge.core.problems import DocumentParseError  # noqa: E402
from linguaforge.parsers.docx_parser import DocxParser  # noqa: E402
from linguaforge.parsers.image_parser import ImageParser  # noqa: E402
from linguaforge.parsers.pdf_parser import PDFParser  # noqa: E402

_TMP = Path(__import__("tempfile").gettempdir()) / "lf_guard_probe"
_TMP.mkdir(parents=True, exist_ok=True)

_RESULTS: list[tuple[str, bool, str]] = []


def _record(name: str, ok: bool, note: str = "") -> None:
    _RESULTS.append((name, ok, note))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {note}")


def _expect_reject(name: str, fn, code: str) -> None:
    """期望：抛 DocumentParseError，且错误码等于 code。"""
    t0 = time.time()
    try:
        fn()
    except DocumentParseError as exc:
        got = exc.problem.code
        _record(
            name,
            got == code,
            f"code={got} expect={code} ({time.time() - t0:.2f}s)",
        )
        return
    except Exception as exc:  # noqa: BLE001 —— 裸异常也算失败
        _record(name, False, f"抛出非预期异常 {type(exc).__name__}: {exc}")
        return
    _record(name, False, "未抛异常，攻击样本被放行了")


def _zip_with(path: Path, n_files: int, payload: bytes) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i in range(n_files):
            zf.writestr(f"p{i:06d}.txt", payload)
    return path


def main() -> int:
    print("=== 安全护栏端到端验证 ===\n")

    # 1) zip 炸弹（压缩比）
    bomb = _TMP / "bomb_ratio.docx"
    _zip_with(bomb, 1, b"\0" * (12 << 20))
    _expect_reject(
        "zip 炸弹 · 压缩比超限",
        lambda: DocxParser().open(bomb),
        "LF-D07",
    )

    # 2) zip 炸弹（条目数）
    many = _TMP / "bomb_count.xlsx"
    _zip_with(many, 20_500, b"a")
    from linguaforge.parsers.xlsx_parser import XlsxParser

    _expect_reject("zip 炸弹 · 条目数超限", lambda: XlsxParser().open(many), "LF-D07")

    # 3) 图片炸弹：声明极大尺寸（不真正分配像素）
    try:
        from PIL import Image

        big = _TMP / "bomb.png"
        # 用 PIL 只写头部：Image.new 会真分配，改为手工改 IHDR
        base = Image.new("RGB", (8, 8), (255, 255, 255))
        base.save(_TMP / "seed.png")
        raw = bytearray((_TMP / "seed.png").read_bytes())
        # PNG IHDR 宽高位于第 16..24 字节（大端）
        w, h = 40_000, 40_000
        raw[16:20] = w.to_bytes(4, "big")
        raw[20:24] = h.to_bytes(4, "big")
        # 重算 IHDR CRC（含类型字段 4 字节 + 数据 13 字节）
        import zlib

        crc = zlib.crc32(bytes(raw[12:29])) & 0xFFFFFFFF
        raw[29:33] = crc.to_bytes(4, "big")
        big.write_bytes(bytes(raw))
        _expect_reject(
            "图片炸弹 · 像素超限",
            lambda: ImageParser().open(big),
            "LF-D08",
        )
    except ImportError:
        print("  [SKIP] 图片炸弹（缺少 Pillow）")

    # 4) 空文件
    empty = _TMP / "empty.pdf"
    empty.write_bytes(b"")
    _expect_reject("空文件", lambda: PDFParser().open(empty), "LF-D02")

    # 5) 文件不存在
    _expect_reject(
        "文件不存在",
        lambda: PDFParser().open(_TMP / "nope.pdf"),
        "LF-D01",
    )

    # 6) 正常文件必须放行（防止护栏误杀）
    print()
    ok_pdf = _TMP / "ok.pdf"
    ok_pdf.write_bytes(
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
    try:
        p = PDFParser()
        p.open(ok_pdf)
        pages = list(p.iter_pages())
        p.close()
        _record("正常 PDF 未被误杀", len(pages) == 1, f"pages={len(pages)}")
    except Exception as exc:  # noqa: BLE001
        _record("正常 PDF 未被误杀", False, f"{type(exc).__name__}: {exc}")

    # 汇总
    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    total = len(_RESULTS)
    print(f"\n=== 汇总：{passed}/{total} 通过 ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
