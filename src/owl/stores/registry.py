"""Read-only store backed by a skill registry (a git repository or a local directory)."""

from __future__ import annotations

import time
from pathlib import Path

from owl import gitutil
from owl.models import OwlError, SearchQuery, Skill, SkillSummary
from owl.parsing import find_skill_dirs, load_skill_dir
from owl.registry import INDEX_FILE, load_index
from owl.stores.base import FACET_KINDS, SkillStore, filter_and_rank

STAMP = ".owl-fetched"
DEFAULT_TTL = 3600  #: seconds before a cached registry is refreshed on the next read


class RegistryStore(SkillStore):
    """A registry as a store.

    *source* is a git URL (cloned shallowly into *cache_dir* and refreshed at most every *ttl*
    seconds; if the network is down the cache is used) or a local directory. If the registry has an
    ``index.json`` it is used for searching; otherwise the repository is scanned for ``SKILL.md``
    files, so any repository with skills can serve as a registry.
    """

    def __init__(
        self,
        source: str,
        label: str,
        cache_dir: Path,
        ref: str | None = None,
        ttl: int = DEFAULT_TTL,
        refresh: bool = False,
        auto_update: bool = True,
        offline: str = "cache",
        verify: bool = True,
    ) -> None:
        self.label = label
        self.source = source
        self.ref = ref
        self.cache_dir = cache_dir
        self.ttl = ttl
        self.refresh = refresh
        self.auto_update = auto_update
        self.offline = offline
        self.verify = verify
        self.warnings: list[str] = []
        self.fetched_at: float | None = None
        self._root: Path | None = None
        self._entries: dict[str, tuple[SkillSummary, str, str]] | None = (
            None  # ref -> (sum, path, text)
        )
        self._index: dict | None = None

    # -- location ----------------------------------------------------------------------

    @property
    def root(self) -> Path:
        if self._root is None:
            self._root = self._prepare()
        return self._root

    @property
    def is_local_directory(self) -> bool:
        return not gitutil.is_git_url(self.source)

    def _age_text(self) -> str:
        if self.fetched_at is None:
            return "unknown age"
        hours = (time.time() - self.fetched_at) / 3600
        return f"{hours:.1f} h old" if hours < 48 else f"{hours / 24:.0f} days old"

    def _prepare(self) -> Path:
        if self.is_local_directory:
            path = Path(self.source).expanduser().resolve()
            if not path.is_dir():
                raise OwlError(f"Registry '{self.label}': {self.source} is not a directory")
            return path
        stamp = self.cache_dir / STAMP
        cloned = gitutil.is_repo(self.cache_dir)
        if cloned and stamp.exists():
            self.fetched_at = stamp.stat().st_mtime
        fresh = cloned and self.fetched_at is not None and time.time() - self.fetched_at < self.ttl
        if cloned and not self.refresh and (fresh or not self.auto_update):
            return self.cache_dir
        try:
            if not cloned:
                self.cache_dir.parent.mkdir(parents=True, exist_ok=True)
                gitutil.clone(self.source, self.cache_dir, ref=self.ref)
            else:
                gitutil.set_remote(self.cache_dir, self.source)  # the URL may have changed
                gitutil.fetch_reset(self.cache_dir, self.ref)
            stamp.touch()
            self.fetched_at = stamp.stat().st_mtime
        except OwlError as exc:
            if not cloned:
                raise OwlError(f"Cannot fetch registry '{self.label}': {exc}") from exc
            if self.offline == "fail":
                raise OwlError(
                    f"Cannot refresh registry '{self.label}' (offline policy: fail): {exc}"
                ) from exc
            # the previous, valid cache is untouched by a failed fetch
            self.warnings.append(
                f"registry '{self.label}' could not be refreshed - using the cache "
                f"({self._age_text()}): {exc}"
            )
        return self.cache_dir

    def update(self) -> None:
        """Force a refresh from the network."""
        self.refresh = True
        self._root = None
        self._entries = None
        self._index = None
        _ = self.root

    def head_commit(self) -> str | None:
        """Commit of the registry checkout (cache or local repository)."""
        root = self.root
        return gitutil.head_commit(root) if gitutil.is_repo(root) else None

    # -- index -------------------------------------------------------------------------

    def _load(self) -> dict[str, tuple[SkillSummary, str, str]]:
        if self._entries is not None:
            return self._entries
        root = self.root
        entries: dict[str, tuple[SkillSummary, str, str]] = {}
        index = load_index(root) if (root / INDEX_FILE).is_file() else None
        self._index = index
        if index is not None:
            for item in index["skills"]:
                summary = SkillSummary.from_dict(item, source=self.label)
                entries[summary.ref] = (summary, item["path"], "")
        else:
            skills_dir = root / "skills" if (root / "skills").is_dir() else root
            for directory in find_skill_dirs(skills_dir):
                result = load_skill_dir(directory)
                if result.valid:
                    skill = result.skill
                    rel = directory.relative_to(root).as_posix()
                    entries[skill.ref] = (skill.summary(self.label), rel, skill.content)
        self._entries = entries
        return entries

    # -- SkillStore --------------------------------------------------------------------

    def upsert(self, skill: Skill) -> Skill:
        raise OwlError(
            f"Registry '{self.label}' is read-only. Contribute with a pull request, or use "
            "`owl registry publish` on a local checkout of it."
        )

    def delete(self, author: str, name: str) -> bool:
        raise OwlError(f"Registry '{self.label}' is read-only")

    def get(self, author: str, name: str) -> Skill | None:
        entry = self._load().get(f"{author.lower()}/{name}")
        if entry is None:
            return None
        summary, rel, _text = entry
        root = self.root.resolve()
        directory = (root / rel).resolve()
        if not directory.is_relative_to(root) or not (directory / "SKILL.md").is_file():
            raise OwlError(f"Registry '{self.label}' has an invalid path for {author}/{name}")
        result = load_skill_dir(directory)
        if not result.valid:
            raise OwlError(f"{author}/{name}: {'; '.join(result.problems)}")
        skill = result.skill
        if (
            self._index is not None
            and self.verify
            and summary.sha256
            and skill.sha256 != summary.sha256
        ):
            raise OwlError(
                f"Registry '{self.label}': the index entry for {author}/{name} does not match the "
                "skill's content (stale index or tampering). Run `owl registry update`, report it "
                "to the registry maintainers, or disable the check with `owl registry set "
                f"{self.label} verify false`."
            )
        revision = next(
            (
                e.get("revision")
                for e in (self._index or {}).get("skills", [])
                if e.get("ref") == skill.ref
            ),
            None,
        )
        skill.provenance = {
            "kind": "registry",
            "registry": self.label,
            "url": self.source,
            "ref": self.ref,
            "commit": revision or self.head_commit(),
            "registry_commit": self.head_commit(),
            "path": rel,
            "sha256": skill.sha256,
        }
        return skill

    def search(self, query: SearchQuery) -> list[SkillSummary]:
        return filter_and_rank(((s, text) for s, _p, text in self._load().values()), query)

    def facets(self, kind: str) -> list[tuple[str, int]]:
        if kind not in FACET_KINDS:
            raise ValueError(f"Unknown facet {kind!r}")
        counts: dict[str, int] = {}
        for summary, _path, _text in self._load().values():
            values = {
                "author": [summary.author],
                "tag": summary.tags,
                "topic": summary.topics,
            }[kind]
            for value in values:
                counts[value] = counts.get(value, 0) + 1
        return sorted(counts.items(), key=lambda r: (-r[1], r[0]))

    def count(self) -> int:
        return len(self._load())

    def info(self) -> dict:
        index = load_index(self.root) if (self.root / INDEX_FILE).is_file() else None
        return {
            "kind": "registry",
            "name": (index or {}).get("name", self.label),
            "skills": self.count(),
            "updated_at": (index or {}).get("generated_at"),
            "indexed": index is not None,
            "commit": self.head_commit(),
            "fetched_at": self.fetched_at,
            "stale": self.fetched_at is not None and time.time() - self.fetched_at > self.ttl,
        }
