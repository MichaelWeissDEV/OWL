"""Versioned, backed-up schema migrations for OWL's databases.

Each database ("scope") has an ordered list of :class:`Migration` steps. Applied versions are
recorded in the ``owl_migrations`` table. Before pending migrations run on an existing SQLite file
the file is copied to ``$OWL_HOME/backups/db``; every step runs in its own transaction.
A database written by a *newer* OWL is refused instead of being modified.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    event,
    insert,
    inspect,
    select,
)
from sqlalchemy.engine import Connection, Engine

from owl import paths
from owl.models import OwlError

_meta = MetaData()
migrations_t = Table(
    "owl_migrations",
    _meta,
    Column("scope", String(32), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("name", String(128), nullable=False),
    Column("applied_at", DateTime(timezone=True), nullable=False),
)


def make_sqlite_transactional(engine: Engine) -> None:
    """Make SQLite DDL transactional (pysqlite auto-commits before DDL by default).

    Without this a failing migration step would leave half-created tables behind. This is the
    documented SQLAlchemy recipe: no implicit transactions in the driver, explicit ``BEGIN``.
    """
    if engine.dialect.name != "sqlite" or getattr(engine, "_owl_transactional", False):
        return

    @event.listens_for(engine, "connect")
    def _connect(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin(conn):  # type: ignore[no-untyped-def]
        conn.exec_driver_sql("BEGIN")

    engine._owl_transactional = True  # type: ignore[attr-defined]


class MigrationError(OwlError):
    """A database cannot be migrated (for example it is newer than this OWL)."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Connection], None]


class Migrator:
    """Applies the pending migrations of one scope to a database."""

    def __init__(
        self,
        engine: Engine,
        scope: str,
        migrations: list[Migration],
        *,
        legacy_table: str | None = None,
        backup_dir: Path | None = None,
    ) -> None:
        versions = [m.version for m in migrations]
        if versions != sorted(set(versions)) or (versions and versions[0] != 1):
            raise ValueError("migrations must be numbered 1..n without gaps")
        make_sqlite_transactional(engine)
        self.engine = engine
        self.scope = scope
        self.migrations = migrations
        #: a table that exists in databases created before migrations were introduced (= version 1)
        self.legacy_table = legacy_table
        self.backup_dir = backup_dir if backup_dir is not None else paths.home() / "backups" / "db"

    @property
    def latest(self) -> int:
        return self.migrations[-1].version if self.migrations else 0

    def _ensure_table(self) -> None:
        migrations_t.create(self.engine, checkfirst=True)

    def current(self) -> int:
        """Highest applied version (0 for an empty database)."""
        self._ensure_table()
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(migrations_t.c.version).where(migrations_t.c.scope == self.scope)
            ).scalars()
            return max(rows, default=0)

    def pending(self) -> list[Migration]:
        current = self.current()
        return [m for m in self.migrations if m.version > current]

    def status(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "current": self.current(),
            "latest": self.latest,
            "pending": [m.name for m in self.pending()],
        }

    def _stamp_legacy(self) -> None:
        """Databases from before migrations existed already contain version 1's tables."""
        if not self.legacy_table or self.current() != 0:
            return
        if inspect(self.engine).has_table(self.legacy_table):
            with self.engine.begin() as conn:
                first = self.migrations[0]
                conn.execute(
                    insert(migrations_t).values(
                        scope=self.scope,
                        version=first.version,
                        name=first.name + " (adopted)",
                        applied_at=datetime.now(UTC),
                    )
                )

    def backup(self, from_version: int) -> Path | None:
        """Copy the SQLite file before it is migrated. PostgreSQL needs ``pg_dump`` (documented)."""
        if self.engine.dialect.name != "sqlite":
            return None
        source = self.engine.url.database
        if not source or source == ":memory:" or not Path(source).exists():
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = (
            self.backup_dir / f"{Path(source).stem}-{self.scope}-v{from_version}-{stamp}.sqlite3"
        )
        src = sqlite3.connect(source)
        try:
            dst = sqlite3.connect(target)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return target

    def upgrade(self) -> list[Migration]:
        """Apply all pending migrations; returns the ones that ran."""
        self._ensure_table()
        self._stamp_legacy()
        current = self.current()
        if current > self.latest:
            raise MigrationError(
                f"The {self.scope} database has schema version {current}, but this OWL only knows "
                f"up to {self.latest}. It was written by a newer OWL; refusing to touch it."
            )
        pending = [m for m in self.migrations if m.version > current]
        if not pending:
            return []
        if current > 0:
            self.backup(current)
        applied: list[Migration] = []
        for migration in pending:
            with self.engine.begin() as conn:
                migration.apply(conn)
                conn.execute(
                    insert(migrations_t).values(
                        scope=self.scope,
                        version=migration.version,
                        name=migration.name,
                        applied_at=datetime.now(UTC),
                    )
                )
            applied.append(migration)
        return applied
