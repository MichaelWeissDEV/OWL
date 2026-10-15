"""Loading skills from a git URL or a local directory (for ``add`` and ``install``)."""

from __future__ import annotations

import contextlib
import tempfile
from collections.abc import Iterator
from pathlib import Path

from owl import gitutil
from owl.models import OwlError
from owl.parsing import LoadResult, load_skills


@contextlib.contextmanager
def load_source(
    source: str, *, default_author: str = "local", ref: str | None = None, subdir: str | None = None
) -> Iterator[list[LoadResult]]:
    """Yield all skills found in *source* (git URL or directory).

    Git sources are shallow-cloned into a temporary directory that is removed on exit;
    the yielded skills are fully loaded into memory so they stay usable afterwards.
    """
    if gitutil.is_git_url(source):
        with tempfile.TemporaryDirectory(prefix="owl-clone-") as tmp:
            checkout = Path(tmp) / "repo"
            gitutil.clone(source, checkout, ref=ref)
            yield _scan(checkout, subdir, default_author)
        return
    path = Path(source).expanduser()
    if not path.exists():
        raise OwlError(f"Not a directory or git URL: {source}")
    yield _scan(path, subdir, default_author)


def _scan(root: Path, subdir: str | None, default_author: str) -> list[LoadResult]:
    base = root
    if subdir:
        base = (root / subdir).resolve()
        if not base.is_relative_to(root.resolve()) or not base.is_dir():
            raise OwlError(f"Invalid sub-directory: {subdir}")
    if not base.is_dir():
        raise OwlError(f"Not a directory: {root}")
    return load_skills(base, default_author)
