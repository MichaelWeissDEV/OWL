"""Commands for the local, personal side of OWL: favorites, collections, notes, metadata, drafts,
history, sources, trust and the local database."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.markup import escape
from rich.table import Table

from owl.cli import (
    JsonOpt,
    LocalOpt,
    RemoteOpt,
    _local,
    _one,
    app,
    console,
    err_console,
)
from owl.completion import complete_ref
from owl.config import load_config
from owl.localdb import LocalDB
from owl.migrations import Migrator
from owl.models import NAME_RE, NotFound, OwlError, Skill, normalize_labels, validate_skill
from owl.parsing import split_frontmatter

RefArg = Annotated[str, typer.Argument(help="author/name or name", autocompletion=complete_ref)]


def _resolve(ref: str, remote: list[str] | None = None, local: bool = False) -> str:
    """Normalise *ref* to ``author/name`` using the selected store."""
    with _one(remote, local) as store:
        author, name = store.resolve(ref)
    return f"{author}/{name}"


# -- favorites ---------------------------------------------------------------------------

favorite_app = typer.Typer(
    help="Mark skills you use a lot (stored locally only).", no_args_is_help=True
)
app.add_typer(favorite_app, name="favorite")


@favorite_app.command("add")
def favorite_add(ref: RefArg, remote: RemoteOpt = None, local: LocalOpt = False) -> None:
    """Add a skill to your favorites."""
    full = _resolve(ref, remote, local)
    with LocalDB() as db:
        added = db.favorite_add(full)
    console.print(f"[green]favorited[/green] {full}" if added else f"{full} is already a favorite")


@favorite_app.command("remove")
def favorite_remove(ref: RefArg) -> None:
    """Remove a skill from your favorites."""
    full = ref if "/" in ref else _resolve(ref)
    with LocalDB() as db:
        if not db.favorite_remove(full):
            raise NotFound(f"{full} is not a favorite")
    console.print(f"[green]removed[/green] {full} from favorites")


@favorite_app.command("list")
def favorite_list(as_json: JsonOpt = False) -> None:
    """List favorites."""
    with LocalDB() as db:
        refs = db.favorites()
    if as_json:
        typer.echo(json.dumps(refs, indent=2))
    else:
        for ref in refs:
            typer.echo(ref)


# -- collections -------------------------------------------------------------------------

collection_app = typer.Typer(
    help="Group skills into your own collections (local).", no_args_is_help=True
)
app.add_typer(collection_app, name="collection")


@collection_app.command("create")
def collection_create(
    name: str, description: Annotated[str, typer.Option(help="What the collection is for.")] = ""
) -> None:
    """Create an empty collection."""
    with LocalDB() as db:
        db.collection_create(name, description)
    console.print(f"[green]created[/green] collection {name}")


@collection_app.command("delete")
def collection_delete(name: str) -> None:
    """Delete a collection (its skills are not touched)."""
    with LocalDB() as db:
        db.collection_delete(name)
    console.print(f"[green]deleted[/green] collection {name}")


@collection_app.command("add")
def collection_add(
    name: str,
    refs: Annotated[list[str], typer.Argument(autocompletion=complete_ref)],
    remote: RemoteOpt = None,
    local: LocalOpt = False,
) -> None:
    """Add skills to a collection."""
    for ref in refs:
        full = _resolve(ref, remote, local)
        with LocalDB() as db:
            added = db.collection_add(name, full)
        console.print(f"[green]added[/green] {full}" if added else f"{full} already in {name}")


@collection_app.command("remove")
def collection_remove(
    name: str, refs: Annotated[list[str], typer.Argument(autocompletion=complete_ref)]
) -> None:
    """Remove skills from a collection."""
    with LocalDB() as db:
        for ref in refs:
            full = ref if "/" in ref else _resolve(ref)
            if not db.collection_remove(name, full):
                err_console.print(f"[yellow]{full} is not in {name}[/yellow]")
            else:
                console.print(f"[green]removed[/green] {full}")


@collection_app.command("list")
def collection_list(as_json: JsonOpt = False) -> None:
    """List collections."""
    with LocalDB() as db:
        rows = db.collections()
    if as_json:
        typer.echo(json.dumps(rows, indent=2))
        return
    for row in rows:
        typer.echo(f"{row['name']}\t{row['skills']} skills\t{row['description']}")


@collection_app.command("show")
def collection_show(name: str, as_json: JsonOpt = False) -> None:
    """List the skills of a collection."""
    with LocalDB() as db:
        members = db.collection_members(name)
    if as_json:
        typer.echo(json.dumps(members, indent=2))
    else:
        for ref in members:
            typer.echo(ref)


# -- notes -------------------------------------------------------------------------------

note_app = typer.Typer(
    help="Private notes about skills (local, never published).", no_args_is_help=True
)
app.add_typer(note_app, name="note")


@note_app.command("set")
def note_set(ref: RefArg, text: str, remote: RemoteOpt = None, local: LocalOpt = False) -> None:
    """Set (replace) the note of a skill."""
    full = _resolve(ref, remote, local)
    with LocalDB() as db:
        db.note_set(full, text)
    console.print(f"[green]note saved[/green] for {full}")


@note_app.command("show")
def note_show(ref: RefArg) -> None:
    """Show the note of a skill."""
    full = ref if "/" in ref else _resolve(ref)
    with LocalDB() as db:
        text = db.note_get(full)
    if text is None:
        raise NotFound(f"No note for {full}")
    typer.echo(text)


@note_app.command("delete")
def note_delete(ref: RefArg) -> None:
    """Delete the note of a skill."""
    full = ref if "/" in ref else _resolve(ref)
    with LocalDB() as db:
        if not db.note_delete(full):
            raise NotFound(f"No note for {full}")
    console.print(f"[green]deleted[/green] note for {full}")


@note_app.command("list")
def note_list(as_json: JsonOpt = False) -> None:
    """List all notes."""
    with LocalDB() as db:
        notes = db.notes()
    if as_json:
        typer.echo(json.dumps(notes, indent=2))
    else:
        for ref, text in notes.items():
            typer.echo(f"{ref}\t{text}")


# -- metadata ----------------------------------------------------------------------------

metadata_app = typer.Typer(help="Show and change skill metadata.", no_args_is_help=True)
app.add_typer(metadata_app, name="metadata")

CORE_KEYS = ("author", "version", "description", "tags", "topics")
LIST_KEYS = ("tags", "topics")


def _local_skill(ref: str) -> tuple[Any, Skill]:
    store = _local()
    try:
        author, name = store.resolve(ref)
        skill = store.get(author, name)
    except OwlError:
        store.close()
        raise
    if skill is None:
        store.close()
        raise NotFound(f"Skill not found: {ref}")
    return store, skill


@metadata_app.command("show")
def metadata_show(ref: RefArg, as_json: JsonOpt = False) -> None:
    """Show a skill's metadata, its local-only overrides, favorite state, collections and note."""
    store, skill = _local_skill(ref)
    store.close()
    with LocalDB() as db:
        extra = {
            "local_overrides": db.overrides(skill.ref),
            "favorite": skill.ref in db.favorites(),
            "collections": db.collections_of(skill.ref),
            "note": db.note_get(skill.ref),
        }
    data = {**skill.meta(), "sha256": skill.sha256, **extra}
    if as_json:
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for key, value in data.items():
        typer.echo(f"{key}: {value}")


