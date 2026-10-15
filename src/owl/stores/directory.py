"""Directory store: skills as plain files, ready to be versioned in a git repository.

Layout (flat - the author is metadata, not a directory)::

    <root>/skills/<name>/SKILL.md
    <root>/skills/<name>/skill.json   # metadata (author, version, tags, topics, ...)
    <root>/skills/<name>/...          # any bundled files

The older layout ``skills/<author>/<name>/`` is still *read* (and reported via
:attr:`DirectoryStore.legacy_layout`), but writing into it is refused until the repository has
been converted with ``owl registry migrate``.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

from owl.fsutil import replace_dir
from owl.models import (
    InvalidSkill,
    OwlError,
    SearchQuery,
    Skill,
    SkillSummary,
    validate_skill,
)
from owl.parsing import META_FILE, SKILL_FILE, load_skill_dir
from owl.stores.base import FACET_KINDS, SkillStore, filter_and_rank

SKILLS_SUBDIR = "skills"


class NameCollision(OwlError):
    """Two different skills would share one directory name."""


class DirectoryStore(SkillStore):
    """Skills stored as directories below ``<root>/skills``."""

    def __init__(
        self, root: str | Path, label: str = "local", default_author: str = "local"
    ) -> None:
        self.label = label
        self.default_author = default_author
        self.root = Path(root).expanduser().resolve()
        self.base = self.root / SKILLS_SUBDIR
        self._lock = threading.RLock()
        self._cache: dict[tuple[str, str], Skill] | None = None
        self._paths: dict[tuple[str, str], Path] = {}
        self.legacy_layout = False

    # -- helpers ---------------------------------------------------------------------

    def _skill_dir(self, name: str) -> Path:
        return self.base / name

    def _read(self, directory: Path, author: str) -> Skill | None:
        result = load_skill_dir(directory, default_author=author)
        stamp = datetime.fromtimestamp((directory / SKILL_FILE).stat().st_mtime, UTC)
        result.skill.created_at = result.skill.updated_at = stamp.isoformat(timespec="seconds")
        if result.valid:
            return result.skill
        print(
            f"owl: ignoring invalid skill {directory}: " + "; ".join(result.problems),
            file=sys.stderr,
        )
        return None

    def _load_all(self) -> dict[tuple[str, str], Skill]:
        with self._lock:
            if self._cache is not None:
                return self._cache
            cache: dict[tuple[str, str], Skill] = {}
            paths: dict[tuple[str, str], Path] = {}
            self.legacy_layout = False
            if self.base.is_dir():
                for entry in sorted(p for p in self.base.iterdir() if p.is_dir()):
                    if entry.name.startswith("."):
                        continue
                    if (entry / SKILL_FILE).is_file():
                        candidates = [(entry, self.default_author)]
                    else:  # legacy: skills/<author>/<name>/
                        candidates = [
                            (sub, entry.name)
                            for sub in sorted(p for p in entry.iterdir() if p.is_dir())
                            if (sub / SKILL_FILE).is_file()
                        ]
                        self.legacy_layout = self.legacy_layout or bool(candidates)
                    for directory, author in candidates:
                        skill = self._read(directory, author)
                        if skill is not None:
                            cache[(skill.author, skill.name)] = skill
                            paths[(skill.author, skill.name)] = directory
            self._cache = cache
            self._paths = paths
            return cache

    def refresh(self) -> None:
        """Drop the in-memory cache (e.g. after a ``git pull``)."""
        with self._lock:
            self._cache = None

    # -- SkillStore ------------------------------------------------------------------

    def upsert(self, skill: Skill) -> Skill:
        problems = validate_skill(skill)
        if problems:
            raise InvalidSkill("; ".join(problems))
        with self._lock:
            cache = self._load_all()
            if self.legacy_layout:
                raise OwlError(
                    f"{self.base} uses the legacy skills/<author>/<name> layout; "
                    "convert it first with `owl registry migrate`"
                )
            existing = cache.get((skill.author, skill.name))
            if existing is not None and existing.sha256 == skill.sha256:
                return existing
            owner = next((a for (a, n) in cache if n == skill.name and a != skill.author), None)
            if owner is not None:
                raise NameCollision(
                    f"Skill name '{skill.name}' is already used by author '{owner}' in this "
                    "registry; names are unique per registry - choose another name"
                )
            dest = self._skill_dir(skill.name)
            if dest.exists() and existing is None:
                raise NameCollision(
                    f"{dest} exists but does not hold a valid skill; not overwriting"
                )
            files = dict(skill.files)
            files[SKILL_FILE] = skill.content.encode("utf-8")
            files[META_FILE] = (
                json.dumps(skill.meta(), indent=2, ensure_ascii=False) + "\n"
            ).encode("utf-8")
            replace_dir(dest, files)
            self.refresh()
            return self._load_all()[(skill.author, skill.name)]

    def get(self, author: str, name: str) -> Skill | None:
        return self._load_all().get((author.lower(), name))

    def delete(self, author: str, name: str) -> bool:
        with self._lock:
            self._load_all()
            directory = self._paths.get((author.lower(), name))
            if directory is None:
                return False
            shutil.rmtree(directory)
            parent = directory.parent
            if parent != self.base and not any(parent.iterdir()):
                parent.rmdir()
            self.refresh()
            return True

    def path_of(self, author: str, name: str) -> Path | None:
        """Directory of a skill (useful for provenance and tooling)."""
        self._load_all()
        return self._paths.get((author.lower(), name))

    def search(self, query: SearchQuery) -> list[SkillSummary]:
        return filter_and_rank(
            ((sk.summary(self.label), sk.content) for sk in self._load_all().values()), query
        )

    def facets(self, kind: str) -> list[tuple[str, int]]:
        if kind not in FACET_KINDS:
            raise ValueError(f"Unknown facet {kind!r}")
        counts: dict[str, int] = {}
        for skill in self._load_all().values():
            values = {"author": [skill.author], "tag": skill.tags, "topic": skill.topics}[kind]
            for value in values:
                counts[value] = counts.get(value, 0) + 1
        return sorted(counts.items(), key=lambda r: (-r[1], r[0]))

    def count(self) -> int:
        return len(self._load_all())
