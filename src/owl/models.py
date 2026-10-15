"""Core data model: :class:`Skill`, :class:`SkillSummary` and :class:`SearchQuery`."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
AUTHOR_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
MAX_NAME_LEN = 64
MAX_DESCRIPTION_LEN = 1024
MAX_COMPATIBILITY_LEN = 500
MAX_TOTAL_BYTES = 20 * 1024 * 1024

#: ``skill.json`` keys that map to first-class fields. Everything else is ``extra``.
KNOWN_META_KEYS = ("author", "name", "version", "description", "tags", "topics")


class OwlError(Exception):
    """Base class for all expected, user-facing errors."""


class NotFound(OwlError):
    """A skill (or remote) does not exist."""


class AmbiguousRef(OwlError):
    """A bare skill name matches skills of several authors."""


class InvalidSkill(OwlError):
    """A skill failed validation and cannot be stored."""


def normalize_labels(values: Any) -> list[str]:
    """Normalise tags/topics: lower-case, stripped, de-duplicated and sorted.

    Accepts ``None``, a comma separated string or any iterable of strings.
    """
    if values is None:
        return []
    if isinstance(values, str):
        values = values.split(",")
    try:
        items = [str(v).strip().lower() for v in values]
    except TypeError:
        return []
    return sorted({v for v in items if v})


def split_ref(ref: str) -> tuple[str | None, str]:
    """Split ``author/name`` into its parts; a bare ``name`` has no author."""
    if "/" in ref:
        author, _, name = ref.partition("/")
        return author.lower(), name
    return None, ref


@dataclass(slots=True)
class SkillSummary:
    """Lightweight skill description used for listings and search results."""

    author: str
    name: str
    version: str = "0.0.0"
    description: str = ""
    tags: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    sha256: str = ""
    updated_at: str | None = None
    source: str | None = None  #: label of the store/remote this result came from

    @property
    def ref(self) -> str:
        return f"{self.author}/{self.name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "author": self.author,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "tags": list(self.tags),
            "topics": list(self.topics),
            "sha256": self.sha256,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str | None = None) -> SkillSummary:
        return cls(
            author=str(data["author"]),
            name=str(data["name"]),
            version=str(data.get("version") or "0.0.0"),
            description=str(data.get("description") or ""),
            tags=normalize_labels(data.get("tags")),
            topics=normalize_labels(data.get("topics")),
            sha256=str(data.get("sha256") or ""),
            updated_at=data.get("updated_at"),
            source=source,
        )


@dataclass(slots=True)
class Skill:
    """A complete skill: ``SKILL.md`` text, metadata and bundled files.

    ``sha256`` is derived from the content, the metadata and the files - never from
    timestamps - so identical skills always hash identically in every store.
    """

    author: str
    name: str
    version: str = "0.0.0"
    description: str = ""
    tags: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    content: str = ""  #: complete SKILL.md text including the frontmatter
    extra: dict[str, Any] = field(default_factory=dict)  #: additional skill.json keys
    files: dict[str, bytes] = field(default_factory=dict)  #: bundled files by relative path
    created_at: str | None = None
    updated_at: str | None = None
    sha256: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.author = self.author.strip().lower()
        self.tags = normalize_labels(self.tags)
        self.topics = normalize_labels(self.topics)
        self.sha256 = self.compute_sha256()

    @property
    def ref(self) -> str:
        return f"{self.author}/{self.name}"

    @property
    def total_bytes(self) -> int:
        return len(self.content.encode("utf-8")) + sum(len(d) for d in self.files.values())

    def meta(self) -> dict[str, Any]:
        """The ``skill.json`` representation (first-class fields followed by extras)."""
        data: dict[str, Any] = {
            "author": self.author,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "tags": self.tags,
            "topics": self.topics,
        }
        data.update(self.extra)
        return data

    def compute_sha256(self) -> str:
        meta = json.dumps(self.meta(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256()
        digest.update(b"meta\0" + meta.encode("utf-8"))
        digest.update(b"\0skill\0" + self.content.encode("utf-8"))
        for path in sorted(self.files):
            file_hash = hashlib.sha256(self.files[path]).hexdigest()
            digest.update(b"\0file\0" + path.encode("utf-8") + b"\0" + file_hash.encode())
        return digest.hexdigest()

    def summary(self, source: str | None = None) -> SkillSummary:
        return SkillSummary(
            author=self.author,
            name=self.name,
            version=self.version,
            description=self.description,
            tags=list(self.tags),
            topics=list(self.topics),
            sha256=self.sha256,
            updated_at=self.updated_at,
            source=source,
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form used on the wire (files are base64 encoded)."""
        data = self.summary().to_dict()
        data.update(
            content=self.content,
            extra=self.extra,
            created_at=self.created_at,
            files={p: base64.b64encode(d).decode("ascii") for p, d in self.files.items()},
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skill:
        from owl.fsutil import safe_relpath

        files = {
            safe_relpath(path): base64.b64decode(blob)
            for path, blob in (data.get("files") or {}).items()
        }
        return cls(
            author=str(data["author"]),
            name=str(data["name"]),
            version=str(data.get("version") or "0.0.0"),
            description=str(data.get("description") or ""),
            tags=data.get("tags") or [],
            topics=data.get("topics") or [],
            content=str(data.get("content") or ""),
            extra=dict(data.get("extra") or {}),
            files=files,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass(slots=True)
class SearchQuery:
    """Search parameters shared by every store.

    ``text`` is split into words; every word must occur (case-insensitively) in the
    name, description, author, tags, topics or body. ``tags`` and ``topics`` must all
    be present on a skill.
    """

    text: str = ""
    author: str | None = None
    tags: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    limit: int = 50
    offset: int = 0

    def terms(self) -> list[str]:
        return self.text.lower().split()


def validate_skill(skill: Skill) -> list[str]:
    """Return a list of human readable problems; empty means the skill is valid."""
    problems: list[str] = []
    if not skill.name or not NAME_RE.fullmatch(skill.name) or len(skill.name) > MAX_NAME_LEN:
        problems.append(
            f"Invalid skill name {skill.name!r}: use lower-case letters, digits and single "
            f"hyphens, at most {MAX_NAME_LEN} characters"
        )
    if not skill.author or not AUTHOR_RE.fullmatch(skill.author):
        problems.append(f"Invalid author {skill.author!r}: use lower-case letters, digits, . _ -")
    if not skill.description.strip():
        problems.append("Missing frontmatter 'description'")
    if len(skill.description) > MAX_DESCRIPTION_LEN:
        problems.append(f"Description is longer than {MAX_DESCRIPTION_LEN} characters")
    if not skill.content.strip():
        problems.append("SKILL.md is empty")
    reserved = sorted({"SKILL.md", "skill.json"} & set(skill.files))
    if reserved:
        problems.append(f"Bundled files may not use reserved names: {', '.join(reserved)}")
    if skill.total_bytes > MAX_TOTAL_BYTES:
        problems.append(f"Skill is larger than {MAX_TOTAL_BYTES // (1024 * 1024)} MiB")
    return problems