@metadata_app.command("set")
def metadata_set(
    ref: RefArg,
    key: Annotated[
        str, typer.Argument(help="author, version, description, tags, topics or any extra key")
    ],
    value: str,
    local: Annotated[
        bool,
        typer.Option("--local", help="Keep it only in your local database (not in the skill)."),
    ] = False,
) -> None:
    """Change one metadata field. SKILL.md itself and the original source stay untouched.

    The change is validated first; an invalid result is refused and nothing changes.
    """
    store, skill = _local_skill(ref)
    try:
        if local:
            with LocalDB() as db:
                db.override_set(skill.ref, key, value)
            console.print(f"[green]local[/green] {skill.ref}: {key} = {value}")
            return
        if key == "name":
            raise OwlError("The name is part of the skill's identity; create a new skill instead")
        fields = {
            f: getattr(skill, f) for f in ("author", "version", "description", "tags", "topics")
        }
        extra = dict(skill.extra)
        if key in LIST_KEYS:
            fields[key] = normalize_labels(value)
        elif key in ("author", "version", "description"):
            fields[key] = value.strip()
        else:
            extra[key] = value
        changed = Skill(
            author=fields["author"],
            name=skill.name,
            version=fields["version"],
            description=fields["description"],
            tags=fields["tags"],
            topics=fields["topics"],
            content=skill.content,
            extra=extra,
            files=skill.files,
        )
        problems = validate_skill(changed)
        if problems:
            raise OwlError(
                "Refusing the change, the skill would become invalid: " + "; ".join(problems)
            )
        if changed.author != skill.author:
            store.delete(skill.author, skill.name)  # identity is author/name: move it
        stored = store.upsert(changed)
        console.print(f"[green]updated[/green] {stored.ref}: {key} = {value}")
    finally:
        store.close()


