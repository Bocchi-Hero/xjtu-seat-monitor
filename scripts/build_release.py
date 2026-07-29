#!/usr/bin/env python3
"""Build Windows zip + Linux tar.gz release packages (no secrets)."""
from __future__ import annotations

import shutil
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"
DIST = ROOT / "dist"
STAGE = DIST / "stage"

INCLUDE_FILES = [
    "README.md",
    "LICENSE",
    "SECURITY.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "requirements.txt",
    "config.example.yaml",
    "monitor.py",
    "auth_session.py",
    "mailer.py",
    "panel_app.py",
    "panel_service.py",
    "Dockerfile",
    "docker-compose.yml",
    "start_panel.bat",
    "start_panel.sh",
]
INCLUDE_DIRS = [
    "panel_static",
    "scripts",
    "docs",
    "data",
]

SKIP_NAMES = {
    "build_release.py",
    "_bootstrap.py",
    "config.yaml",
    "session.json",
}


def clean() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    STAGE.mkdir(parents=True)


def copy_tree() -> Path:
    pkg = STAGE / f"xjtu-seat-monitor-{VERSION}"
    pkg.mkdir(parents=True)

    for name in INCLUDE_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, pkg / name)

    for d in INCLUDE_DIRS:
        src = ROOT / d
        if not src.exists():
            continue
        dst = pkg / d
        if d == "scripts":
            dst.mkdir(parents=True)
            for f in src.iterdir():
                if f.is_file() and f.name not in SKIP_NAMES and f.suffix == ".py":
                    if f.name.startswith("_"):
                        continue
                    shutil.copy2(f, dst / f.name)
        elif d == "data":
            dst.mkdir(parents=True)
            keep = src / ".gitkeep"
            if keep.exists():
                shutil.copy2(keep, dst / ".gitkeep")
            else:
                (dst / ".gitkeep").write_text("", encoding="utf-8")
        else:
            shutil.copytree(
                src,
                dst,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
            )

    # release-oriented quickstart
    (pkg / "RELEASE_NOTES.txt").write_text(
        f"""XJTU Seat Monitor v{VERSION}
============================

Windows:
  1. Install Python 3.10+
  2. python -m venv .venv
  3. .venv\\Scripts\\activate
  4. pip install -r requirements.txt
  5. copy config.example.yaml config.yaml  (edit it)
  6. Double-click start_panel.bat
  7. Open http://127.0.0.1:18730/

Linux:
  1. python3 -m venv .venv && source .venv/bin/activate
  2. pip install -r requirements.txt
  3. cp config.example.yaml config.yaml  (edit it)
  4. chmod +x start_panel.sh && ./start_panel.sh
  5. Open http://127.0.0.1:18730/

Never share config.yaml or session.json.
""",
        encoding="utf-8",
    )
    return pkg


def zip_windows(pkg: Path) -> Path:
    out = DIST / f"xjtu-seat-monitor-{VERSION}-windows-x64.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in pkg.rglob("*"):
            if f.is_file():
                zf.write(f, f"xjtu-seat-monitor-{VERSION}-windows-x64/{f.relative_to(pkg).as_posix()}")
    return out


def tar_linux(pkg: Path) -> Path:
    out = DIST / f"xjtu-seat-monitor-{VERSION}-linux-x64.tar.gz"
    with tarfile.open(out, "w:gz") as tf:
        tf.add(pkg, arcname=f"xjtu-seat-monitor-{VERSION}-linux-x64")
    return out


def main() -> None:
    clean()
    pkg = copy_tree()
    z = zip_windows(pkg)
    t = tar_linux(pkg)
    print("Built:")
    print(" ", z, z.stat().st_size)
    print(" ", t, t.stat().st_size)


if __name__ == "__main__":
    main()
