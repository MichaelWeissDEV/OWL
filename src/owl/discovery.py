"""Skill discovery: find candidate skills in directories, monorepos, git repositories, archives
and single files, and describe each one in a structured way.

Discovery only *reads*. Parsing, normalisation, validation and storage are separate steps (see
:mod:`owl.importer`). Nothing found here is ever executed; archives are extracted with strict path
and size checks.
"""

from __future__ import annotations

import contextlib
import re
import stat
import tempfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from owl import gitutil
from owl.fsutil import safe_relpath
from owl.models import MAX_TOTAL_BYTES, OwlError, Skill
from owl.parsing import LoadResult, find_skill_dirs, load_skill_dir, split_frontmatter

MAX_ZIP_FILES = 5000
MAX_ZIP_BYTES = 100 * 1024 * 1024
COMMAND_DIRS = {"commands", "command", "prompts"}

#: Problems that sensible defaults can repair. Everything else needs a human (or is rejected).
FIXABLE = (
    "Missing YAML frontmatter",
    "Missing frontmatter 'name'",
    "Missing frontmatter 'description'",
    "Invalid skill name",
    "Invalid author",
)


@dataclass
class Candidate:
    """What discovery learned about one potential skill."""

    origin: Path  #: the skill directory or markdown file on disk
    relative: str  #: position inside the source (POSIX)
    format: str  #: ``agent-skills`` (directory), ``skill-file`` or ``markdown`` (single file)
    name: str
    author: str
    description: str
    version: str
    tags: list[str]
    topics: list[str]
    text: str  #: the complete SKILL.md / markdown text
    files: dict[str, bytes]  #: additional bundled files
    sha256: str
    status: str  #: valid | incomplete | invalid | rejected
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source: str = ""  #: where it was found (path, URL, archive)
    commit: str | None = None  #: git commit of the source repository, if any
    skill: Skill | None = None  #: ready-to-store skill when ``status == "valid"``
    extra: dict[str, Any] = field(default_factory=dict)  #: overlay (skill.json) of the source

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": str(self.origin),
            "relative": self.relative,
            "format": self.format,
            "name": self.name,
            "author": self.author,
            "description": self.description,
            "version": self.version,
            "tags": self.tags,
            "topics": self.topics,
            "files": sorted(self.files),
            "sha256": self.sha256,
            "status": self.status,
            "problems": self.problems,
            "warnings": self.warnings,
            "source": self.source,
            "commit": self.commit,
        }


