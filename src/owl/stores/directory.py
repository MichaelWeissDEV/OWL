"""Directory store: skills as plain files, ready to be versioned in a git repository.

Layout::

    <root>/skills/<author>/<name>/SKILL.md
    <root>/skills/<author>/<name>/skill.json   # metadata (author, version, tags, topics, ...)
    <root>/skills/<author>/<name>/...          # any bundled files
"""

from __future__ import annotations

import shutil
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

from owl.models import InvalidSkill, SearchQuery, Skill, SkillSummary, validate_skill
from owl.parsing import SKILL_FILE, load_skill_dir, write_skill_dir
from owl.stores.base import FACET_KINDS, SkillStore, filter_and_rank

SKILLS_SUBDIR = "skills"


class DirectoryStore(SkillStore):
    """Skills stored as directories below ``<root>/skills``."""

    def __init__(self, root: str | Path, label: str = "local") -> None:
        self.label = label
        self.root = Path(root).expanduser().resolve()
        self.base = self.root / SKILLS_SUBDIR
        self._lock = threading.RLock()
        self._cache: dict[tuple[str, str], Skill] | None = None

    # -- helpers ---------------------------------------------------------------------

    def _skill_dir(self, author: str, name: str) -> Path:
        return self.base / author / name

    def _load_all(self) -> dict[tuple[str, str], Skill]:
        with self._lock:
            if self._cache is not None:
                return self._cache
            cache: dict[tuple[str, str], Skill] = {}
            if self.base.is_dir():
                for author_dir in sorted(p for p in self.base.iterdir() if p.is_dir()):
                    for skill_dir in sorted(p for p in author_dir.iterdir() if p.is_dir()):
                        if not (skill_dir / SKILL_FILE).is_file():
                            continue
                        result = load_skill_dir(skill_dir, default_author=author_dir.name)
                        skill = result.skill
                        stamp = datetime.fromtimestamp(
                            (skill_dir / SKILL_FILE).stat().st_mtime, UTC
                        ).isoformat(timespec="seconds")
                        skill.created_at = skill.updated_at = stamp
                        if result.valid:
                            cache[(skill.author, skill.name)] = skill
                        else:
                            print(
                                f"owl: ignoring invalid skill {skill_dir}: "
                                + "; ".join(result.problems),
                                file=sys.stderr,
                            )
            self._cache = cache
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
            existing = self._load_all().get((skill.author, skill.name))
            if existing is not None and existing.sha256 == skill.sha256:
                return existing
            dest = self._skill_dir(skill.author, skill.name)
            if dest.exists():
                shutil.rmtree(dest)
            write_skill_dir(skill, dest)
            self.refresh()
            stored = self._load_all()[(skill.author, skill.name)]
        return stored

    def get(self, author: str, name: str) -> Skill | None:
        return self._load_all().get((author.lower(), name))

    def delete(self, author: str, name: str) -> bool:
        with self._lock:
            dest = self._skill_dir(author.lower(), name)
            if not dest.is_dir():
                return False
            shutil.rmtree(dest)
            author_dir = dest.parent
            if not any(author_dir.iterdir()):
                author_dir.rmdir()
            self.refresh()
            return True

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
