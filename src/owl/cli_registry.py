"""``owl registry ...``: use, create and maintain skill registries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape

from owl import gitutil, registry
from owl.cli import app, console, err_console
from owl.completion import complete_remote
from owl.config import Remote, load_config, save_config
from owl.models import NotFound, OwlError
from owl.sources import load_source
from owl.stores import open_remote
from owl.stores.directory import DirectoryStore
from owl.stores.registry import RegistryStore

registry_app = typer.Typer(
    help="Use and maintain skill registries (git repositories with an index).",
    no_args_is_help=True,
)
app.add_typer(registry_app, name="registry")


def _registry_names(cfg_remotes: dict[str, Remote]) -> list[str]:
    return [n for n, r in cfg_remotes.items() if r.kind == "registry"]


@registry_app.command("list")
def registry_list() -> None:
    """List the registries this client reads from."""
    cfg = load_config()
    names = _registry_names(cfg.remotes)
    if not names:
        err_console.print(
            "[yellow]No registries configured. Add one: owl registry add NAME URL[/yellow]"
        )
    for name in names:
        r = cfg.remotes[name]
        marker = "*" if name == cfg.default_remote else " "
        typer.echo(f"{marker} {name}\t{r.url}" + (f"\t@{r.ref}" if r.ref else ""))


@registry_app.command("add")
def registry_add(
    name: Annotated[str, typer.Argument(help="Local name of the registry.")],
    url: Annotated[str, typer.Argument(help="Git URL or local directory of the registry.")],
    ref: Annotated[str | None, typer.Option("--ref", help="Branch or tag to follow.")] = None,
    default: Annotated[bool, typer.Option("--default", help="Make it the default remote.")] = False,
) -> None:
    """Register a registry. It is cloned on first use and refreshed hourly."""
    cfg = load_config()
    cfg.remotes[name] = Remote(url=url, kind="registry", ref=ref)
    if default or cfg.default_remote is None:
        cfg.default_remote = name
    save_config(cfg)
    console.print(f"[green]added[/green] registry {name} -> {url}")


@registry_app.command("remove")
def registry_remove(
    name: Annotated[str, typer.Argument(autocompletion=complete_remote)],
) -> None:
    """Forget a registry (its local cache stays until you delete it)."""
    cfg = load_config()
    if cfg.remote(name).kind != "registry":
        raise OwlError(f"'{name}' is a server; use `owl remote remove {name}`")
    del cfg.remotes[name]
    if cfg.default_remote == name:
        cfg.default_remote = next(iter(cfg.remotes), None)
    save_config(cfg)
    console.print(f"[green]removed[/green] registry {name}")


@registry_app.command("update")
def registry_update(
    names: Annotated[list[str] | None, typer.Argument(autocompletion=complete_remote)] = None,
) -> None:
    """Fetch the latest version of registries now (otherwise they refresh hourly)."""
    cfg = load_config()
    targets = names or _registry_names(cfg.remotes)
    if not targets:
        raise NotFound("No registries configured")
    for name in targets:
        if cfg.remote(name).kind != "registry":
            raise OwlError(f"'{name}' is not a registry")
        store = open_remote(cfg, name)
        assert isinstance(store, RegistryStore)
        try:
            store.update()
            info = store.info()
            console.print(f"[green]updated[/green] {name}: {info['skills']} skills")
        finally:
            store.close()


# -- maintaining a registry --------------------------------------------------------------


@registry_app.command("init")
def registry_init(
    directory: Annotated[Path, typer.Argument(help="Where to create the registry.")] = Path("."),
    name: Annotated[
        str | None, typer.Option(help="Registry name (default: directory name).")
    ] = None,
    description: Annotated[str, typer.Option(help="One-line description.")] = "",
    git_url: Annotated[str | None, typer.Option(help="Set this as `origin`.")] = None,
    commit: Annotated[bool, typer.Option(help="Make an initial commit.")] = True,
) -> None:
    """Create a new local registry repository (git, layout, CI workflow, empty index)."""
    path = registry.init_registry(
        directory, name=name, description=description, git_url=git_url, commit=commit
    )
    console.print(f"[green]registry created[/green] at {path}")
    console.print("Next: owl registry publish ./my-skill --dir " + str(path))
    if git_url:
        console.print(f"Then publish it: git -C {path} push -u origin main")


def _registry_dir(directory: Path | None) -> Path:
    path = (directory or Path.cwd()).expanduser().resolve()
    if not registry.is_registry(path):
        raise OwlError(
            f"{path} is not a registry (no {registry.REGISTRY_FILE}); see `owl registry init`"
        )
    return path


@registry_app.command("publish")
def registry_publish(
    sources: Annotated[list[str], typer.Argument(help="Skill directories, trees or git URLs.")],
    directory: Annotated[
        Path | None,
        typer.Option("--dir", "-d", help="The registry checkout (default: current dir)."),
    ] = None,
    author: Annotated[str | None, typer.Option(help="Author for skills that declare none.")] = None,
    skill: Annotated[
        list[str] | None, typer.Option("--skill", "-s", help="Only these names.")
    ] = None,
) -> None:
    """Copy skills into a local registry checkout and update its index."""
    root = _registry_dir(directory)
    cfg = load_config()
    store = DirectoryStore(root, default_author=author or cfg.author)
    added = 0
    for source in sources:
        with load_source(source, default_author=author or cfg.author) as found:
            for result in found:
                if skill and result.skill.name not in skill:
                    continue
                if not result.valid:
                    err_console.print(
                        f"[yellow]skipped[/yellow] {result.path}: {'; '.join(result.problems)}"
                    )
                    continue
                stored = store.upsert(result.skill)
                added += 1
                console.print(f"[green]published[/green] {stored.ref} {stored.version}")
    if not added:
        raise OwlError("Nothing was published")
    index = registry.write_index(root)
    console.print(f"index updated: {index['count']} skills (commit and push to share it)")


@registry_app.command("index")
def registry_index(
    directory: Annotated[Path | None, typer.Argument(help="The registry checkout.")] = None,
    check: Annotated[
        bool,
        typer.Option(
            "--check", help="Only verify that the generated files are current (exit 1 if not)."
        ),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print the index.")] = False,
) -> None:
    """(Re)generate index.json, stats.json, INDEX.md and STATS.md - normally done by CI."""
    root = _registry_dir(directory)
    if check:
        if not registry.index_is_current(root):
            raise OwlError("generated files are out of date: run `owl registry index`")
        console.print("[green]index is current[/green]")
        return
    index = registry.write_index(root)
    if as_json:
        typer.echo(json.dumps(index, indent=2))
    else:
        console.print(
            f"[green]index written[/green]: {index['count']} skills, "
            f"last update {index['generated_at'] or '-'}"
        )


@registry_app.command("check")
def registry_check(
    directory: Annotated[Path | None, typer.Argument(help="The registry checkout.")] = None,
    fresh: Annotated[
        bool, typer.Option("--fresh", help="Also require index.json/stats.json/*.md to be current.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Machine readable result.")] = False,
) -> None:
    """Validate a registry without changing anything (used by CI on pull requests).

    Checks structure, names, frontmatter, paths, symlinks, sizes, collisions and index consistency.
    """
    root = (directory or Path.cwd()).expanduser().resolve()
    problems, warnings = registry.check_registry(root, fresh=fresh)
    if as_json:
        typer.echo(
            json.dumps({"ok": not problems, "problems": problems, "warnings": warnings}, indent=2)
        )
    else:
        for w in warnings:
            err_console.print(f"[yellow]warning:[/yellow] {escape(w)}")
        for p in problems:
            err_console.print(f"[red]error:[/red] {escape(p)}")
        if not problems:
            console.print("[green]registry is valid[/green]")
    raise typer.Exit(1 if problems else 0)


@registry_app.command("migrate")
def registry_migrate(
    directory: Annotated[Path | None, typer.Argument(help="The registry checkout.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show the plan only.")] = False,
) -> None:
    """Convert the old skills/<author>/<name>/ layout to the flat skills/<name>/ layout.

    Aborts without changes on conflicts; safe to run repeatedly.
    """
    root = (directory or Path.cwd()).expanduser().resolve()
    if not (root / "skills").is_dir():
        raise OwlError(f"{root} has no skills/ directory")
    plan = registry.migrate_registry(root, dry_run=dry_run)
    if plan.empty:
        console.print("[green]nothing to migrate[/green] - already using the flat layout")
        return
    verb = "would move" if dry_run else "moved"
    for source, target, author in plan.moves:
        console.print(
            f"{verb} {source.relative_to(root)} -> {target.relative_to(root)}  [dim](author: {author})[/dim]"
        )
    if not dry_run:
        console.print("generated files regenerated; review with `git status` and commit")


@registry_app.command("upgrade")
def registry_upgrade(
    directory: Annotated[Path | None, typer.Argument(help="The registry checkout.")] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite", help="Replace OWL-managed files (workflow, README, CONTRIBUTING)."
        ),
    ] = False,
) -> None:
    """Bring an existing registry up to date: flat layout, scaffold files, regenerated index."""
    root = (directory or Path.cwd()).expanduser().resolve()
    if not registry.is_registry(root):
        raise OwlError(f"{root} is not a registry")
    meta = json.loads((root / registry.REGISTRY_FILE).read_text("utf-8"))
    plan = registry.migrate_registry(root)
    url = gitutil.remote_url(root) if gitutil.is_repo(root) else None
    written = registry.scaffold(
        root,
        name=meta.get("name", root.name),
        description=meta.get("description", ""),
        git_url=url,
        overwrite=overwrite,
    )
    registry.write_index(root)
    console.print(f"migrated {len(plan.moves)} skill(s); wrote: {', '.join(written) or 'nothing'}")
