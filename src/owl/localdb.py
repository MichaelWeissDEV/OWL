"""The user's local SQLite database: favorites, collections, notes, installations, history, ...

This is *personal* data about skills, kept apart from the skill catalog (which may live in SQLite,
PostgreSQL or a git repository). Skills are referenced by their ``author/name`` text, so the data
survives switching the catalog backend. Nothing here is ever uploaded to a registry or server.
"""

from __future__ import annotations

import json
import sqlite3  # noqa: F401  (documented dependency of the SQLite file format)
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Connection, Engine

from owl import paths
from owl.migrations import Migration, Migrator
from owl.models import NotFound, OwlError

metadata = MetaData()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


favorites_t = Table(
    "favorites",
    metadata,
    Column("ref", String(200), primary_key=True),
    Column("added_at", String(40), nullable=False),
)
collections_t = Table(
    "collections",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False, unique=True),
    Column("description", Text, nullable=False, default=""),
    Column("created_at", String(40), nullable=False),
)
collection_skills_t = Table(
    "collection_skills",
    metadata,
    Column("collection_id", Integer, ForeignKey("collections.id"), primary_key=True),
    Column("ref", String(200), primary_key=True),
    Column("added_at", String(40), nullable=False),
)
notes_t = Table(
    "notes",
    metadata,
    Column("ref", String(200), primary_key=True),
    Column("text", Text, nullable=False),
    Column("updated_at", String(40), nullable=False),
)
overrides_t = Table(
    "metadata_overrides",
    metadata,
    Column("ref", String(200), primary_key=True),
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
)
sources_t = Table(
    "sources",
    metadata,
    Column("name", String(100), primary_key=True),
    Column("kind", String(16), nullable=False),  # directory | git | server | registry
    Column("location", Text, nullable=False),
    Column("added_at", String(40), nullable=False),
)
trusted_t = Table(
    "trusted_sources",
    metadata,
    Column("source", String(300), primary_key=True),  # remote name, URL or directory
    Column("note", Text, nullable=False, default=""),
    Column("added_at", String(40), nullable=False),
)
installations_t = Table(
    "installations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("ref", String(200), nullable=False),
    Column("name", String(64), nullable=False),
    Column("target", String(32), nullable=False),
    Column("directory", Text, nullable=False),
    Column("scope", String(8), nullable=False),  # global | project | custom
    Column("project_root", Text),
    Column("version", String(64), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("source", Text, nullable=False),
    Column("registry", Text),
    Column("revision", String(64)),
    Column("installed_at", String(40), nullable=False),
    UniqueConstraint("directory", name="uq_installation_directory"),
)
history_t = Table(
    "operation_history",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("at", String(40), nullable=False),
    Column("operation", String(32), nullable=False),
    Column("ref", String(200)),
    Column("status", String(16), nullable=False),  # ok | skipped | failed
    Column("detail", Text, nullable=False, default=""),
)
sync_state_t = Table(
    "sync_state",
    metadata,
    Column("remote", String(100), primary_key=True),
    Column("ref", String(200), primary_key=True),
    Column("sha256", String(64), nullable=False),
    Column("updated_at", String(40), nullable=False),
)
drafts_t = Table(
    "drafts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(200), nullable=False),
    Column("origin", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("problems_json", Text, nullable=False),
    Column("created_at", String(40), nullable=False),
)
meta_t = Table(
    "local_meta",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
)


def _v1(conn: Connection) -> None:
    for table in metadata.sorted_tables:
        table.create(conn, checkfirst=True)


LOCAL_MIGRATIONS = [Migration(1, "local user data tables", _v1)]


class LocalDB:
    """Access to the personal SQLite database (``$OWL_HOME/local.sqlite3`` by default)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else paths.home() / "local.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite:///{self.path}", connect_args={"check_same_thread": False}, future=True
        )
        self.migrator = Migrator(self.engine, "local", LOCAL_MIGRATIONS)
        self.migrator.upgrade()
        self._import_legacy_state()

    def close(self) -> None:
        self.engine.dispose()

    def __enter__(self) -> LocalDB:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- bookmarks / legacy state.json -------------------------------------------------

    def _import_legacy_state(self) -> None:
        """Move sync bookmarks from the old ``state.json`` into the database (once)."""
        with self.engine.begin() as conn:
            done = conn.execute(
                select(meta_t.c.value).where(meta_t.c.key == "state_imported")
            ).first()
            if done:
                return
            try:
                state = json.loads(paths.state_file().read_text("utf-8"))
            except (OSError, ValueError):
                state = {}
            for remote, refs in (state.get("synced") or {}).items():
                for ref, sha in refs.items():
                    conn.execute(
                        insert(sync_state_t).values(
                            remote=remote, ref=ref, sha256=sha, updated_at=_now()
                        )
                    )
            conn.execute(insert(meta_t).values(key="state_imported", value=_now()))

    def get_synced(self, remote: str, ref: str) -> str | None:
        with self.engine.connect() as conn:
            return conn.execute(
                select(sync_state_t.c.sha256).where(
                    sync_state_t.c.remote == remote, sync_state_t.c.ref == ref
                )
            ).scalar_one_or_none()

    def set_synced(self, remote: str, ref: str, sha: str | None) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                delete(sync_state_t).where(
                    sync_state_t.c.remote == remote, sync_state_t.c.ref == ref
                )
            )
            if sha is not None:
                conn.execute(
                    insert(sync_state_t).values(
                        remote=remote, ref=ref, sha256=sha, updated_at=_now()
                    )
                )

    # -- favorites ---------------------------------------------------------------------

    def favorite_add(self, ref: str) -> bool:
        with self.engine.begin() as conn:
            if conn.execute(select(favorites_t.c.ref).where(favorites_t.c.ref == ref)).first():
                return False
            conn.execute(insert(favorites_t).values(ref=ref, added_at=_now()))
            return True

    def favorite_remove(self, ref: str) -> bool:
        with self.engine.begin() as conn:
            return conn.execute(delete(favorites_t).where(favorites_t.c.ref == ref)).rowcount > 0

    def favorites(self) -> list[str]:
        with self.engine.connect() as conn:
            return list(
                conn.execute(select(favorites_t.c.ref).order_by(favorites_t.c.ref)).scalars()
            )

    # -- collections -------------------------------------------------------------------

    def _collection_id(self, conn: Connection, name: str) -> int:
        cid = conn.execute(select(collections_t.c.id).where(collections_t.c.name == name)).scalar()
        if cid is None:
            raise NotFound(f"Collection '{name}' does not exist (owl collection create {name})")
        return int(cid)

    def collection_create(self, name: str, description: str = "") -> None:
        if not name.strip() or "/" in name:
            raise OwlError("Collection names must be non-empty and must not contain '/'")
        with self.engine.begin() as conn:
            if conn.execute(select(collections_t.c.id).where(collections_t.c.name == name)).first():
                raise OwlError(f"Collection '{name}' already exists")
            conn.execute(
                insert(collections_t).values(name=name, description=description, created_at=_now())
            )

    def collection_delete(self, name: str) -> None:
        with self.engine.begin() as conn:
            cid = self._collection_id(conn, name)
            conn.execute(
                delete(collection_skills_t).where(collection_skills_t.c.collection_id == cid)
            )
            conn.execute(delete(collections_t).where(collections_t.c.id == cid))

    def collection_add(self, name: str, ref: str) -> bool:
        with self.engine.begin() as conn:
            cid = self._collection_id(conn, name)
            exists = conn.execute(
                select(collection_skills_t.c.ref).where(
                    collection_skills_t.c.collection_id == cid, collection_skills_t.c.ref == ref
                )
            ).first()
            if exists:
                return False
            conn.execute(
                insert(collection_skills_t).values(collection_id=cid, ref=ref, added_at=_now())
            )
            return True

    def collection_remove(self, name: str, ref: str) -> bool:
        with self.engine.begin() as conn:
            cid = self._collection_id(conn, name)
            return (
                conn.execute(
                    delete(collection_skills_t).where(
                        collection_skills_t.c.collection_id == cid,
                        collection_skills_t.c.ref == ref,
                    )
                ).rowcount
                > 0
            )

    def collections(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(
                    collections_t.c.name,
                    collections_t.c.description,
                    func.count(collection_skills_t.c.ref),
                )
                .select_from(
                    collections_t.outerjoin(
                        collection_skills_t,
                        collection_skills_t.c.collection_id == collections_t.c.id,
                    )
                )
                .group_by(collections_t.c.id)
                .order_by(collections_t.c.name)
            ).all()
        return [{"name": n, "description": d, "skills": int(c)} for n, d, c in rows]

    def collection_members(self, name: str) -> list[str]:
        with self.engine.connect() as conn:
            cid = self._collection_id(conn, name)
            return list(
                conn.execute(
                    select(collection_skills_t.c.ref)
                    .where(collection_skills_t.c.collection_id == cid)
                    .order_by(collection_skills_t.c.ref)
                ).scalars()
            )

    def collections_of(self, ref: str) -> list[str]:
        with self.engine.connect() as conn:
            return list(
                conn.execute(
                    select(collections_t.c.name)
                    .select_from(
                        collections_t.join(
                            collection_skills_t,
                            collection_skills_t.c.collection_id == collections_t.c.id,
                        )
                    )
                    .where(collection_skills_t.c.ref == ref)
                    .order_by(collections_t.c.name)
                ).scalars()
            )

    # -- notes and local metadata ------------------------------------------------------

    def note_set(self, ref: str, text: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(notes_t).where(notes_t.c.ref == ref))
            conn.execute(insert(notes_t).values(ref=ref, text=text, updated_at=_now()))

    def note_get(self, ref: str) -> str | None:
        with self.engine.connect() as conn:
            return conn.execute(
                select(notes_t.c.text).where(notes_t.c.ref == ref)
            ).scalar_one_or_none()

    def note_delete(self, ref: str) -> bool:
        with self.engine.begin() as conn:
            return conn.execute(delete(notes_t).where(notes_t.c.ref == ref)).rowcount > 0

    def notes(self) -> dict[str, str]:
        with self.engine.connect() as conn:
            return {r.ref: r.text for r in conn.execute(select(notes_t).order_by(notes_t.c.ref))}

    def override_set(self, ref: str, key: str, value: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                delete(overrides_t).where(overrides_t.c.ref == ref, overrides_t.c.key == key)
            )
            conn.execute(insert(overrides_t).values(ref=ref, key=key, value=value))

    def override_unset(self, ref: str, key: str) -> bool:
        with self.engine.begin() as conn:
            return (
                conn.execute(
                    delete(overrides_t).where(overrides_t.c.ref == ref, overrides_t.c.key == key)
                ).rowcount
                > 0
            )

    def overrides(self, ref: str) -> dict[str, str]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(overrides_t).where(overrides_t.c.ref == ref)).all()
        return {r.key: r.value for r in rows}

    # -- sources and trust -------------------------------------------------------------

    def source_add(self, name: str, kind: str, location: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(sources_t).where(sources_t.c.name == name))
            conn.execute(
                insert(sources_t).values(name=name, kind=kind, location=location, added_at=_now())
            )

    def source_remove(self, name: str) -> bool:
        with self.engine.begin() as conn:
            return conn.execute(delete(sources_t).where(sources_t.c.name == name)).rowcount > 0

    def sources(self) -> list[dict[str, str]]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(sources_t).order_by(sources_t.c.name)).all()
        return [{"name": r.name, "kind": r.kind, "location": r.location} for r in rows]

    def trust_add(self, source: str, note: str = "") -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(trusted_t).where(trusted_t.c.source == source))
            conn.execute(insert(trusted_t).values(source=source, note=note, added_at=_now()))

    def trust_remove(self, source: str) -> bool:
        with self.engine.begin() as conn:
            return conn.execute(delete(trusted_t).where(trusted_t.c.source == source)).rowcount > 0

    def trusted(self) -> list[str]:
        with self.engine.connect() as conn:
            return list(
                conn.execute(select(trusted_t.c.source).order_by(trusted_t.c.source)).scalars()
            )

    def is_trusted(self, source: str) -> bool:
        return source in self.trusted()

    # -- installations and history -----------------------------------------------------

    def installation_record(
        self,
        *,
        ref: str,
        name: str,
        target: str,
        directory: str,
        scope: str,
        project_root: str | None,
        version: str,
        sha256: str,
        source: str,
        registry: str | None = None,
        revision: str | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(installations_t).where(installations_t.c.directory == directory))
            conn.execute(
                insert(installations_t).values(
                    ref=ref,
                    name=name,
                    target=target,
                    directory=directory,
                    scope=scope,
                    project_root=project_root,
                    version=version,
                    sha256=sha256,
                    source=source,
                    registry=registry,
                    revision=revision,
                    installed_at=_now(),
                )
            )

    def installation_forget(self, directory: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(installations_t).where(installations_t.c.directory == directory))

    def installations(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = (
                conn.execute(select(installations_t).order_by(installations_t.c.ref))
                .mappings()
                .all()
            )
        return [dict(r) for r in rows]

    def history_add(
        self, operation: str, ref: str | None, status: str = "ok", detail: str = ""
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                insert(history_t).values(
                    at=_now(), operation=operation, ref=ref, status=status, detail=detail
                )
            )

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(history_t).order_by(history_t.c.id.desc()).limit(limit)
            ).mappings()
            return [dict(r) for r in rows]

    # -- drafts (incomplete imports) ---------------------------------------------------

    def draft_add(self, name: str, origin: str, content: str, problems: list[str]) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(
                insert(drafts_t).values(
                    name=name,
                    origin=origin,
                    content=content,
                    problems_json=json.dumps(problems),
                    created_at=_now(),
                )
            )
            return int(result.inserted_primary_key[0])  # type: ignore[index]

    def drafts(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(drafts_t).order_by(drafts_t.c.id)).mappings().all()
        return [{**dict(r), "problems": json.loads(r["problems_json"])} for r in rows]

    def draft_get(self, draft_id: int) -> dict[str, Any] | None:
        for d in self.drafts():
            if d["id"] == draft_id:
                return d
        return None

    def draft_update(self, draft_id: int, content: str, problems: list[str]) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(drafts_t)
                .where(drafts_t.c.id == draft_id)
                .values(content=content, problems_json=json.dumps(problems))
            )

    def draft_delete(self, draft_id: int) -> bool:
        with self.engine.begin() as conn:
            return conn.execute(delete(drafts_t).where(drafts_t.c.id == draft_id)).rowcount > 0
