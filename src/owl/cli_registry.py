"""``owl registry ...``: use, create and maintain skill registries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from owl import registry
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
    store = DirectoryStore(root)
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
        typer.Option("--check", help="Only verify that index.json is current (exit 1 if not)."),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print the index.")] = False,
) -> None:
    """(Re)generate index.json and INDEX.md - normally done by CI."""
    root = _registry_dir(directory)
    if check:
        if not registry.index_is_current(root):
            raise OwlError("index.json is out of date: run `owl registry index`")
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