@metadata_app.command("unset")
def metadata_unset(
    ref: RefArg,
    key: str,
    local: Annotated[bool, typer.Option("--local", help="Remove a local-only override.")] = False,
) -> None:
    """Remove a tags/topics list, an extra key or a local override."""
    store, skill = _local_skill(ref)
    try:
        if local:
            with LocalDB() as db:
                if not db.override_unset(skill.ref, key):
                    raise NotFound(f"No local override '{key}' for {skill.ref}")
            console.print(f"[green]removed[/green] local {key}")
            return
        if key in ("author", "version", "description", "name"):
            raise OwlError(f"'{key}' is required and cannot be removed; use `metadata set`")
        extra = {k: v for k, v in skill.extra.items() if k != key}
        tags = [] if key == "tags" else skill.tags
        topics = [] if key == "topics" else skill.topics
        if key not in LIST_KEYS and key not in skill.extra:
            raise NotFound(f"{skill.ref} has no '{key}'")
        store.upsert(
            Skill(
                author=skill.author,
                name=skill.name,
                version=skill.version,
                description=skill.description,
                tags=tags,
                topics=topics,
                content=skill.content,
                extra=extra,
                files=skill.files,
            )
        )
        console.print(f"[green]removed[/green] {key} from {skill.ref}")
    finally:
        store.close()


# -- edit --------------------------------------------------------------------------------


def _editor() -> list[str]:
    command = (
        os.environ.get("VISUAL")
        or os.environ.get("EDITOR")
        or ("notepad" if os.name == "nt" else "vi")
    )
    return shlex.split(command)


@app.command()
def edit(
    ref: RefArg,
    on_invalid: Annotated[
        str,
        typer.Option(
            "--on-invalid", help="ask, draft (save as draft) or abort when the result is invalid."
        ),
    ] = "ask",
) -> None:
    """Edit a library skill's SKILL.md in $EDITOR. Invalid results never replace the valid skill."""
    from owl.parsing import skill_from_markdown

    if on_invalid not in ("ask", "draft", "abort"):
        raise OwlError("--on-invalid must be ask, draft or abort")
    store, skill = _local_skill(ref)
    try:
        with tempfile.TemporaryDirectory(prefix="owl-edit-") as tmp:
            file = Path(tmp) / "SKILL.md"
            file.write_text(skill.content, "utf-8")
            while True:
                result = subprocess.run([*_editor(), str(file)], check=False)
                if result.returncode != 0:
                    raise OwlError("The editor exited with an error; nothing was changed")
                content = file.read_text("utf-8")
                fm, _body, _ = split_frontmatter(content)
                nested: dict[str, Any] = (
                    fm["metadata"] if isinstance(fm.get("metadata"), dict) else {}
                )
                keep = {
                    k: getattr(skill, k)
                    for k in ("author", "version", "tags", "topics")
                    if k not in fm and k not in nested
                }
                keep.update(skill.extra)
                edited, problems = skill_from_markdown(
                    content,
                    default_author=skill.author,
                    fallback_name=skill.name,
                    files=skill.files,
                    overlay=keep,
                )
                if edited.name != skill.name:
                    problems.append(f"the skill name must stay '{skill.name}'")
                if not problems:
                    break
                err_console.print("[red]The edited skill is invalid:[/red]")
                for p in problems:
                    err_console.print(f"  - {escape(p)}")
                choice = on_invalid
                if choice == "ask":
                    choice = typer.prompt("[e]dit again, save as [d]raft, [a]bort", default="e")[
                        :1
                    ].lower()
                    choice = {"e": "edit", "d": "draft", "a": "abort"}.get(choice, "edit")
                if choice == "edit":
                    continue
                if choice == "draft":
                    with LocalDB() as db:
                        draft_id = db.draft_add(
                            skill.name, f"edit of {skill.ref}", content, problems
                        )
                    raise OwlError(f"Saved as draft #{draft_id}; {skill.ref} is unchanged")
                raise OwlError(f"Aborted; {skill.ref} is unchanged")
        if edited.sha256 == skill.sha256:
            console.print("no changes")
            return
        stored = store.upsert(edited)
        console.print(f"[green]updated[/green] {stored.ref} ({stored.version})")
    finally:
        store.close()


# -- drafts ------------------------------------------------------------------------------

drafts_app = typer.Typer(
    help="Incomplete skills kept locally until they are fixed.", no_args_is_help=True
)
app.add_typer(drafts_app, name="drafts")


