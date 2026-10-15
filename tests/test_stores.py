"""Contract tests that every store implementation must pass."""

from __future__ import annotations

import pytest

from owl.models import AmbiguousRef, InvalidSkill, NotFound, OwlError, SearchQuery
from owl.stores.directory import DirectoryStore
from owl.stores.sql import SqlStore, normalize_db_url
from tests.conftest import make_skill


def fill(store, skills):
    for s in skills:
        store.upsert(s)


def test_roundtrip_preserves_everything(any_store, sample_skills):
    fill(any_store, sample_skills)
    for original in sample_skills:
        got = any_store.get(original.author, original.name)
        assert got is not None
        assert got.sha256 == original.sha256
        assert got.content == original.content
        assert got.files == original.files
        assert got.extra == original.extra
        assert got.tags == original.tags and got.topics == original.topics


def test_upsert_is_idempotent_and_updates(any_store):
    first = any_store.upsert(make_skill("one"))
    again = any_store.upsert(make_skill("one"))
    assert first.sha256 == again.sha256 and first.updated_at == again.updated_at
    changed = any_store.upsert(make_skill("one", description="changed"))
    assert changed.description == "changed"
    assert any_store.count() == 1


def test_get_missing_and_delete(any_store):
    assert any_store.get("nobody", "nothing") is None
    any_store.upsert(make_skill("gone"))
    assert any_store.delete("alice", "gone") is True
    assert any_store.delete("alice", "gone") is False
    assert any_store.get("alice", "gone") is None


def test_invalid_skill_is_rejected(any_store):
    bad = make_skill("Bad_Name")
    with pytest.raises(OwlError):
        any_store.upsert(bad)
    assert issubclass(InvalidSkill, OwlError)


def test_search_filters(any_store, sample_skills):
    fill(any_store, sample_skills)
    refs = lambda **kw: [s.ref for s in any_store.search(SearchQuery(**kw))]  # noqa: E731
    assert refs() == ["alice/docs-writer", "alice/git-helper", "bob/sql-tuner"]
    assert refs(author="alice") == ["alice/docs-writer", "alice/git-helper"]
    assert refs(author="ALICE") == ["alice/docs-writer", "alice/git-helper"]
    assert refs(tags=["git"]) == ["alice/git-helper"]
    assert refs(tags=["sql", "postgres"]) == ["bob/sql-tuner"]
    assert refs(tags=["sql", "git"]) == []
    assert refs(topics=["devtools"]) == ["alice/docs-writer", "alice/git-helper"]
    assert refs(text="tuner") == ["bob/sql-tuner"]
    assert refs(text="BODY OF docs-writer") == ["alice/docs-writer"]  # case-insensitive, AND
    assert refs(text="postgres") == ["bob/sql-tuner"]  # matches tags
    assert refs(text="zzz-nothing") == []
    assert refs(text="100%") == []  # LIKE wildcards are escaped
    assert refs(limit=1) == ["alice/docs-writer"]
    assert refs(limit=1, offset=1) == ["alice/git-helper"]


def test_search_ranks_name_matches_first(any_store):
    any_store.upsert(make_skill("aaa", description="mentions widget here"))
    any_store.upsert(make_skill("widget-maker", description="makes things"))
    assert [s.name for s in any_store.search(SearchQuery(text="widget"))] == [
        "widget-maker",
        "aaa",
    ]


def test_facets(any_store, sample_skills):
    fill(any_store, sample_skills)
    assert any_store.facets("author") == [("alice", 2), ("bob", 1)]
    assert dict(any_store.facets("topic"))["devtools"] == 2
    assert ("sql", 1) in any_store.facets("tag")


def test_resolve_bare_names(any_store):
    any_store.upsert(make_skill("shared", "alice"))
    any_store.upsert(make_skill("shared", "bob"))
    any_store.upsert(make_skill("unique", "alice"))
    assert any_store.resolve("unique") == ("alice", "unique")
    assert any_store.resolve("bob/shared") == ("bob", "shared")
    with pytest.raises(AmbiguousRef):
        any_store.resolve("shared")
    with pytest.raises(NotFound):
        any_store.resolve("missing")


def test_list_pages_through_everything(any_store):
    for i in range(7):
        any_store.upsert(make_skill(f"skill-{i}"))
    assert len(any_store.list()) == 7


def test_cross_store_roundtrip_keeps_sha(sample_skills, tmp_path, remote_store):
    """SQL -> directory -> remote -> SQL must not change a skill's hash."""
    a = SqlStore(str(tmp_path / "a.sqlite3"))
    b = DirectoryStore(tmp_path / "dir")
    c = SqlStore(str(tmp_path / "c.sqlite3"))
    for original in sample_skills:
        a_skill = a.upsert(original)
        b_skill = b.upsert(a_skill)
        r_skill = remote_store.upsert(b.get(*b_skill.ref.split("/")))
        c_skill = c.upsert(remote_store.get(*r_skill.ref.split("/")))
        assert c_skill.sha256 == original.sha256


def test_directory_store_layout(dir_store, sample_skills):
    dir_store.upsert(sample_skills[1])
    base = dir_store.root / "skills" / "bob" / "sql-tuner"
    assert (base / "SKILL.md").is_file()
    assert (base / "skill.json").is_file()
    assert (base / "scripts" / "run.sh").read_bytes().startswith(b"#!/bin/sh")
    fresh = DirectoryStore(dir_store.root)  # a new instance reads the same data from disk
    assert fresh.get("bob", "sql-tuner").sha256 == sample_skills[1].sha256


def test_normalize_db_url(tmp_path):
    assert normalize_db_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_db_url("postgres://u@h/db") == "postgresql+psycopg://u@h/db"
    assert normalize_db_url("postgresql+psycopg://u@h/db") == "postgresql+psycopg://u@h/db"
    assert normalize_db_url(str(tmp_path / "x.db")).startswith("sqlite:////")
