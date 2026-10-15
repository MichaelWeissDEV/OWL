"""Filesystem helpers that treat skill content as untrusted input."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from owl.models import OwlError

SKIP_DIRS = {".git", "__pycache__", "node_modules"}
SKIP_FILES = {".DS_Store", ".owl-install.json"}


def safe_relpath(path: str) -> str:
    """Validate a relative POSIX path; reject absolute paths, ``..`` and odd characters."""
    if not path or "\0" in path or "\\" in path:
        raise OwlError(f"Unsafe file path: {path!r}")
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in ("..", "") for part in pure.parts):
        raise OwlError(f"Unsafe file path: {path!r}")
    if pure.parts and pure.parts[0] in SKIP_DIRS:
        raise OwlError(f"Unsafe file path: {path!r}")
    return pure.as_posix()


def read_tree(root: Path) -> dict[str, bytes]:
    """Read all regular files below *root* (symlinks are never followed)."""
    files: dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames if d not in SKIP_DIRS and not (Path(dirpath) / d).is_symlink()
        )
        for filename in sorted(filenames):
            file = Path(dirpath) / filename
            if filename in SKIP_FILES or file.is_symlink() or not file.is_file():
                continue
            rel = file.relative_to(root).as_posix()
            files[rel] = file.read_bytes()
    return files


def write_tree(dest: Path, files: dict[str, bytes]) -> None:
    """Write *files* below *dest*, validating every path first."""
    dest_resolved = dest.resolve()
    for rel, data in files.items():
        target = (dest / safe_relpath(rel)).resolve()
        if not target.is_relative_to(dest_resolved):
            raise OwlError(f"Unsafe file path: {rel!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def replace_dir(dest: Path, files: dict[str, bytes]) -> None:
    """Atomically(ish) replace *dest* with a directory containing *files*."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{dest.name}.", dir=dest.parent))
    try:
        write_tree(tmp, files)
        tmp.chmod(0o755)  # mkdtemp creates 0700
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