@drafts_app.command("list")
def drafts_list(as_json: JsonOpt = False) -> None:
    """List incomplete local drafts and why they are not valid yet."""
    with LocalDB() as db:
        rows = db.drafts()
    if as_json:
        typer.echo(json.dumps(rows, indent=2))
        return
    for d in rows:
        typer.echo(f"#{d['id']}\t{d['name']}\t{d['origin']}\t{'; '.join(d['problems'])}")


@drafts_app.command("show")
def drafts_show(draft_id: int) -> None:
    """Print a draft's content and problems."""
    with LocalDB() as db:
        draft = db.draft_get(draft_id)
    if draft is None:
        raise NotFound(f"No draft #{draft_id}")
    for p in draft["problems"]:
        err_console.print(f"[yellow]problem:[/yellow] {escape(p)}")
    typer.echo(draft["content"], nl=False)


@drafts_app.command("edit")
def drafts_edit(draft_id: int) -> None:
    """Edit a draft in $EDITOR and re-check it."""
    from owl.parsing import skill_from_markdown

    cfg = load_config()
    with LocalDB() as db:
        draft = db.draft_get(draft_id)
        if draft is None:
            raise NotFound(f"No draft #{draft_id}")
        with tempfile.TemporaryDirectory(prefix="owl-draft-") as tmp:
            file = Path(tmp) / "SKILL.md"
            file.write_text(draft["content"], "utf-8")
            if subprocess.run([*_editor(), str(file)], check=False).returncode != 0:
                raise OwlError("The editor exited with an error; the draft is unchanged")
            content = file.read_text("utf-8")
        _skill, problems = skill_from_markdown(
            content, default_author=cfg.author, fallback_name=draft["name"]
        )
        db.draft_update(draft_id, content, problems)
    console.print(
        "[green]draft is now valid - promote it with `owl drafts promote`[/green]"
        if not problems
        else "[yellow]still invalid:[/yellow] " + escape("; ".join(problems))
    )


@drafts_app.command("promote")
def drafts_promote(draft_id: int) -> None:
    """Add a valid draft to the library."""
    from owl.parsing import skill_from_markdown

    cfg = load_config()
    with LocalDB() as db:
        draft = db.draft_get(draft_id)
        if draft is None:
            raise NotFound(f"No draft #{draft_id}")
        skill, problems = skill_from_markdown(
            draft["content"], default_author=cfg.author, fallback_name=draft["name"]
        )
        if problems:
            raise OwlError("The draft is still invalid: " + "; ".join(problems))
        with _local() as store:
            stored = store.upsert(skill)
        db.draft_delete(draft_id)
    console.print(f"[green]promoted[/green] draft #{draft_id} -> {stored.ref}")


@drafts_app.command("discard")
def drafts_discard(draft_id: int) -> None:
    """Delete a draft."""
    with LocalDB() as db:
        if not db.draft_delete(draft_id):
            raise NotFound(f"No draft #{draft_id}")
    console.print(f"[green]discarded[/green] draft #{draft_id}")


# -- history, sources, trust -------------------------------------------------------------


@app.command()
def history(
    limit: Annotated[int, typer.Option(help="How many entries.")] = 30, as_json: JsonOpt = False
) -> None:
    """Show the local log of installs, updates, imports and syncs."""
    with LocalDB() as db:
        rows = db.history(limit)
    if as_json:
        typer.echo(json.dumps(rows, indent=2))
        return
    table = Table(header_style="bold")
    for column in ("When (UTC)", "Operation", "Skill", "Status", "Detail"):
        table.add_column(column)
    for r in rows:
        table.add_row(
            r["at"].replace("T", " ")[:19], r["operation"], r["ref"] or "", r["status"], r["detail"]
        )
    console.print(table)


source_app = typer.Typer(
    help="Extra places OWL scans for skills (local directories, git URLs).", no_args_is_help=True
)
app.add_typer(source_app, name="source")


@source_app.command("add")
def source_add(
    name: str,
    location: str,
    kind: Annotated[str, typer.Option(help="directory or git")] = "directory",
) -> None:
    """Remember a directory or git URL as a named source (`owl scan` re-imports all sources)."""
    if kind not in ("directory", "git"):
        raise OwlError("--kind must be directory or git")
    if not NAME_RE.fullmatch(name):
        raise OwlError("Source names use lower-case letters, digits and hyphens")
    with LocalDB() as db:
        db.source_add(name, kind, location)
    console.print(f"[green]added[/green] source {name}")


