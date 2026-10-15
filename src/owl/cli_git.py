"""Git-oriented management commands: ``owl lock`` (reproducible installs)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from owl import audit, lockfile
from owl.cli import RootOpt, TargetOpt, _target_dirs, app, console, err_console
from owl.config import load_config
from owl.installer import install_skill
from owl.models import OwlError

lock_app = typer.Typer(
    help="Pin installed skills to exact revisions (owl.lock).", no_args_is_help=True
)
app.add_typer(lock_app, name="lock")

FileArg = Annotated[
    Path | None, typer.Argument(help="Lock file (default: <project root>/owl.lock).")
]


def _root(project_root: Path | None) -> Path:
    return (project_root or Path.cwd()).expanduser().resolve()


@lock_app.command("create")
def lock_create(
    output: FileArg = None,
    project_root: RootOpt = None,
    target: TargetOpt = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print the lock, write nothing.")
    ] = False,
) -> None:
    """Write owl.lock for the skills installed in a project (revision + content hash of each)."""
    root = _root(project_root)
    lock, warnings = lockfile.build_lock(root, load_config(), target)
    if not lock["skills"]:
        raise OwlError(f"No skills installed by owl in the project at {root}")
    for w in warnings:
        err_console.print(f"[yellow]warning:[/yellow] {w}")
    if dry_run:
        typer.echo(json.dumps(lock, indent=2))
        return
    path = output or lockfile.lock_path(root)
    lockfile.write_lock(path, lock)
    console.print(f"[green]locked[/green] {len(lock['skills'])} skill(s) -> {path}")


@lock_app.command("install")
def lock_install(
    file: FileArg = None,
    project_root: RootOpt = None,
    target: TargetOpt = None,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite foreign or modified directories.")
    ] = False,
) -> None:
    """Install exactly what owl.lock says: fetch the pinned revision, verify the hash, install."""
    root = _root(project_root)
    path = file or lockfile.lock_path(root)
    lock = lockfile.read_lock(path)
    cfg = load_config()
    failures = 0
    for entry in lock["skills"]:
        try:
            skill = lockfile.fetch_locked(entry, cfg)
            names = target or entry.get("targets") or None
            for tname, tdir in _target_dirs(cfg, names, None, True, root):
                dest = install_skill(
                    skill,
                    tdir,
                    source=str(entry["source"].get("registry") or entry["source"].get("url") or ""),
                    force=force,
                    provenance=skill.provenance,
                )
                audit.record_install(
                    skill,
                    target=tname,
                    directory=dest,
                    source="owl.lock",
                    project=True,
                    custom=False,
                    registry=entry["source"].get("registry"),
                    revision=entry["source"].get("commit"),
                )
                console.print(
                    f"[green]installed[/green] {skill.ref} -> {dest}  [dim]({tname}, locked)[/dim]"
                )
        except OwlError as exc:
            failures += 1
            err_console.print(f"[red]failed[/red] {entry['ref']}: {exc}")
            audit.record("lock-install", entry["ref"], "failed", str(exc))
    if failures:
        raise typer.Exit(1)


@lock_app.command("verify")
def lock_verify(
    file: FileArg = None,
    project_root: RootOpt = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine readable result.")] = False,
) -> None:
    """Check the installed skills against owl.lock (exit 1 on any difference)."""
    root = _root(project_root)
    lock = lockfile.read_lock(file or lockfile.lock_path(root))
    rows = lockfile.verify_lock(root, lock, load_config())
    bad = [r for r in rows if r["status"] != "ok"]
    if as_json:
        typer.echo(json.dumps({"ok": not bad, "skills": rows}, indent=2))
    else:
        for r in rows:
            colour = "green" if r["status"] == "ok" else "red"
            console.print(
                f"[{colour}]{r['status']:<8}[/{colour}] {r['ref']}  [dim]({r['target']})[/dim]"
            )
    raise typer.Exit(1 if bad else 0)


# -- merge ----------------------------------------------------------------------------------

import datetime as _dt  # noqa: E402

from owl import gitutil, paths, registry, registry_ops  # noqa: E402
from owl.cli import _local  # noqa: E402
from owl.completion import complete_remote  # noqa: E402
from owl.registry_ops import MergeItem  # noqa: E402
from owl.stores.base import SkillStore  # noqa: E402
from owl.stores.directory import DirectoryStore  # noqa: E402


def _open_store(spec: str, writable: bool) -> tuple[SkillStore, Path | None]:
    """``local``, a configured remote/registry alias, or a registry/library directory."""
    cfg = load_config()
    if spec == "local":
        return _local(), None
    candidate = Path(spec).expanduser()
    if spec in cfg.remotes:
        remote = cfg.remotes[spec]
        if remote.kind == "registry" and writable:
            root = registry_ops.writable_registry(cfg, spec, None)
            return DirectoryStore(root, label=spec), root
        from owl.stores import open_remote

        return open_remote(cfg, spec), None
    if candidate.is_dir():
        root = candidate.resolve()
        return DirectoryStore(root, label=root.name), (root if registry.is_registry(root) else None)
    raise OwlError(f"'{spec}' is neither 'local', a configured remote/registry nor a directory")


def _ask(item: MergeItem, source_label: str, dest_label: str) -> str:
    """Interactive conflict resolution for one skill."""
    assert item.source is not None
    console.print(f"\n[bold red]Conflict:[/bold red] {item.ref}  [dim]({item.kind})[/dim]")
    console.print(f"  {item.note}")
    s, d = item.source, item.dest
    console.print(f"  source ({source_label}): v{s.version}  {s.sha256[:12]}  {s.description[:70]}")
    if d is not None:
        console.print(
            f"  dest   ({dest_label}): v{d.version}  {d.sha256[:12]}  {d.description[:70]}"
        )
    while True:
        choice = (
            typer.prompt(
                "[s]ource wins / [d]estination stays / [r]ename source copy / [c]ompare / s[k]ip / [m]anual / [q]uit",
                default="k",
                show_default=False,
            )
            .strip()
            .lower()[:1]
        )
        if choice == "c":
            typer.echo(
                registry_ops.compare_text(item) or "(no textual difference in SKILL.md/skill.json)"
            )
        elif choice == "s":
            if item.kind == "name-collision":
                err_console.print(
                    "[yellow]The name is taken by another author; choose rename or keep.[/yellow]"
                )
                continue
            return "source"
        elif choice == "d":
            return "dest"
        elif choice == "r":
            chosen = None
            while chosen is None:
                new = typer.prompt(
                    "new name for the source skill (empty = back)", default="", show_default=False
                )
                if not new.strip():
                    break
                try:
                    registry_ops.rename_skill(s, new.strip())
                    chosen = new.strip()
                except OwlError as exc:
                    err_console.print(f"[red]{exc}[/red]")
            if chosen is not None:
                return f"rename:{chosen}"
        elif choice == "k":
            return "skip"
        elif choice == "m":
            return "manual"
        elif choice == "q":
            raise KeyboardInterrupt


def run_merge(
    source_spec: str,
    dest_spec: str,
    *,
    skills: list[str] | None,
    dry_run: bool,
    interactive: bool,
    on_conflict: str,
    commit: bool,
    message: str | None,
    report: Path | None,
    as_json: bool,
) -> None:
    if on_conflict not in ("fail", "source", "dest"):
        raise OwlError("--on-conflict must be fail, source or dest")
    if source_spec == dest_spec:
        raise OwlError("Source and destination are the same")
    src, _src_root = _open_store(source_spec, writable=False)
    dest, dest_root = _open_store(dest_spec, writable=not dry_run)
    try:
        source_skills = [src.get_ref(s.ref) for s in src.list() if not skills or s.name in skills]
        dest_skills = [dest.get_ref(s.ref) for s in dest.list()]
        unique = isinstance(dest, DirectoryStore)
        items = registry_ops.plan_merge(source_skills, dest_skills, unique_names=unique)
        _print_merge_plan(items)
        conflicts = [i for i in items if i.conflict]
        if dry_run:
            if as_json:
                typer.echo(
                    json.dumps(registry_ops.MergeResult(unresolved=conflicts).report(), indent=2)
                )
            return
        try:
            for item in conflicts:
                if interactive:
                    item.resolution = _ask(item, source_spec, dest_spec)
                elif on_conflict == "source" and item.kind != "name-collision":
                    item.resolution = "source"
                elif on_conflict == "dest":
                    item.resolution = "dest"
        except KeyboardInterrupt:
            raise OwlError("Aborted; nothing was merged") from None
        result = registry_ops.apply_merge(items, dest)
    finally:
        src.close()
        dest.close()
    if dest_root is not None:
        registry.write_index(dest_root)
        if commit and gitutil.is_repo(dest_root):
            gitutil.commit_all(dest_root, message or f"chore: merge skills from {source_spec}")
    summary = (
        f"{len(result.copied)} copied, {len(result.replaced)} replaced, {len(result.kept)} kept, "
        f"{len(result.renamed)} renamed, {result.identical} identical, {len(result.unresolved)} unresolved"
    )
    audit.record(
        "merge",
        None,
        "ok" if not result.unresolved else "skipped",
        f"{source_spec} -> {dest_spec}: {summary}",
    )
    if as_json:
        typer.echo(json.dumps(result.report(), indent=2))
    else:
        console.print(summary)
    if result.unresolved:
        path = (
            report
            or paths.home()
            / "merge-reports"
            / f"merge-{_dt.datetime.now(_dt.UTC):%Y%m%dT%H%M%SZ}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result.report(), indent=2), "utf-8")
        err_console.print(
            f"[red]{len(result.unresolved)} conflict(s) left unresolved[/red] - nothing was overwritten. Report: {path}"
        )
        raise typer.Exit(1)


def _print_merge_plan(items: list[MergeItem]) -> None:
    from rich.markup import escape
    from rich.table import Table

    table = Table(header_style="bold")
    for column in ("Result", "Skill", "Note"):
        table.add_column(column)
    colours = {
        "only-source": "green",
        "only-dest": "dim",
        "identical": "dim",
        "content-conflict": "red",
        "metadata-conflict": "yellow",
        "name-collision": "red",
    }
    for item in items:
        table.add_row(f"[{colours[item.kind]}]{item.kind}[/]", item.ref, escape(item.note))
    console.print(table)


@app.command()
def merge(
    source: Annotated[
        str,
        typer.Argument(
            help="local, a remote/registry alias or a directory.", autocompletion=complete_remote
        ),
    ],
    into: Annotated[
        str,
        typer.Option(
            "--into", help="Destination: local, a server/registry alias or a registry directory."
        ),
    ],
    skill: Annotated[
        list[str] | None, typer.Option("--skill", "-s", help="Only these skill names.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show the plan, change nothing.")
    ] = False,
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Resolve conflicts one by one.")
    ] = False,
    on_conflict: Annotated[
        str, typer.Option(help="fail (default: leave conflicts unresolved), source or dest.")
    ] = "fail",
    commit: Annotated[
        bool, typer.Option("--commit", help="Commit the result in a registry checkout.")
    ] = False,
    message: Annotated[str | None, typer.Option("-m", "--message", help="Commit message.")] = None,
    report: Annotated[Path | None, typer.Option(help="Where to write the conflict report.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine readable result.")] = False,
) -> None:
    """Semantically merge the skills of one store into another (never a blind overwrite).

    Classifies every skill (only in source, only in destination, identical, content/metadata
    conflict, name collision), copies the ones that exist only in the source and resolves the rest as
    you decide. Unresolved conflicts are documented in a report and leave the destination untouched.
    This is a skill-level merge, not a git merge.
    """
    run_merge(
        source,
        into,
        skills=skill,
        dry_run=dry_run,
        interactive=interactive,
        on_conflict=on_conflict,
        commit=commit,
        message=message,
        report=report,
        as_json=as_json,
    )


# -- backup ---------------------------------------------------------------------------------

from owl import backup as backup_mod  # noqa: E402

backup_app = typer.Typer(help="Back up and restore OWL's local state.", no_args_is_help=True)
app.add_typer(backup_app, name="backup")


@backup_app.command("create")
def backup_create(
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Target .zip file or directory.")
    ] = None,
    include_registries: Annotated[
        bool, typer.Option("--include-registries", help="Include cached registries.")
    ] = False,
) -> None:
    """Create a backup archive (config, personal DB, catalog, state, formats; optionally registries)."""
    archive = backup_mod.create_backup(
        load_config(), include_registries=include_registries, out=out
    )
    console.print(f"[green]backup created[/green] {archive}")
    err_console.print(
        "[dim]The archive contains config.json (possibly access tokens); it is stored with mode 0600.[/dim]"
    )


@backup_app.command("list")
def backup_list(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """List backups in the default backup directory."""
    rows = backup_mod.list_backups()
    if as_json:
        typer.echo(json.dumps(rows, indent=2))
        return
    for r in rows:
        typer.echo(f"{r['created_at']}\t{r['owl_version']}\t{r['size']} bytes\t{r['path']}")


@backup_app.command("verify")
def backup_verify(archive: Path, as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Check a backup: structure, hashes, SQLite integrity and compatibility (exit 1 if not valid)."""
    result = backup_mod.verify_backup(archive.expanduser())
    if as_json:
        typer.echo(
            json.dumps(
                {"ok": result.ok, "problems": result.problems, "manifest": result.manifest},
                indent=2,
            )
        )
    elif result.ok:
        console.print(
            f"[green]backup is valid[/green] ({len(result.manifest.get('files', []))} files, "
            f"created {result.manifest.get('created_at')} by owl {result.manifest.get('owl_version')})"
        )
        for note in result.manifest.get("notes", []):
            console.print(f"[yellow]note:[/yellow] {note}")
    else:
        for p in result.problems:
            err_console.print(f"[red]problem:[/red] {p}")
    raise typer.Exit(0 if result.ok else 1)


@backup_app.command("restore")
def backup_restore(
    archive: Path,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only list what would be restored.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="No confirmation.")] = False,
) -> None:
    """Restore a backup after verifying it. A backup of the current state is made first."""
    archive = archive.expanduser()
    cfg = load_config()
    if not dry_run and not yes:
        typer.confirm(
            "Restoring replaces your config, databases and caches (a pre-restore backup is kept). Continue?",
            abort=True,
        )
    restored = backup_mod.restore_backup(archive, cfg, dry_run=dry_run)
    verb = "would restore" if dry_run else "restored"
    for path in restored:
        console.print(f"{verb} {path}")
