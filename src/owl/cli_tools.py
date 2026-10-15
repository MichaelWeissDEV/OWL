"""Maintenance and inspection commands: config, outdated/update, diff, doctor, stats, export."""

from __future__ import annotations

import difflib
import json
import shutil
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.markup import escape
from rich.table import Table

from owl import __version__, audit, gitutil, paths
from owl.cli import (
    DirOpt,
    JsonOpt,
    LocalOpt,
    ProjectOpt,
    RemoteOpt,
    RootOpt,
    TargetOpt,
    _one,
    _target_dirs,
    app,
    console,
    err_console,
)
from owl.completion import complete_installed, complete_ref, complete_remote
from owl.config import (
    MODES,
    Config,
    expand,
    load_config,
    save_config,
)
from owl.installer import Installed, install_skill, list_installed
from owl.models import NotFound, OwlError, Skill
from owl.sources import load_source
from owl.stores import open_remote, open_store
from owl.targets import all_targets

# -- config ------------------------------------------------------------------------------

config_app = typer.Typer(help="Show and change the configuration.", no_args_is_help=True)
app.add_typer(config_app, name="config")

SETTABLE = {
    "mode": "standalone | client | server",
    "author": "default author for new skills",
    "install_dir": "custom install directory replacing the targets (empty to unset)",
    "targets": "comma separated install targets, e.g. claude,opencode",
    "default_remote": "name of the default remote (or empty to unset)",
}


@config_app.command("show")
def config_show() -> None:
    """Show the active configuration (tokens are hidden)."""
    data = load_config().to_dict()
    for remote in data["remotes"].values():
        if "token" in remote:
            remote["token"] = "***"
    typer.echo(f"# {paths.config_file()}")
    typer.echo(json.dumps(data, indent=2))


@config_app.command("path")
def config_path() -> None:
    """Print the path of the config file."""
    typer.echo(paths.config_file())


@config_app.command("get")
def config_get(key: Annotated[str, typer.Argument(help="mode, author, install_dir, ...")]) -> None:
    """Print one configuration value."""
    data = load_config().to_dict()
    if key not in data:
        raise OwlError(f"Unknown key '{key}'. Known keys: {', '.join(data)}")
    value = data[key]
    typer.echo(value if isinstance(value, str) else json.dumps(value))


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    """Change a setting: mode, author, install_dir or default_remote."""
    cfg = load_config()
    if key not in SETTABLE:
        raise OwlError(f"Cannot set '{key}'. Settable keys: {', '.join(SETTABLE)}")
    if key == "mode":
        if value not in MODES:
            raise OwlError(f"mode must be one of: {', '.join(MODES)}")
        cfg.mode = value
    elif key == "author":
        cfg.author = value.lower()
    elif key == "install_dir":
        cfg.install_dir = value or None
    elif key == "targets":
        names = [v.strip() for v in value.split(",") if v.strip()]
        unknown = set(names) - set(all_targets(cfg.custom_targets))
        if not names or unknown:
            raise OwlError(
                f"Unknown targets: {', '.join(sorted(unknown)) or '(none given)'}. "
                f"Known: {', '.join(sorted(all_targets(cfg.custom_targets)))}"
            )
        cfg.targets = names
    elif key == "default_remote":
        if value:
            cfg.remote(value)
        cfg.default_remote = value or None
    save_config(cfg)
    console.print(f"[green]{key}[/green] = {value}")


# -- outdated / update -------------------------------------------------------------------


def _latest(cfg: Config, item: Installed) -> Skill | None:
    """Fetch the current version of an installed skill from where it came from."""
    source = item.source
    try:
        if source == "local":
            store = open_store(cfg.store)
        elif source in cfg.remotes:
            store = open_remote(cfg, source)
        else:
            with load_source(source, default_author=cfg.author) as found:
                for result in found:
                    if result.valid and result.skill.ref == item.ref:
                        return result.skill
            return None
        try:
            author, name = item.ref.split("/", 1)
            return store.get(author, name)
        finally:
            store.close()
    except OwlError as exc:
        err_console.print(f"[yellow]warning:[/yellow] {item.ref}: {escape(str(exc))}")
        return None


def _check(
    cfg: Config,
    targets: list[str] | None,
    directory: str | None,
    project: bool,
    names: list[str] | None,
    project_root: Path | None = None,
) -> list[tuple[str, Path, Installed, Skill | None]]:
    rows: list[tuple[str, Path, Installed, Skill | None]] = []
    found: set[str] = set()
    for tname, tdir in _target_dirs(cfg, targets, directory, project, project_root):
        for item in list_installed(tdir):
            if names and item.name not in names:
                continue
            found.add(item.name)
            rows.append((tname, tdir, item, _latest(cfg, item)))
    unknown = set(names or []) - found
    if unknown:
        raise NotFound(f"Not installed by owl: {', '.join(sorted(unknown))}")
    return rows