@source_app.command("remove")
def source_remove(name: str) -> None:
    """Forget a source."""
    with LocalDB() as db:
        if not db.source_remove(name):
            raise NotFound(f"No source '{name}'")
    console.print(f"[green]removed[/green] source {name}")


@source_app.command("list")
def source_list(as_json: JsonOpt = False) -> None:
    """List all sources: configured remotes/registries and registered directories."""
    cfg = load_config()
    rows: list[dict[str, Any]] = [
        {"name": n, "kind": r.kind, "location": r.url} for n, r in cfg.remotes.items()
    ]
    with LocalDB() as db:
        rows += db.sources()
        trusted = set(db.trusted())
    for r in rows:
        r["trusted"] = r["name"] in trusted or r["location"] in trusted
    if as_json:
        typer.echo(json.dumps(rows, indent=2))
        return
    for r in rows:
        typer.echo(
            f"{r['name']}\t{r['kind']}\t{r['location']}\t{'trusted' if r['trusted'] else ''}"
        )


trust_app = typer.Typer(
    help="Mark sources you trust (a label for you; OWL does not verify publishers).",
    no_args_is_help=True,
)
app.add_typer(trust_app, name="trust")


@trust_app.command("add")
def trust_add(
    source: str, note: Annotated[str, typer.Option(help="Why you trust it.")] = ""
) -> None:
    """Trust a remote/registry name, URL or directory."""
    with LocalDB() as db:
        db.trust_add(source, note)
    console.print(f"[green]trusted[/green] {source}")


@trust_app.command("remove")
def trust_remove(source: str) -> None:
    """Stop trusting a source."""
    with LocalDB() as db:
        if not db.trust_remove(source):
            raise NotFound(f"{source} is not in the trusted list")
    console.print(f"[green]removed[/green] {source}")


@trust_app.command("list")
def trust_list() -> None:
    """List trusted sources."""
    with LocalDB() as db:
        for s in db.trusted():
            typer.echo(s)


# -- database ----------------------------------------------------------------------------

db_app = typer.Typer(help="Inspect and migrate OWL's SQLite databases.", no_args_is_help=True)
app.add_typer(db_app, name="db")


def _migrators() -> list[tuple[str, Migrator, Any]]:
    from owl.stores.sql import CATALOG_MIGRATIONS, SqlStore

    out: list[tuple[str, Migrator, Any]] = []
    cfg = load_config().store
    if cfg.backend == "sqlite":
        from sqlalchemy import create_engine

        engine = create_engine(f"sqlite:///{Path(cfg.location).expanduser()}")
        out.append(
            (
                "catalog",
                Migrator(engine, "catalog", CATALOG_MIGRATIONS, legacy_table="skills"),
                engine,
            )
        )
    del SqlStore
    return out


@db_app.command("status")
def db_status(as_json: JsonOpt = False) -> None:
    """Show schema versions of the catalog (SQLite backend) and the local user database."""
    from owl import paths

    rows: list[dict[str, Any]] = []
    for scope, migrator, _engine in _migrators():
        if Path(migrator.engine.url.database or "").exists():
            rows.append({**migrator.status(), "file": migrator.engine.url.database, "scope": scope})
    with LocalDB() as db:
        rows.append({**db.migrator.status(), "file": str(db.path)})
    if as_json:
        typer.echo(json.dumps(rows, indent=2))
        return
    for r in rows:
        pending = f", pending: {', '.join(r['pending'])}" if r["pending"] else ""
        typer.echo(f"{r['scope']}: v{r['current']} of v{r['latest']}  {r['file']}{pending}")
    del paths


@db_app.command("migrate")
def db_migrate() -> None:
    """Apply pending migrations (a backup of the SQLite file is made first)."""
    done = 0
    for scope, migrator, _engine in _migrators():
        applied = migrator.upgrade()
        done += len(applied)
        for m in applied:
            console.print(f"[green]{scope}[/green] applied {m.version}: {m.name}")
    LocalDB().close()  # creates / migrates the local database
    console.print("up to date" if not done else f"{done} migration(s) applied")


@db_app.command("backup")
def db_backup() -> None:
    """Copy the SQLite databases into $OWL_HOME/backups/db."""
    made = []
    for _scope, migrator, _engine in _migrators():
        if Path(migrator.engine.url.database or "").exists():
            made.append(migrator.backup(migrator.current()))
    with LocalDB() as db:
        made.append(db.migrator.backup(db.migrator.current()))
    for path in made:
        console.print(f"[green]backup[/green] {path}")
