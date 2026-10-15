"""Installing skills into a skills directory such as ``~/.claude/skills``."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from owl.fsutil import replace_dir
from owl.models import NAME_RE, OwlError, Skill
from owl.parsing import SKILL_FILE, write_skill_dir  # noqa: F401  (re-exported for callers)

MARKER = ".owl-install.json"


@dataclass(slots=True)
class Installed:
    name: str
    ref: str
    version: str
    sha256: str
    source: str
    path: Path


def install_skill(skill: Skill, target: Path, *, source: str = "", force: bool = False) -> Path:
    """Install *skill* below *target*/<name>.

    Refuses to overwrite a directory that OWL did not create, or one installed from a
    different author's skill of the same name, unless *force* is set.
    """
    if not NAME_RE.fullmatch(skill.name):
        raise OwlError(f"Refusing to install skill with unsafe name {skill.name!r}")
    dest = target / skill.name
    if dest.exists() and not force:
        marker = read_marker(dest)
        if marker is None:
            raise OwlError(f"{dest} already exists and was not installed by owl (use --force)")
        if marker.ref != skill.ref:
            raise OwlError(
                f"{dest} holds {marker.ref}, refusing to replace it with {skill.ref} (use --force)"
            )
    files = dict(skill.files)
    files[SKILL_FILE] = skill.content.encode("utf-8")
    files[MARKER] = (
        json.dumps(
            {
                "ref": skill.ref,
                "version": skill.version,
                "sha256": skill.sha256,
                "source": source,
            },
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    # Install the bundled files and SKILL.md; metadata lives in the marker.
    replace_dir(dest, files)
    return dest


def read_marker(path: Path) -> Installed | None:
    file = path / MARKER
    try:
        data = json.loads(file.read_text("utf-8"))
        return Installed(
            name=path.name,
            ref=data["ref"],
            version=data.get("version", ""),
            sha256=data.get("sha256", ""),
            source=data.get("source", ""),
            path=path,
        )
    except (OSError, ValueError, KeyError):
        return None


def list_installed(target: Path) -> list[Installed]:
    if not target.is_dir():
        return []
    items = [read_marker(p) for p in sorted(target.iterdir()) if p.is_dir()]
    return [i for i in items if i is not None]


def uninstall_skill(name: str, target: Path) -> Path:
    if not NAME_RE.fullmatch(name):
        raise OwlError(f"Invalid skill name {name!r}")
    dest = target / name
    if not dest.is_dir() or read_marker(dest) is None:
        raise OwlError(f"{name} was not installed by owl in {target}")
    shutil.rmtree(dest)
    return dest
