"""``owl add`` and ``owl scan``: discovering and importing skills (strict, defaults, interactive)."""

from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from owl.cli import _local, app, console, err_console
from owl.config import load_config, update_completion_cache
from owl.discovery import Candidate, discover_source
from owl.importer import DEFAULTS, INTERACTIVE, STRICT, Fields, PlanItem, build_plan
from owl.localdb import LocalDB
from owl.models import OwlError

SourcesArg = Annotated[
    list[str], typer.Argument(help="Directories, git URLs, zip archives or markdown files.")
]


def _collect(
    sources: list[str], author: str, ref: str | None, subdir: str | None, recursive: bool
) -> list[Candidate]:
    found: list[Candidate] = []
    for source in sources:
        with discover_source(
            source, default_author=author, ref=ref, subdir=subdir, recursive=recursive
        ) as candidates:
            found.extend(candidates)
    return found


def _prompter(c: Candidate, fields: Fields, index: int, total: int) -> Fields | str | None:
    """Interactive questions for one incomplete skill; Enter accepts the suggested defaults."""
    console.print(
        f"\n[bold]Incomplete skill {index}/{total}:[/bold] {c.relative} [dim]({c.format})[/dim]"
    )
    for problem in c.problems:
        console.print(f"  [yellow]- {escape(problem)}[/yellow]")
    console.print(
        f"  suggested: name=[cyan]{fields.name}[/cyan] author=[cyan]{fields.author}[/cyan] "
        f"version=[cyan]{fields.version}[/cyan]\n  description: {escape(fields.description)}"
    )
    raw = (
        typer.prompt(
            "[A]ccept defaults / [e]dit values / [s]kip / [all] accept remaining / [q]uit",
            default="a",
            show_default=False,
        )
        .strip()
        .lower()
    )
    if raw == "all":
        return "all"
    choice = raw[:1]
    if choice == "q":
        return None
    if choice == "s":
        return "skip"
    if choice == "e":
        return Fields(
            name=typer.prompt("name", default=fields.name),
            author=typer.prompt("author", default=fields.author),
            version=typer.prompt("version", default=fields.version),
            description=typer.prompt("description", default=fields.description),
            tags=[
                t
                for t in typer.prompt(
                    "tags (comma separated)", default=",".join(fields.tags)
                ).split(",")
                if t.strip()
            ],
            topics=[
                t
                for t in typer.prompt(
                    "topics (comma separated)", default=",".join(fields.topics)
                ).split(",")
                if t.strip()
            ],
            generated=[g for g in fields.generated],
        )
    return fields  # Enter / "a": accept the defaults


def _plan_table(plan: list[PlanItem]) -> Table:
    table = Table(header_style="bold")
    for column in ("Action", "Skill", "Source", "Note"):
        table.add_column(column)
    colours = {
        "add": "green",
        "update": "cyan",
        "unchanged": "dim",
        "skip": "yellow",
        "draft": "magenta",
        "reject": "red",
    }
    for item in plan:
        c = item.candidate
        name = item.skill.ref if item.skill else c.name
        table.add_row(
            f"[{colours[item.action]}]{item.action}[/]", name, c.relative, escape(item.note)
        )
    return table


@app.command()
def add(
    sources: SourcesArg,
    ref: Annotated[str | None, typer.Option("--ref", help="Branch or tag (git sources).")] = None,
    subdir: Annotated[str | None, typer.Option(help="Only look below this sub-directory.")] = None,
    author: Annotated[str | None, typer.Option(help="Author for skills that declare none.")] = None,
    skill: Annotated[
        list[str] | None, typer.Option("--skill", "-s", help="Only add these skill names.")
    ] = None,
    allow_incomplete: Annotated[
        bool,
        typer.Option(
            "--allow-incomplete",
            help="Fill missing metadata with defaults; still-invalid input becomes a local draft.",
        ),
    ] = False,
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Ask about every incomplete skill.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would happen, change nothing.")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="No final confirmation (interactive).")
    ] = False,
    recursive: Annotated[bool, typer.Option(help="Search sub-directories.")] = True,
    as_json: Annotated[bool, typer.Option("--json", help="Machine readable result.")] = False,
) -> None:
    """Import skills from directories, monorepos, git URLs, zip archives or markdown files.

    Strict by default: only valid skills are stored. --allow-incomplete adds defaults for missing
    metadata, --interactive asks about each incomplete skill, --dry-run changes nothing.
    Security rules (paths, symlinks, sizes) are never relaxed.
    """
    cfg = load_config()
    mode = INTERACTIVE if interactive else DEFAULTS if allow_incomplete else STRICT
    candidates = _collect(sources, author or cfg.author, ref, subdir, recursive)
    if not candidates:
        raise OwlError("No skills found in: " + ", ".join(sources))
    store = _local()
    try:
        try:
            plan = build_plan(
                candidates,
                mode=mode,
                default_author=author or cfg.author,
                store=store,
                only=skill,
                prompter=_prompter if interactive else None,
            )
        except KeyboardInterrupt:
            raise OwlError("Aborted; nothing was imported") from None
        if not as_json:
            console.print(_plan_table(plan))
        if dry_run:
            if as_json:
                typer.echo(json.dumps(_result(plan, applied=False), indent=2))
            return
        if interactive and not yes and any(i.generated or i.action == "draft" for i in plan):
            typer.confirm("Apply these changes?", default=True, abort=True)
        outcome = _apply(plan, store)
    finally:
        store.close()
    if as_json:
        typer.echo(json.dumps(_result(plan, applied=True, outcome=outcome), indent=2))
    else:
        console.print(
            f"{outcome['added']} added, {outcome['updated']} updated, {outcome['unchanged']} unchanged, "
            f"{outcome['drafts']} draft(s), {outcome['skipped']} skipped, {outcome['failed']} failed"
        )
    if outcome["failed"] or not (outcome["added"] + outcome["updated"] + outcome["unchanged"]):
        raise typer.Exit(1)


