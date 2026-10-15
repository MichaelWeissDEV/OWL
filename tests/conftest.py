from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from owl.models import Skill
from owl.server import create_app
from owl.stores.directory import DirectoryStore
from owl.stores.remote import RemoteStore
from owl.stores.sql import SqlStore

TOKEN = "s3cret"


@pytest.fixture(autouse=True)
def owl_home(tmp_path, monkeypatch):
    """Never touch the real ~/.owl or ~/.claude during tests."""
    home = tmp_path / "owl-home"
    monkeypatch.setenv("OWL_HOME", str(home))
    return home


def make_skill(name="alpha", author="alice", **kw) -> Skill:
    description = kw.pop("description", f"The {name} skill for testing")
    content = kw.pop(
        "content",
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name.title()}\n\nBody of {name}.\n",
    )
    return Skill(author=author, name=name, description=description, content=content, **kw)


@pytest.fixture
def sample_skills() -> list[Skill]:
    return [
        make_skill(
            "git-helper", "alice", tags=["git", "vcs"], topics=["devtools"], version="1.2.0"
        ),
        make_skill(
            "sql-tuner",
            "bob",
            tags=["sql", "postgres"],
            topics=["databases"],
            files={"scripts/run.sh": b"#!/bin/sh\necho hi\n", "data.bin": bytes(range(256))},
            extra={"license": "MIT"},
        ),
        make_skill("docs-writer", "alice", tags=["docs"], topics=["devtools", "writing"]),
    ]


@pytest.fixture
def sql_store(tmp_path):
    store = SqlStore(str(tmp_path / "t.sqlite3"))
    yield store
    store.close()


@pytest.fixture
def dir_store(tmp_path):
    return DirectoryStore(tmp_path / "repo")


@pytest.fixture
def server_store(tmp_path):
    store = SqlStore(str(tmp_path / "server.sqlite3"), label="server")
    yield store
    store.close()


@pytest.fixture
def remote_store(server_store):
    client = TestClient(create_app(server_store, token=TOKEN))
    return RemoteStore("http://testserver", TOKEN, label="srv", client=client)


@pytest.fixture
def pg_store():
    """A clean PostgreSQL store (only when OWL_TEST_POSTGRES_URL is set)."""
    from owl.stores.sql import SqlStore, files_t, labels_t, skills_t

    url = os.environ.get("OWL_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("OWL_TEST_POSTGRES_URL is not set")
    store = SqlStore(url)
    with store.engine.begin() as conn:
        for table in (files_t, labels_t, skills_t):
            conn.execute(table.delete())
    yield store
    store.close()


@pytest.fixture(params=["sql", "dir", "remote", "postgres"])
def any_store(request, sql_store, dir_store, remote_store):
    """Every store implementation; the shared contract tests run against each."""
    if request.param == "postgres":
        return request.getfixturevalue("pg_store")
    return {"sql": sql_store, "dir": dir_store, "remote": remote_store}[request.param]
