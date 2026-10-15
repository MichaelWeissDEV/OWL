"""Migrations, the local user database and the catalog revision history."""

from __future__ import annotations

import json
import sqlite3

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, text

from owl import paths
from owl.localdb import LocalDB
from owl.migrations import Migration, MigrationError, Migrator
from owl.models import SearchQuery
from owl.stores.sql import SqlStore, skills_t
from tests.conftest import make_skill


def test_fresh_catalog_is_at_latest_version(tmp_path):
    store = SqlStore(str(tmp_path / "c.sqlite3"))
    assert store.migrator.current() == store.migrator.latest == 2
    assert store.migrator.pending() == []


def test_revisions_are_recorded_only_for_new_hashes(tmp_path):
    store = SqlStore(str(tmp_path / "c.sqlite3"))
    store.upsert(make_skill("rev", description="one"))
    store.upsert(make_skill("rev", description="one"))  # identical: no new revision
    store.upsert(make_skill("rev", description="two", version="2.0.0"))
    store.upsert(make_skill("rev", description="one"))  # back to an older hash: known already
    revisions = store.revisions("alice", "rev")
    assert len(revisions) == 2 and revisions[1]["version"] == "2.0.0"


def _legacy_db(path):
    """A database as created before migrations existed (v1 tables, data, no version table)."""
    engine = create_engine(f"sqlite:///{path}")
    meta = MetaData()
    skills_t.to_metadata(meta)
    for table in (skills_t,):
        table.to_metadata(meta)
    from owl.stores.sql import files_t, labels_t

    for t in (skills_t, labels_t, files_t):
        t.create(engine, checkfirst=True)
    with engine.begin() as conn:
        conn.execute(
            skills_t.insert().values(
                author="alice",
                name="old",
                version="1.0.0",
                description="legacy",
                content="---\nname: old\ndescription: legacy\n---\n",
                extra_json="{}",
                sha256="a" * 64,
                created_at="2024-01-01",
                updated_at="2024-01-01",
            )
        )
    engine.dispose()


def test_legacy_database_is_adopted_backed_up_and_upgraded(tmp_path, owl_home):
    db = tmp_path / "legacy.sqlite3"
    _legacy_db(db)
    store = SqlStore(str(db))
    assert store.migrator.current() == 2
    assert [s.ref for s in store.list()] == ["alice/old"]  # data survived
    assert store.revisions("alice", "old")[0]["sha256"] == "a" * 64  # history back-filled
    backups = list((paths.home() / "backups" / "db").glob("*.sqlite3"))
    assert len(backups) == 1
    check = sqlite3.connect(backups[0])
    assert check.execute("select count(*) from skills").fetchone()[0] == 1
    assert "skill_revisions" not in {r[0] for r in check.execute("select name from sqlite_master")}
    check.close()


def test_database_from_newer_owl_is_refused(tmp_path):
    db = tmp_path / "new.sqlite3"
    SqlStore(str(db)).close()
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(
            text("insert into owl_migrations values ('catalog', 99, 'future', '2030-01-01')")
        )
    engine.dispose()
    with pytest.raises(MigrationError, match="newer OWL"):
        SqlStore(str(db))


def test_failed_migration_rolls_back_and_is_not_recorded(tmp_path, owl_home):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.sqlite3'}")
    meta = MetaData()
    probe = Table("probe", meta, Column("id", Integer, primary_key=True))

    def ok(conn):
        probe.create(conn)

    def broken(conn):
        conn.execute(text("create table half_done (x int)"))
        raise RuntimeError("boom")

    migrator = Migrator(engine, "t", [Migration(1, "one", ok), Migration(2, "two", broken)])
    with pytest.raises(RuntimeError):
        migrator.upgrade()
    assert migrator.current() == 1  # step 1 stays applied, step 2 is not recorded
    with engine.connect() as conn:
        names = {r[0] for r in conn.execute(text("select name from sqlite_master"))}
    assert "half_done" not in names  # the failed step was rolled back
    # a fresh database needs no backup; once data exists, the next attempt backs it up first
    with pytest.raises(RuntimeError):
        migrator.upgrade()
    assert list((paths.home() / "backups" / "db").glob("*-t-v1-*"))


def test_migration_numbering_is_validated(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'x.sqlite3'}")
    with pytest.raises(ValueError):
        Migrator(engine, "x", [Migration(2, "gap", lambda c: None)])


def test_local_db_roundtrip(owl_home):
    with LocalDB() as db:
        assert db.migrator.current() == 2
        assert db.favorite_add("a/x") and not db.favorite_add("a/x")
        db.collection_create("sec", "security things")
        assert db.collection_add("sec", "a/x") and not db.collection_add("sec", "a/x")
        assert db.collections() == [{"name": "sec", "description": "security things", "skills": 1}]
        assert db.collections_of("a/x") == ["sec"]
        db.note_set("a/x", "good")
        db.override_set("a/x", "priority", "high")
        assert db.overrides("a/x") == {"priority": "high"} and db.note_get("a/x") == "good"
        db.trust_add("official")
        assert db.is_trusted("official") and not db.is_trusted("other")
        db.history_add("install", "a/x", "ok", "claude")
        assert db.history()[0]["operation"] == "install"
        db.collection_delete("sec")
        assert db.collections() == []


def test_sync_bookmarks_move_from_state_json_once(owl_home):
    owl_home.mkdir(parents=True)
    (owl_home / "state.json").write_text(json.dumps({"synced": {"team": {"a/x": "h1"}}}))
    with LocalDB() as db:
        assert db.get_synced("team", "a/x") == "h1"
        db.set_synced("team", "a/x", "h2")
    with LocalDB() as db:  # second open must not re-import the old value
        assert db.get_synced("team", "a/x") == "h2"
    assert [s for s in SearchQuery().terms()] == []
