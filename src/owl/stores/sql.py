"""SQL store: SQLite for local use, PostgreSQL for servers (via SQLAlchemy)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    case,
    create_engine,
    delete,
    exists,
    func,
    insert,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.engine import Engine

from owl.models import InvalidSkill, SearchQuery, Skill, SkillSummary, validate_skill
from owl.stores.base import FACET_KINDS, SkillStore

metadata = MetaData()

skills_t = Table(
    "skills",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("author", String(128), nullable=False),
    Column("name", String(64), nullable=False),
    Column("version", String(64), nullable=False),
    Column("description", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("extra_json", Text, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    UniqueConstraint("author", "name", name="uq_skills_author_name"),
    Index("ix_skills_name", "name"),
)

labels_t = Table(
    "skill_labels",
    metadata,
    Column("skill_id", Integer, ForeignKey("skills.id"), primary_key=True),
    Column("kind", String(8), primary_key=True),  # "tag" | "topic"
    Column("value", String(128), primary_key=True),
    Index("ix_skill_labels_value", "kind", "value"),
)

files_t = Table(
    "skill_files",
    metadata,
    Column("skill_id", Integer, ForeignKey("skills.id"), primary_key=True),
    Column("path", String(512), primary_key=True),
    Column("data", LargeBinary, nullable=False),
)


def normalize_db_url(url: str) -> str:
    """Turn a path or a short URL into a SQLAlchemy URL.

    ``postgres://`` and ``postgresql://`` are rewritten to the ``psycopg`` (v3) driver
    that the ``postgres`` extra installs.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if "://" not in url:
        return f"sqlite:///{Path(url).expanduser().resolve()}"
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        path = Path(url[len("sqlite:///") :]).expanduser()
        if str(path) != ":memory:":
            return f"sqlite:///{path.resolve()}"
    return url


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SqlStore(SkillStore):
    """Skills stored in a relational database."""

    def __init__(self, url: str, label: str = "local") -> None:
        self.label = label
        self.url = normalize_db_url(url)
        kwargs: dict[str, Any] = {"future": True}
        if self.url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            path = self.url.removeprefix("sqlite:///")
            if path and path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        else:
            kwargs["pool_pre_ping"] = True
        self.engine: Engine = create_engine(self.url, **kwargs)
        metadata.create_all(self.engine)
        if self.engine.dialect.name == "postgresql":
            self._create_trigram_indexes()

    def _create_trigram_indexes(self) -> None:
        """Speed up substring search on PostgreSQL with pg_trgm (best effort).

        Needs the ``pg_trgm`` extension; if the role may not create it, search still works
        (just with sequential scans).
        """
        statements = ["CREATE EXTENSION IF NOT EXISTS pg_trgm"] + [
            f"CREATE INDEX IF NOT EXISTS ix_skills_{col}_trgm ON skills "
            f"USING gin (lower({col}) gin_trgm_ops)"
            for col in ("name", "description", "content")
        ]
        for statement in statements:
            try:
                with self.engine.begin() as conn:
                    conn.exec_driver_sql(statement)
            except Exception:  # noqa: BLE001, S112 - optional optimisation
                break

    # -- writing ---------------------------------------------------------------------

    def upsert(self, skill: Skill) -> Skill:
        problems = validate_skill(skill)
        if problems:
            raise InvalidSkill("; ".join(problems))
        now = _now()
        with self.engine.begin() as conn:
            row = conn.execute(
                select(skills_t.c.id, skills_t.c.sha256, skills_t.c.created_at).where(
                    skills_t.c.author == skill.author, skills_t.c.name == skill.name
                )
            ).one_or_none()
            if row is not None and row.sha256 == skill.sha256:
                return self._load(conn, row.id)
            values = dict(
                version=skill.version,
                description=skill.description,
                content=skill.content,
                extra_json=json.dumps(skill.extra, ensure_ascii=False, sort_keys=True),
                sha256=skill.sha256,
                updated_at=now,
            )
            if row is None:
                skill_id = conn.execute(
                    insert(skills_t).values(
                        author=skill.author, name=skill.name, created_at=now, **values
                    )
                ).inserted_primary_key[0]  # type: ignore[index]
            else:
                skill_id = row.id
                conn.execute(update(skills_t).where(skills_t.c.id == skill_id).values(**values))
                conn.execute(delete(labels_t).where(labels_t.c.skill_id == skill_id))
                conn.execute(delete(files_t).where(files_t.c.skill_id == skill_id))
            labels = [{"skill_id": skill_id, "kind": "tag", "value": t} for t in skill.tags]
            labels += [{"skill_id": skill_id, "kind": "topic", "value": t} for t in skill.topics]
            if labels:
                conn.execute(insert(labels_t), labels)
            if skill.files:
                conn.execute(
                    insert(files_t),
                    [{"skill_id": skill_id, "path": p, "data": d} for p, d in skill.files.items()],
                )
            return self._load(conn, skill_id)

    def delete(self, author: str, name: str) -> bool:
        with self.engine.begin() as conn:
            skill_id = conn.execute(
                select(skills_t.c.id).where(
                    skills_t.c.author == author.lower(), skills_t.c.name == name
                )
            ).scalar_one_or_none()
            if skill_id is None:
                return False
            conn.execute(delete(labels_t).where(labels_t.c.skill_id == skill_id))
            conn.execute(delete(files_t).where(files_t.c.skill_id == skill_id))
            conn.execute(delete(skills_t).where(skills_t.c.id == skill_id))
            return True

    # -- reading ---------------------------------------------------------------------

    def _load(self, conn: Any, skill_id: int) -> Skill:
        row = conn.execute(select(skills_t).where(skills_t.c.id == skill_id)).one()
        labels = conn.execute(select(labels_t).where(labels_t.c.skill_id == skill_id)).all()
        files = conn.execute(select(files_t).where(files_t.c.skill_id == skill_id)).all()
        return Skill(
            author=row.author,
            name=row.name,
            version=row.version,
            description=row.description,
            tags=[x.value for x in labels if x.kind == "tag"],
            topics=[x.value for x in labels if x.kind == "topic"],
            content=row.content,
            extra=json.loads(row.extra_json),
            files={f.path: bytes(f.data) for f in files},
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def get(self, author: str, name: str) -> Skill | None:
        with self.engine.connect() as conn:
            skill_id = conn.execute(
                select(skills_t.c.id).where(
                    skills_t.c.author == author.lower(), skills_t.c.name == name
                )
            ).scalar_one_or_none()
            return None if skill_id is None else self._load(conn, skill_id)

    @staticmethod
    def _has_label(kind: str, value_clause: Any) -> Any:
        return exists().where(
            labels_t.c.skill_id == skills_t.c.id, labels_t.c.kind == kind, value_clause
        )

    def search(self, query: SearchQuery) -> list[SkillSummary]:
        c = skills_t.c
        conditions = []
        for term in query.terms():
            conditions.append(
                or_(
                    c.name.icontains(term, autoescape=True),
                    c.description.icontains(term, autoescape=True),
                    c.author.icontains(term, autoescape=True),
                    c.content.icontains(term, autoescape=True),
                    exists().where(
                        labels_t.c.skill_id == c.id,
                        labels_t.c.value.icontains(term, autoescape=True),
                    ),
                )
            )
        if query.author:
            conditions.append(c.author == query.author.lower())
        for tag in query.tags:
            conditions.append(self._has_label("tag", labels_t.c.value == tag.lower()))
        for topic in query.topics:
            conditions.append(self._has_label("topic", labels_t.c.value == topic.lower()))
        terms = query.terms()
        relevance: Any
        if terms:
            relevance = case(
                (c.name.icontains(terms[0], autoescape=True), 0),
                (c.description.icontains(terms[0], autoescape=True), 1),
                else_=2,
            )
        else:
            relevance = literal(0)
        stmt = (
            select(c.id, c.author, c.name, c.version, c.description, c.sha256, c.updated_at)
            .where(*conditions)
            .order_by(relevance, c.author, c.name)
            .limit(query.limit)
            .offset(query.offset)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).all()
            labels: dict[int, dict[str, list[str]]] = {}
            if rows:
                for lab in conn.execute(
                    select(labels_t).where(labels_t.c.skill_id.in_([r.id for r in rows]))
                ):
                    labels.setdefault(lab.skill_id, {"tag": [], "topic": []})[lab.kind].append(
                        lab.value
                    )
        return [
            SkillSummary(
                author=r.author,
                name=r.name,
                version=r.version,
                description=r.description,
                tags=sorted(labels.get(r.id, {}).get("tag", [])),
                topics=sorted(labels.get(r.id, {}).get("topic", [])),
                sha256=r.sha256,
                updated_at=r.updated_at,
                source=self.label,
            )
            for r in rows
        ]

    def facets(self, kind: str) -> list[tuple[str, int]]:
        if kind not in FACET_KINDS:
            raise ValueError(f"Unknown facet {kind!r}")
        if kind == "author":
            col = skills_t.c.author
            stmt = select(col, func.count()).group_by(col)
        else:
            col = labels_t.c.value
            stmt = select(col, func.count()).where(labels_t.c.kind == kind).group_by(col)
        with self.engine.connect() as conn:
            rows = [(str(v), int(n)) for v, n in conn.execute(stmt)]
        return sorted(rows, key=lambda r: (-r[1], r[0]))

    def count(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(skills_t)).scalar_one())

    def close(self) -> None:
        self.engine.dispose()