def _apply(plan: list[PlanItem], store) -> dict[str, int]:  # type: ignore[no-untyped-def]
    counts = {"added": 0, "updated": 0, "unchanged": 0, "drafts": 0, "skipped": 0, "failed": 0}
    with LocalDB() as db:
        for item in plan:
            c = item.candidate
            try:
                if item.action in ("add", "update") and item.skill is not None:
                    stored = store.upsert(item.skill)
                    counts["added" if item.action == "add" else "updated"] += 1
                    if c.provenance:
                        db.provenance_set(stored.ref, c.provenance, stored.sha256)
                    db.history_add("add", stored.ref, "ok", f"from {c.source}")
                elif item.action == "unchanged":
                    counts["unchanged"] += 1
                    if c.provenance and item.skill is not None:
                        db.provenance_set(item.skill.ref, c.provenance, item.skill.sha256)
                elif item.action == "draft":
                    content = item.skill.content if item.skill else c.text
                    problems = item.note.split("; ") if item.note else c.problems
                    draft_id = db.draft_add(c.name, f"{c.source}:{c.relative}", content, problems)
                    counts["drafts"] += 1
                    err_console.print(
                        f"[magenta]draft #{draft_id}[/magenta] {c.relative}: kept locally, not a valid skill yet"
                    )
                else:
                    counts["skipped"] += 1
            except OwlError as exc:
                counts["failed"] += 1
                err_console.print(f"[red]failed[/red] {c.relative}: {escape(str(exc))}")
                db.history_add("add", c.name, "failed", str(exc))
    update_completion_cache(store.list())
    return counts


def _result(plan: list[PlanItem], applied: bool, outcome: dict[str, int] | None = None) -> dict:
    return {
        "applied": applied,
        "outcome": outcome,
        "items": [
            {
                "action": i.action,
                "ref": i.skill.ref if i.skill else None,
                "name": i.candidate.name,
                "relative": i.candidate.relative,
                "format": i.candidate.format,
                "status": i.candidate.status,
                "generated": i.generated,
                "note": i.note,
            }
            for i in plan
        ],
    }


@app.command()
def scan(
    sources: Annotated[
        list[str] | None, typer.Argument(help="Paths or URLs; default: registered `owl source`s.")
    ] = None,
    recursive: Annotated[bool, typer.Option(help="Search sub-directories.")] = True,
    as_json: Annotated[bool, typer.Option("--json", help="Machine readable result.")] = False,
) -> None:
    """Discover skills and show their status without importing anything."""
    cfg = load_config()
    targets = list(sources or [])
    if not targets:
        with LocalDB() as db:
            targets = [s["location"] for s in db.sources() if s["kind"] in ("directory", "git")]
    if not targets:
        raise OwlError("Nothing to scan: give paths/URLs or register sources with `owl source add`")
    found = _collect(targets, cfg.author, None, None, recursive)
    if as_json:
        typer.echo(json.dumps([c.to_dict() for c in found], indent=2))
        return
    table = Table(header_style="bold")
    for column in ("Status", "Format", "Name", "Location", "Problems"):
        table.add_column(column)
    colours = {"valid": "green", "incomplete": "yellow", "invalid": "red", "rejected": "red"}
    for c in found:
        table.add_row(
            f"[{colours[c.status]}]{c.status}[/]",
            c.format,
            c.name,
            c.relative,
            escape("; ".join(c.problems)),
        )
    console.print(table)
    console.print(f"[dim]{len(found)} candidate(s)[/dim]")
