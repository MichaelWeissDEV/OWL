"""Runs the shared store contract against PostgreSQL when OWL_TEST_POSTGRES_URL is set.

CI provides a Postgres service container; locally:

    OWL_TEST_POSTGRES_URL=postgresql://user:pw@localhost/owl_test uv run pytest tests/test_postgres.py
"""

from __future__ import annotations

import os

import pytest

from owl.models import SearchQuery
from tests.conftest import make_skill

URL = os.environ.get("OWL_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not URL, reason="OWL_TEST_POSTGRES_URL is not set")


def test_postgres_roundtrip_and_search(pg_store, sample_skills):
    for skill in sample_skills:
        pg_store.upsert(skill)
    for skill in sample_skills:
        got = pg_store.get(skill.author, skill.name)
        assert got is not None and got.sha256 == skill.sha256
    assert [s.ref for s in pg_store.search(SearchQuery(tags=["sql"]))] == ["bob/sql-tuner"]
    assert [s.ref for s in pg_store.search(SearchQuery(text="TUNER"))] == ["bob/sql-tuner"]
    assert pg_store.search(SearchQuery(text="100%")) == []
    assert pg_store.facets("author") == [("alice", 2), ("bob", 1)]
    pg_store.upsert(make_skill("git-helper", "alice", description="changed"))
    assert pg_store.get("alice", "git-helper").description == "changed"
    assert pg_store.delete("bob", "sql-tuner")