def slugify(text: str) -> str:
    """Turn arbitrary text into a valid skill name (lower-case, single hyphens, ≤ 64 chars)."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:64].strip("-")
    return slug or "skill"


def _classify(problems: list[str]) -> str:
    if not problems:
        return "valid"
    return "incomplete" if all(p.startswith(FIXABLE) for p in problems) else "invalid"


def _from_result(result: LoadResult, root: Path, source: str, commit: str | None) -> Candidate:
    skill = result.skill
    try:
        rel = result.path.resolve().relative_to(root.resolve()).as_posix() or "."
    except ValueError:
        rel = result.path.name
    status = _classify(result.problems)
    return Candidate(
        origin=result.path,
        relative=rel,
        format="agent-skills",
        name=skill.name,
        author=skill.author,
        description=skill.description,
        version=skill.version,
        tags=skill.tags,
        topics=skill.topics,
        text=skill.content,
        files=skill.files,
        sha256=skill.sha256,
        status=status,
        problems=list(result.problems),
        warnings=list(result.warnings),
        source=source,
        commit=commit,
        skill=skill if status == "valid" else None,
        extra=dict(skill.extra),
    )


def _from_markdown(
    path: Path, root: Path, source: str, default_author: str, commit: str | None
) -> Candidate:
    from owl.parsing import skill_from_markdown

    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    skill, problems = skill_from_markdown(
        text, default_author=default_author, fallback_name=slugify(path.stem)
    )
    if "�" in text:
        problems.append("Invalid UTF-8 byte sequence(s)")
    fm, _body, _ = split_frontmatter(text)
    fmt = "skill-file" if fm.get("name") and fm.get("description") else "markdown"
    status = _classify(problems)
    if len(raw) > MAX_TOTAL_BYTES:
        problems.append("File is larger than the size limit")
        status = "rejected"
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix() or path.name
    except ValueError:
        rel = path.name
    return Candidate(
        origin=path,
        relative=rel,
        format=fmt,
        name=skill.name,
        author=skill.author,
        description=skill.description,
        version=skill.version,
        tags=skill.tags,
        topics=skill.topics,
        text=text,
        files={},
        sha256=skill.sha256,
        status=status,
        problems=problems,
        source=source,
        commit=commit,
        skill=skill if status == "valid" else None,
    )


def discover(
    root: Path,
    *,
    source: str | None = None,
    default_author: str = "local",
    recursive: bool = True,
    commit: str | None = None,
) -> list[Candidate]:
    """Find candidates below *root* (a directory, a single skill directory or a markdown file)."""
    root = root.expanduser()
    label = source or str(root)
    if root.is_symlink():
        raise OwlError(f"{root} is a symbolic link; refusing to follow it")
    if root.is_file():
        if root.suffix.lower() not in (".md", ".markdown"):
            raise OwlError(f"{root} is not a markdown file, directory or zip archive")
        return [_from_markdown(root, root.parent, label, default_author, commit)]
    if not root.is_dir():
        raise OwlError(f"Not found: {root}")
    results: list[Candidate] = []
    dirs = find_skill_dirs(root)
    if not recursive:
        dirs = [d for d in dirs if d == root.resolve() or d.parent == root.resolve()]
    for directory in dirs:
        try:
            results.append(
                _from_result(load_skill_dir(directory, default_author), root, label, commit)
            )
        except (OSError, FileNotFoundError) as exc:
            results.append(_unreadable(directory, root, label, str(exc)))
    # prompt/command style markdown files in well-known directories
    if recursive:
        covered = [d for d in dirs]
        for md in sorted(root.rglob("*.md")):
            if md.parent.name in COMMAND_DIRS and md.is_file() and not md.is_symlink():
                resolved = md.resolve()
                if any(resolved.is_relative_to(c) for c in covered):
                    continue
                results.append(_from_markdown(md, root, label, default_author, commit))
    results.sort(key=lambda c: c.relative)
    return results


def _unreadable(path: Path, root: Path, source: str, reason: str) -> Candidate:
    return Candidate(
        origin=path,
        relative=path.name,
        format="agent-skills",
        name=path.name,
        author="",
        description="",
        version="",
        tags=[],
        topics=[],
        text="",
        files={},
        sha256="",
        status="rejected",
        problems=[reason],
        source=source,
    )


def extract_zip(archive: Path, dest: Path) -> None:
    """Extract *archive* into *dest* with strict checks (no traversal, links or zip bombs)."""
    with zipfile.ZipFile(archive) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_ZIP_FILES:
            raise OwlError(f"Archive has more than {MAX_ZIP_FILES} files")
        if sum(i.file_size for i in infos) > MAX_ZIP_BYTES:
            raise OwlError(f"Archive expands to more than {MAX_ZIP_BYTES // (1024 * 1024)} MiB")
        for info in infos:
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise OwlError(f"Archive member {info.filename!r} is a symbolic link")
            rel = safe_relpath(info.filename)
            target = (dest / rel).resolve()
            if not target.is_relative_to(dest.resolve()):
                raise OwlError(f"Unsafe archive member {info.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                written = 0
                while chunk := src.read(65536):
                    written += len(chunk)
                    if written > MAX_ZIP_BYTES:
                        raise OwlError("Archive member is too large")
                    out.write(chunk)


@contextlib.contextmanager
def discover_source(
    source: str,
    *,
    default_author: str = "local",
    ref: str | None = None,
    subdir: str | None = None,
    recursive: bool = True,
) -> Iterator[list[Candidate]]:
    """Discover candidates in a git URL, directory, zip archive or markdown file.

    Temporary clones/extractions are removed when the context exits; the yielded candidates hold
    all content in memory.
    """
    if gitutil.is_git_url(source):
        with tempfile.TemporaryDirectory(prefix="owl-clone-") as tmp:
            checkout = Path(tmp) / "repo"
            gitutil.clone(source, checkout, ref=ref)
            commit = gitutil.head_commit(checkout)
            base = _sub(checkout, subdir)
            yield discover(
                base,
                source=source,
                default_author=default_author,
                recursive=recursive,
                commit=commit,
            )
        return
    path = Path(source).expanduser()
    if not path.exists():
        raise OwlError(f"Not a directory, file or git URL: {source}")
    if path.is_file() and path.suffix.lower() == ".zip":
        with tempfile.TemporaryDirectory(prefix="owl-zip-") as tmp:
            extract_zip(path, Path(tmp))
            yield discover(
                _sub(Path(tmp), subdir),
                source=str(path),
                default_author=default_author,
                recursive=recursive,
            )
        return
    commit = gitutil.head_commit(path) if path.is_dir() and gitutil.is_repo(path) else None
    yield discover(
        _sub(path, subdir) if path.is_dir() else path,
        source=str(path),
        default_author=default_author,
        recursive=recursive,
        commit=commit,
    )


def _sub(root: Path, subdir: str | None) -> Path:
    if not subdir:
        return root
    base = (root / subdir).resolve()
    if not base.is_relative_to(root.resolve()) or not base.is_dir():
        raise OwlError(f"Invalid sub-directory: {subdir}")
    return base
