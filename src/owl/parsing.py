"""Reading skills from ``SKILL.md`` files and skill directories."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from owl.fsutil import SKIP_DIRS, read_tree, write_tree
from owl.models import KNOWN_META_KEYS, Skill, validate_skill

SKILL_FILE = "SKILL.md"
META_FILE = "skill.json"


def split_frontmatter(content: str) -> tuple[dict[str, Any], str, list[str]]:
    """Split a markdown document into ``(frontmatter, body, problems)``."""
    if not content.startswith("---"):
        return {}, content, ["Missing YAML frontmatter"]
    lines = content.splitlines(keepends=True)
    if lines[0].strip() != "---":
        return {}, content, ["Invalid YAML frontmatter delimiter"]
    closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if closing is None:
        return {}, content, ["Unclosed YAML frontmatter"]
    raw = "".join(lines[1:closing])
    body = "".join(lines[closing + 1 :])
    try:
        meta = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return {}, body, [f"Invalid YAML: {exc}"]
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        return {}, body, ["Frontmatter must be a YAML mapping"]
    return meta, body, []


def _lookup(meta: dict[str, Any], *keys: str) -> Any:
    """Find a value at the top level of the frontmatter or below its ``metadata`` key."""
    nested = meta.get("metadata")
    for key in keys:
        if key in meta:
            return meta[key]
        if isinstance(nested, dict) and key in nested:
            return nested[key]
    return None


def title_of(body: str) -> str | None:
    match = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
    return match.group(1).strip() if match else None


@dataclass(slots=True)
class LoadResult:
    """A skill read from disk together with everything that is wrong with it."""

    skill: Skill
    path: Path
    problems: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.problems


def skill_from_markdown(
    content: str,
    *,
    default_author: str = "local",
    fallback_name: str = "",
    files: dict[str, bytes] | None = None,
    overlay: dict[str, Any] | None = None,
) -> tuple[Skill, list[str]]:
    """Build a :class:`Skill` from SKILL.md text and an optional ``skill.json`` overlay."""
    fm, _body, problems = split_frontmatter(content)
    overlay = overlay or {}

    def pick(key: str, *aliases: str) -> Any:
        if key in overlay:
            return overlay[key]
        return _lookup(fm, key, *aliases)

    name = pick("name")
    if not isinstance(name, str) or not name.strip():
        problems.append("Missing frontmatter 'name'")
        name = fallback_name
    description = pick("description")
    version = pick("version")
    skill = Skill(
        author=str(pick("author") or default_author),
        name=str(name).strip(),
        version=str(version) if version is not None else "0.0.0",
        description=description.strip() if isinstance(description, str) else "",
        tags=pick("tags", "keywords") or [],
        topics=pick("topics", "topic", "categories") or [],
        content=content,
        extra={k: v for k, v in overlay.items() if k not in KNOWN_META_KEYS},
        files=files or {},
    )
    problems.extend(p for p in validate_skill(skill) if p not in problems)
    return skill, problems


def load_skill_dir(path: Path, default_author: str = "local") -> LoadResult:
    """Load the skill stored in directory *path* (SKILL.md, optional skill.json, extras)."""
    files = read_tree(path)
    raw = files.pop(SKILL_FILE, None)
    problems: list[str] = []
    if raw is None:
        raise FileNotFoundError(f"{path} has no {SKILL_FILE}")
    overlay: dict[str, Any] = {}
    meta_raw = files.pop(META_FILE, None)
    if meta_raw is not None:
        try:
            parsed = json.loads(meta_raw.decode("utf-8"))
            if isinstance(parsed, dict):
                overlay = parsed
            else:
                problems.append(f"{META_FILE} must contain a JSON object")
        except (ValueError, UnicodeDecodeError) as exc:
            problems.append(f"Invalid {META_FILE}: {exc}")
    content = raw.decode("utf-8", errors="replace")
    if "�" in content:
        problems.append("SKILL.md contains invalid UTF-8")
    skill, skill_problems = skill_from_markdown(
        content,
        default_author=default_author,
        fallback_name=path.name,
        files=files,
        overlay=overlay,
    )
    problems.extend(p for p in skill_problems if p not in problems)
    return LoadResult(skill, path, problems)


def find_skill_dirs(root: Path) -> list[Path]:
    """Find directories containing a SKILL.md below *root* (never following symlinks).

    A directory that contains a SKILL.md is a skill; its sub-directories belong to it.
    """
    root = root.resolve()
    if (root / SKILL_FILE).is_file() and not (root / SKILL_FILE).is_symlink():
        return [root]
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        if SKILL_FILE in filenames and not (here / SKILL_FILE).is_symlink():
            found.append(here)
            dirnames[:] = []
            continue
        dirnames[:] = sorted(
            d for d in dirnames if d not in SKIP_DIRS and not (here / d).is_symlink()
        )
    return sorted(found)


def load_skills(root: Path, default_author: str = "local") -> list[LoadResult]:
    """Load every skill found below *root*."""
    return [load_skill_dir(d, default_author) for d in find_skill_dirs(root)]


def write_skill_dir(skill: Skill, dest: Path, *, with_meta: bool = True) -> None:
    """Write *skill* into directory *dest* (SKILL.md, skill.json and bundled files)."""
    files = dict(skill.files)
    files[SKILL_FILE] = skill.content.encode("utf-8")
    if with_meta:
        meta = json.dumps(skill.meta(), indent=2, ensure_ascii=False) + "\n"
        files[META_FILE] = meta.encode("utf-8")
    dest.mkdir(parents=True, exist_ok=True)
    write_tree(dest, files)