@app.command()
def outdated(
    target: TargetOpt = None,
    directory: DirOpt = None,
    project: ProjectOpt = False,
    project_root: RootOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Show installed skills whose source has a newer version."""
    checked = _check(load_config(), target, directory, project, None, project_root)
    rows = [(t, i, new) for t, _d, i, new in checked if new is not None and new.sha256 != i.sha256]
    if as_json:
        typer.echo(
            json.dumps(
                [
                    {"ref": i.ref, "target": t, "installed": i.version, "available": n.version}
                    for t, i, n in rows
                ],
                indent=2,
            )
        )
    elif not rows:
        console.print("[green]Everything is up to date.[/green]")
    else:
        table = Table(header_style="bold")
        for column in ("Skill", "Target", "Installed", "Available", "Source"):
            table.add_column(column)
        for t, i, new in rows:
            table.add_row(i.ref, t, i.version, new.version, i.source)
        console.print(table)
    raise typer.Exit(1 if rows and not as_json else 0)


@app.command()
def update(
    names: Annotated[list[str] | None, typer.Argument(autocompletion=complete_installed)] = None,
    target: TargetOpt = None,
    directory: DirOpt = None,
    project: ProjectOpt = False,
    project_root: RootOpt = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only show what would change.")
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force", help="Replace locally modified skills (the old copy is backed up)."
        ),
    ] = False,
) -> None:
    """Re-install installed skills whose source has a newer version (all when no name given).

    Skills whose installed files were modified locally are skipped (exit status 1) unless --force.
    """
    changed = 0
    conflicts = 0
    for tname, tdir, item, new in _check(
        load_config(), target, directory, project, names, project_root
    ):
        label = f"{item.ref} [dim]({tname})[/dim]"
        modified = item.modified_files()
        if new is None:
            console.print(f"[yellow]unavailable[/yellow] {label} (source: {item.source})")
        elif new.sha256 == item.sha256:
            console.print(f"[dim]up to date[/dim]  {label}")
        elif modified and not force:
            conflicts += 1
            console.print(
                f"[yellow]modified[/yellow]  {label}: local changes in "
                f"{escape(', '.join(modified[:5]))}; skipped (use --force, a backup is kept)"
            )
        elif dry_run:
            console.print(f"[cyan]would update[/cyan] {label} {item.version} -> {new.version}")
        else:
            dest = install_skill(new, tdir, source=item.source, force=bool(modified))
            audit.record_install(
                new,
                target=tname,
                directory=dest,
                source=item.source,
                project=project,
                custom=bool(directory) or tname == "custom",
            )
            audit.record("update", new.ref, "ok", f"{item.version} -> {new.version}")
            console.print(f"[green]updated[/green] {label} {item.version} -> {new.version}")
            changed += 1
    console.print(f"{changed} skill(s) updated")
    if conflicts:
        raise typer.Exit(1)


# -- diff --------------------------------------------------------------------------------


def _skill_text(skill: Skill | None) -> dict[str, str]:
    if skill is None:
        return {}
    parts = {"SKILL.md": skill.content, "skill.json": json.dumps(skill.meta(), indent=2) + "\n"}
    for path, data in skill.files.items():
        try:
            parts[path] = data.decode("utf-8")
        except UnicodeDecodeError:
            parts[path] = f"<binary {len(data)} bytes>\n"
    return parts


@app.command()
def diff(
    ref: Annotated[str, typer.Argument(autocompletion=complete_ref)],
    remote: Annotated[
        str | None,
        typer.Option(
            "--remote", "-r", help="Compare with this remote.", autocompletion=complete_remote
        ),
    ] = None,
) -> None:
    """Show how the local copy of a skill differs from the one on a remote (exit 1 if different)."""
    cfg = load_config()
    name = remote or cfg.default_remote
    if not name:
        raise OwlError("No remote selected: pass --remote NAME")
    local = open_store(cfg.store)
    other = open_remote(cfg, name)
    try:
        author, skill_name = local.resolve(ref)
        left, right = local.get(author, skill_name), other.get(author, skill_name)
    finally:
        local.close()
        other.close()
    if right is None:
        raise NotFound(f"{author}/{skill_name} does not exist on '{name}'")
    if left is not None and left.sha256 == right.sha256:
        console.print("[green]identical[/green]")
        return
    a, b = _skill_text(left), _skill_text(right)
    for path in sorted(set(a) | set(b)):
        lines = difflib.unified_diff(
            a.get(path, "").splitlines(keepends=True),
            b.get(path, "").splitlines(keepends=True),
            fromfile=f"local/{path}",
            tofile=f"{name}/{path}",
        )
        typer.echo("".join(lines), nl=False)
    raise typer.Exit(1)


# -- stats / doctor / export -------------------------------------------------------------


@app.command()
def stats(remote: RemoteOpt = None, local: LocalOpt = False, as_json: JsonOpt = False) -> None:
    """Show counts for a store: skills, authors, tags, topics and the most used labels."""
    with _one(remote, local) as store:
        summaries = store.list()
        data: dict[str, Any] = {
            "store": store.label,
            "skills": len(summaries),
            "authors": store.facets("author"),
            "tags": store.facets("tag"),
            "topics": store.facets("topic"),
        }
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    console.print(
        f"[bold]{data['store']}[/bold]: {data['skills']} skills, "
        f"{len(data['authors'])} authors, {len(data['tags'])} tags, "
        f"{len(data['topics'])} topics"
    )
    for title, key in (("Top authors", "authors"), ("Top tags", "tags"), ("Top topics", "topics")):
        top = ", ".join(f"{v} ({n})" for v, n in data[key][:10]) or "-"
        console.print(f"[green]{title}:[/green] {top}")


def _check_row(table: Table, status: str, what: str, detail: str = "") -> None:
    color = {"OK": "green", "WARN": "yellow", "FAIL": "red"}[status]
    table.add_row(f"[{color}]{status}[/{color}]", what, escape(detail))


@app.command()
def doctor() -> None:
    """Diagnose the setup: config, store, git, extras, install directory and remotes."""
    table = Table(header_style="bold")
    table.add_column("")
    table.add_column("Check")
    table.add_column("Detail", overflow="fold")
    failed = False
    _check_row(table, "OK", "owl version", __version__)
    cfg_file = paths.config_file()
    if cfg_file.exists():
        _check_row(table, "OK", "config file", str(cfg_file))
    else:
        _check_row(table, "WARN", "config file", f"{cfg_file} missing - run `owl init`")
    try:
        cfg = load_config()
    except OwlError as exc:
        _check_row(table, "FAIL", "config", str(exc))
        console.print(table)
        raise typer.Exit(1) from exc
    _check_row(table, "OK", "mode", cfg.mode)
    try:
        store = open_store(cfg.store)
        try:
            _check_row(table, "OK", f"store ({cfg.store.backend})", f"{store.count()} skills")
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001 - diagnosing means reporting everything
        failed = True
        _check_row(table, "FAIL", f"store ({cfg.store.backend})", str(exc))
    if shutil.which("git"):
        _check_row(table, "OK", "git", "available")
    else:
        _check_row(table, "WARN", "git", "not on PATH (needed for git sources and the git backend)")
    if cfg.store.backend == "git":
        repo = expand(cfg.store.location)
        if gitutil.is_repo(repo):
            _check_row(table, "OK", "git repo", f"{repo} (origin: {gitutil.has_remote(repo)})")
        else:
            failed = True
            _check_row(table, "FAIL", "git repo", f"{repo} is not a repository")
    for module, extra in (("fastapi", "server"), ("psycopg", "postgres")):
        try:
            __import__(module)
            _check_row(table, "OK", f"extra [{extra}]", "installed")
        except ImportError:
            _check_row(
                table, "WARN", f"extra [{extra}]", f"not installed (pip install 'owl[{extra}]')"
            )
    for tname, tdir in _target_dirs(cfg, None, None, False):
        _check_row(table, "OK" if tdir.exists() else "WARN", f"install target {tname}", str(tdir))
    for name in cfg.remotes:
        store = open_remote(cfg, name)
        try:
            info = store.info()  # type: ignore[attr-defined]
            _check_row(
                table, "OK", f"remote {name}", f"{cfg.remotes[name].url} - {info['skills']} skills"
            )
        except OwlError as exc:
            _check_row(table, "WARN", f"remote {name}", str(exc))
        finally:
            store.close()
    console.print(table)
    raise typer.Exit(1 if failed else 0)


# -- targets -----------------------------------------------------------------------------


@app.command()
def targets(as_json: JsonOpt = False) -> None:
    """List the tools OWL can install skills for, with their global and project directories."""
    cfg = load_config()
    known = all_targets(cfg.custom_targets)
    if as_json:
        typer.echo(
            json.dumps(
                [
                    {
                        "name": t.name,
                        "description": t.description,
                        "global": t.global_dir,
                        "project": t.project_dir,
                        "default": t.name in cfg.targets,
                    }
                    for t in known.values()
                ],
                indent=2,
            )
        )
        return
    table = Table(header_style="bold")
    for column in ("", "Target", "Tool", "Global (-g)", "Project (-p)"):
        table.add_column(column)
    for t in known.values():
        table.add_row(
            "*" if t.name in cfg.targets else "", t.name, t.description, t.global_dir, t.project_dir
        )
    console.print(table)
    console.print(
        "[dim]* = default target. Change with: owl config set targets claude,opencode[/dim]"
    )
