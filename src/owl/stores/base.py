"""The store interface every backend (SQL, directory, remote server) implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from owl.models import (
    AmbiguousRef,
    NotFound,
    SearchQuery,
    Skill,
    SkillSummary,
    split_ref,
)

FACET_KINDS = ("author", "tag", "topic")
PAGE_SIZE = 500


def rank(summary: SkillSummary, terms: list[str]) -> int:
    """Relevance bucket: 0 = name matches, 1 = description matches, 2 = anything else."""
    if not terms:
        return 0
    first = terms[0]
    if first in summary.name.lower():
        return 0
    if first in summary.description.lower():
        return 1
    return 2


def filter_and_rank(
    items: Iterable[tuple[SkillSummary, str]], query: SearchQuery
) -> list[SkillSummary]:
    """Apply *query* to ``(summary, extra_text)`` pairs with the semantics every store shares.

    ``extra_text`` is additional searchable text (the SKILL.md body) or ``""``.
    """
    terms = query.terms()
    results: list[SkillSummary] = []
    for summary, extra in items:
        if query.author and summary.author != query.author.lower():
            continue
        if any(t.lower() not in summary.tags for t in query.tags):
            continue
        if any(t.lower() not in summary.topics for t in query.topics):
            continue
        haystack = [
            summary.name,
            summary.description,
            summary.author,
            extra,
            *summary.tags,
            *summary.topics,
        ]
        lowered = [h.lower() for h in haystack]
        if any(not any(term in h for h in lowered) for term in terms):
            continue
        results.append(summary)
    results.sort(key=lambda s: (rank(s, terms), s.author, s.name))
    return results[query.offset : query.offset + query.limit]


class SkillStore(ABC):
    """Storage for skills. Implementations must be safe to use from several threads."""

    #: Label used to tag search results (``"local"`` or a remote name).
    label: str = "local"

    @abstractmethod
    def upsert(self, skill: Skill) -> Skill:
        """Insert or update *skill* (identified by author/name) and return the stored copy."""

    @abstractmethod
    def get(self, author: str, name: str) -> Skill | None:
        """Return the full skill or ``None``."""

    @abstractmethod
    def delete(self, author: str, name: str) -> bool:
        """Delete a skill; returns whether it existed."""

    @abstractmethod
    def search(self, query: SearchQuery) -> list[SkillSummary]:
        """Return matching summaries ordered by relevance, author and name."""

    @abstractmethod
    def facets(self, kind: str) -> list[tuple[str, int]]:
        """Return ``(value, skill_count)`` for ``author``, ``tag`` or ``topic``."""

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release resources."""

    def count(self) -> int:
        return len(self.list())

    def list(self) -> list[SkillSummary]:
        """Return every skill, fetched page by page."""
        results: list[SkillSummary] = []
        while True:
            page = self.search(SearchQuery(limit=PAGE_SIZE, offset=len(results)))
            results.extend(page)
            if len(page) < PAGE_SIZE:
                return results

    def resolve(self, ref: str) -> tuple[str, str]:
        """Resolve ``author/name`` or a bare ``name`` to ``(author, name)``."""
        author, name = split_ref(ref)
        if author is not None:
            if self.get(author, name) is None:
                raise NotFound(f"Skill not found: {ref}")
            return author, name
        matches = sorted(s.ref for s in self.list() if s.name == name)
        if not matches:
            raise NotFound(f"Skill not found: {ref}")
        if len(matches) > 1:
            raise AmbiguousRef(f"'{ref}' is ambiguous, use one of: {', '.join(matches)}")
        author, _, name = matches[0].partition("/")
        return author, name

    def get_ref(self, ref: str) -> Skill:
        author, name = self.resolve(ref)
        skill = self.get(author, name)
        if skill is None:
            raise NotFound(f"Skill not found: {ref}")
        return skill

    def __enter__(self) -> SkillStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
