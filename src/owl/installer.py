"""Installing skills into a skills directory such as ``~/.claude/skills``.

Every installation records which files it wrote (path -> SHA-256) in ``.owl-install.json``, so
later updates can tell whether the user modified the installed copy.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from owl import paths
from owl.fsutil import hash_tree, read_tree, replace_dir
from owl.models import NAME_RE, OwlError, Skill
from owl.parsing import SKILL_FILE

MARKER = ".owl-install.json"
MARKER_FORMAT = 2


@dataclass(slots=True)
class Installed:
    name: str
    ref: str
    version: str
    sha256: str
    source: str
    path: Path
    #: path -> sha256 of the files OWL wrote; ``None`` for installs made by older versions
    files: dict[str, str] | None = field(default=None, repr=False)

    def to_dict(self) -> dict:
        """JSON-friendly representation (slotted dataclasses have no ``__dict__``)."""
        data = asdict(self)
        data["path"] = str(self.path)
        data.pop("files")
        data["modified"] = self.modified_files() or []
        return data

    def modified_files(self) -> list[str] | None:
        """Files changed, added or removed since installation; ``None`` if it cannot be known."""
        if self.files is None:
            return None
        return dirty_files(self.path, self.files)


def dirty_files(path: Path, recorded: dict[str, str]) -> list[str]:
    """Compare the installed directory with the recorded file hashes."""
    current = hash_tree(read_tree(path)) if path.is_dir() else {}
    changed = {p for p in recorded if current.get(p) != recorded[p]}
    added = {p for p in current if p not in recorded}
    return sorted(changed | added)


def backup_root() -> Path:
    return paths.home() / "backups" / "installs"


def install_skill(skill: Skill, target: Path, *, source: str = "", force: bool = False) -> Path:
    """Install *skill* below *target*/<name>.

    Refuses to overwrite a directory that OWL did not create, one holding another skill, or one
    with local modifications, unless *force* is set. With *force* the previous directory is kept
    in ``$OWL_HOME/backups/installs``. An unchanged, unmodified installation is left alone.
    """
    if not NAME_RE.fullmatch(skill.name):
        raise OwlError(f"Refusing to install skill with unsafe name {skill.name!r}")
    dest = target / skill.name
    replaced_existing = dest.exists()
    if replaced_existing and not force:
        marker = read_marker(dest)
        if marker is None:
            raise OwlError(f"{dest} already exists and was not installed by owl (use --force)")
        if marker.ref != skill.ref:
            raise OwlError(
                f"{dest} holds {marker.ref}, refusing to replace it with {skill.ref} (use --force)"
            )
        modified = marker.modified_files()
        if modified:
            raise OwlError(
                f"{dest} has local modifications ({', '.join(modified[:5])}"
                f"{'...' if len(modified) > 5 else ''}); use --force to replace it "
                "(the old copy is kept in the owl backup directory)"
            )
        if marker.sha256 == skill.sha256 and modified == []:
            return dest  # already installed and untouched
    files = dict(skill.files)
    files[SKILL_FILE] = skill.content.encode("utf-8")
    marker_data = {
        "format": MARKER_FORMAT,
        "ref": skill.ref,
        "version": skill.version,
        "sha256": skill.sha256,
        "source": source,
        "files": hash_tree(files),
    }
    files[MARKER] = (json.dumps(marker_data, indent=2) + "\n").encode("utf-8")
    replace_dir(dest, files, keep_backup_in=backup_root() if replaced_existing and force else None)
    return dest


def read_marker(path: Path) -> Installed | None:
    file = path / MARKER
    try:
        data = json.loads(file.read_text("utf-8"))
        files = data.get("files")
        return Installed(
            name=path.name,
            ref=data["ref"],
            version=data.get("version", ""),
            sha256=data.get("sha256", ""),
            source=data.get("source", ""),
            path=path,
            files=files if isinstance(files, dict) else None,
        )
    except (OSError, ValueError, KeyError):
        return None


def list_installed(target: Path) -> list[Installed]:
    if not target.is_dir():
        return []
    items = [read_marker(p) for p in sorted(target.iterdir()) if p.is_dir()]
    return [i for i in items if i is not None]


def uninstall_skill(name: str, target: Path, *, force: bool = False) -> Path:
    """Remove an OWL-installed skill; modified installs need *force* (and are backed up)."""
    if not NAME_RE.fullmatch(name):
        raise OwlError(f"Invalid skill name {name!r}")
    dest = target / name
    marker = read_marker(dest) if dest.is_dir() else None
    if marker is None:
        raise OwlError(f"{name} was not installed by owl in {target}")
    modified = marker.modified_files()
    if modified and not force:
        raise OwlError(
            f"{name} has local modifications ({', '.join(modified[:5])}); use --force to remove it "
            "(a backup is kept)"
        )
    if modified:
        keep = backup_root()
        keep.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        shutil.copytree(dest, keep / f"{stamp}-removed-{name}")
    shutil.rmtree(dest)
    return dest
