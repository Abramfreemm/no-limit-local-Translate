#!/usr/bin/env python3
"""Windows 一键打包：质量门禁 -> 资源准备 -> PyInstaller -> Inno Setup -> 哈希清单。

把之前手工执行的几步固化下来，避免"忘了重新生成许可清单"或"lint 红了照样打包"。

用法:
    python scripts/build_windows.py                 # 全量
    python scripts/build_windows.py --skip-gate     # 跳过 lint/测试（仅调试用）
    python scripts/build_windows.py --skip-inno     # 只出 dist，不做安装包
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "win" / "linguaforge.spec"
ISS = ROOT / "packaging" / "win" / "inno_setup.iss"
DIST = ROOT / "dist_v2"
BUILD = ROOT / "build_v2"
RELEASES = ROOT / "releases"

#: 安装包体积门禁（字节）。超过说明把不该带的东西打进去了。
MAX_INSTALLER_BYTES = 400 * 1024 * 1024

_CANDIDATE_ISCC = (
    Path.home() / "AppData/Local/Programs/Inno Setup 6/ISCC.exe",
    Path("/c/Program Files (x86)/Inno Setup 6/ISCC.exe"),
    Path("/c/Program Files/Inno Setup 6/ISCC.exe"),
)


def _run(cmd: list[str], cwd: Path | None = None, *, check: bool = True) -> int:
    print(f"\n$ {' '.join(cmd)}")
    started = time.time()
    proc = subprocess.run(cmd, cwd=str(cwd or ROOT), check=False)
    print(f"  -> exit={proc.returncode} ({time.time() - started:.1f}s)")
    if check and proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc.returncode


def _find_iscc() -> Path | None:
    for c in _CANDIDATE_ISCC:
        if c.exists():
            return c
    return shutil.which("ISCC") and Path(str(shutil.which("ISCC")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-gate", action="store_true", help="跳过 ruff / pytest")
    ap.add_argument("--skip-inno", action="store_true", help="跳过 Inno Setup 安装包")
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--dist", default=str(DIST), help="PyInstaller 输出目录")
    ap.add_argument("--work", default=str(BUILD), help="PyInstaller 工作目录")
    args = ap.parse_args()

    dist_dir = Path(args.dist)
    work_dir = Path(args.work)

    py = Path(sys.executable)
    print(f"=== LinguaForge Windows 打包 ===\npython: {py}")

    # ---------- 1) 质量门禁 ----------
    if not args.skip_gate:
        print("\n--- [1/4] 质量门禁 ---")
        _run([str(py), "-m", "ruff", "check", "."])
        _run([str(py), "-m", "ruff", "format", "--check", "."])
        _run([str(py), "-m", "pytest", "-q"])
    else:
        print("\n--- [1/4] 质量门禁（已跳过）---")

    # ---------- 2) 资源准备 ----------
    print("\n--- [2/4] 资源准备（字体 / 许可清单）---")
    _run([str(py), str(ROOT / "scripts" / "prepare_resources.py")], check=False)

    # ---------- 3) PyInstaller ----------
    print("\n--- [3/4] PyInstaller ---")
    _run(
        [
            str(py),
            "-m",
            "PyInstaller",
            str(SPEC),
            "--noconfirm",
            "--clean",
            f"--distpath={dist_dir}",
            f"--workpath={work_dir}",
        ]
    )

    exe = dist_dir / "LinguaForge" / "LinguaForge.exe"
    if not exe.exists():
        print(f"[error] 未找到主程序: {exe}")
        return 1

    # 许可清单必须随包分发（开源合规红线）
    lic = dist_dir / "LinguaForge" / "_internal" / "resources" / "THIRD_PARTY_LICENSES.txt"
    print(f"  许可清单: {'OK' if lic.exists() else '缺失'} ({lic})")

    installer: Path | None = None
    # ---------- 4) Inno Setup ----------
    if args.skip_inno:
        print("\n--- [4/4] Inno Setup（已跳过）---")
    else:
        print("\n--- [4/4] Inno Setup ---")
        iscc = _find_iscc()
        if iscc is None:
            print("[warn] 未找到 ISCC.exe，跳过安装包制作")
        else:
            RELEASES.mkdir(parents=True, exist_ok=True)
            _run([str(iscc), f"/O{RELEASES}", str(ISS)])
            installer = RELEASES / f"LinguaForge-{args.version}-Setup.exe"
            if installer.exists():
                size = installer.stat().st_size
                print(f"  安装包: {installer.name} {size / 1048576:.1f} MB")
                if size > MAX_INSTALLER_BYTES:
                    print(f"[error] 安装包超过门禁 {MAX_INSTALLER_BYTES / 1048576:.0f} MB")
                    return 1

    # ---------- 哈希清单 ----------
    targets = [p for p in (installer,) if p is not None and p.exists()]
    if targets:
        lines = []
        for t in targets:
            h = hashlib.sha256(t.read_bytes()).hexdigest()
            lines.append(f"{h}  {t.name}")
        # newline="" 强制 LF：Windows 默认会写 CRLF，而 sha256sum -c 会把
        # 行尾的 \r 当成文件名的一部分，导致校验必然失败。
        with open(RELEASES / "SHA256SUMS.txt", "w", encoding="utf-8", newline="") as fh:
            fh.write("\n".join(lines) + "\n")
        print("\n--- SHA256SUMS.txt ---")
        print("\n".join(lines))

    print("\n=== 打包完成 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
