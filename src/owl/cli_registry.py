"""``owl registry ...``: use, create and maintain skill registries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape

from owl import gitutil, registry, registry_ops
from owl.cli import app, console, err_console
from owl.completion import complete_remote
from owl.config import Remote, load_config, save_config
from owl.models import NotFound, OwlError, Skill
from owl.sources import load_source
from owl.stores import open_remote
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
    name: Annotated[str, typer.Argument(help="Unique local alias of the registry.")],
    url: Annotated[str, typer.Argument(help="Git URL or local directory of the registry.")],
    ref: Annotated[
        str | None, typer.Option("--ref", help="Branch, tag or commit to follow.")
    ] = None,
    default: Annotated[bool, typer.Option("--default", help="Make it the default remote.")] = False,
    disabled: Annotated[bool, typer.Option("--disabled", help="Add it switched off.")] = False,
    no_auto_update: Annotated[
        bool, typer.Option("--no-auto-update", help="Only refresh on `owl registry update`.")
    ] = False,
    interval: Annotated[
        int, typer.Option(help="Seconds before the cache counts as stale (default 3600).")
    ] = 3600,
    offline: Annotated[
        str, typer.Option(help="cache: use the cache if the network fails; fail: error out.")
    ] = "cache",
    trust: Annotated[
        bool, typer.Option("--trust", help="Mark the registry as trusted (a label).")
    ] = False,
    no_verify: Annotated[
        bool, typer.Option("--no-verify", help="Do not check index entries against skill content.")
    ] = False,
    target: Annotated[
        list[str] | None, typer.Option("--target", "-t", help="Preferred install target(s).")
    ] = None,
) -> None:
    """Register a registry under a unique alias. It is cloned on first use and kept in a cache."""
    cfg = load_config()
    if name in cfg.remotes:
        raise OwlError(f"The alias '{name}' is already used; choose another or remove it first")
    if offline not in ("cache", "fail"):
        raise OwlError("--offline must be cache or fail")
    if target:
        from owl.targets import resolve_targets

        resolve_targets(target, custom=cfg.custom_targets)
    cfg.remotes[name] = Remote(
        url=url,
        kind="registry",
        ref=ref,
        enabled=not disabled,
        auto_update=not no_auto_update,
        update_interval=interval,
        offline=offline,
        verify=not no_verify,
        trusted=trust,
        targets=target,
    )
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
    everything: Annotated[
        bool, typer.Option("--all", help="Update every enabled registry.")
    ] = False,
) -> None:
    """Fetch the latest version of registries now (otherwise they refresh on their interval).

    A failed fetch never damages a working cache.
    """
    cfg = load_config()
    targets = names or [n for n in _registry_names(cfg.remotes) if cfg.remotes[n].enabled]
    if not targets:
        raise NotFound("No registries configured")
    failures = 0
    for name in targets:
        if cfg.remote(name).kind != "registry":
            raise OwlError(f"'{name}' is not a registry")
        store = open_remote(cfg, name)
        assert isinstance(store, RegistryStore)
        try:
            store.update()
            info = store.info()
            console.print(f"[green]updated[/green] {name}: {info['skills']} skills")
            for w in store.warnings:
                err_console.print(f"[yellow]warning:[/yellow] {escape(w)}")
        except OwlError as exc:
            failures += 1
            err_console.print(f"[red]failed[/red] {name}: {escape(str(exc))}")
        finally:
            store.close()
    if failures:
        raise typer.Exit(1)


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
    to: Annotated[
        str | None,
        typer.Option(
            "--to",
            help="A configured registry (a checkout is made if needed).",
            autocompletion=complete_remote,
        ),
    ] = None,
    directory: Annotated[
        Path | None, typer.Option("--dir", "-d", help="A local registry checkout instead of --to.")
    ] = None,
    author: Annotated[str | None, typer.Option(help="Author for skills that declare none.")] = None,
    skill: Annotated[
        list[str] | None, typer.Option("--skill", "-s", help="Only these names.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show the changes, write nothing.")
    ] = False,
    show_diff: Annotated[
        bool, typer.Option("--diff", help="Print the diff of updated skills.")
    ] = False,
    commit: Annotated[bool, typer.Option("--commit", help="Commit the change locally.")] = False,
    message: Annotated[str | None, typer.Option("-m", "--message", help="Commit message.")] = None,
    branch: Annotated[str | None, typer.Option(help="Work on a new branch with this name.")] = None,
    push: Annotated[
        bool, typer.Option("--push", help="Push the branch to origin (explicit; never forced).")
    ] = False,
    pr: Annotated[
        bool,
        typer.Option("--pr", help="Prepare a pull request (implies --branch/--commit/--push)."),
    ] = False,
    allow_dirty: Annotated[
        bool,
        typer.Option(
            "--allow-dirty", help="Publish although the checkout has uncommitted changes."
        ),
    ] = False,
) -> None:
    """Put skills into a registry: validate, show the changes, write, index, and optionally commit.

    By default this only changes the local checkout. Committing, pushing and pull requests happen
    only when you ask for them.
    """
    cfg = load_config()
    root = registry_ops.writable_registry(cfg, to, directory)
    candidates: list[Skill] = []
    for source in sources:
        with load_source(source, default_author=author or cfg.author) as found:
            for result in found:
                if skill and result.skill.name not in skill:
                    continue
                if not result.valid:
                    err_console.print(
                        f"[yellow]skipped[/yellow] {result.path}: {escape('; '.join(result.problems))}"
                    )
                    continue
                candidates.append(result.skill)
    if not candidates:
        raise OwlError("Nothing to publish: no valid skills found")
    items = registry_ops.plan_publish(root, candidates)
    colours = {"add": "green", "update": "cyan", "unchanged": "dim", "collision": "red"}
    for item in items:
        console.print(
            f"[{colours[item.action]}]{item.action:<9}[/] {item.skill.ref} {item.skill.version}"
            + (f"  [dim]{escape(item.note)}[/dim]" if item.note else "")
        )
        if show_diff and item.diff:
            typer.echo(item.diff)
    collisions = [i for i in items if i.action == "collision"]
    if collisions:
        raise OwlError(
            "Name collisions, nothing was written: " + ", ".join(i.skill.name for i in collisions)
        )
    changes = [i for i in items if i.action in ("add", "update")]
    if dry_run:
        return
    if not changes:
        console.print("nothing to publish - the registry already contains these skills")
        return
    is_git = gitutil.is_repo(root)
    if (commit or branch or push or pr) and not is_git:
        raise OwlError(f"{root} is not a git repository; cannot commit or push")
    if is_git and gitutil.is_dirty(root) and not allow_dirty:
        raise OwlError(
            f"{root} has uncommitted changes; commit or stash them first (or use --allow-dirty)"
        )
    if pr:
        commit = push = True
        branch = branch or registry_ops.default_branch_name(items)
    if push or branch:
        commit = True
    if push and not branch and is_git:
        current = gitutil.current_ref(root)
        if current in ("main", "master") and not typer.confirm(
            f"Push directly to '{current}' of origin?", default=False
        ):
            raise OwlError(
                "Not pushed and nothing written (use --branch to publish on a separate branch)"
            )
    if branch:
        gitutil.create_branch(root, branch)
    stored = registry_ops.apply_publish(root, changes)
    for s in stored:
        console.print(f"[green]published[/green] {s.ref} {s.version}")
    if commit:
        gitutil.commit_all(root, message or registry_ops.commit_message(items))
        console.print(f"[green]committed[/green] on {gitutil.current_ref(root)}")
    if push:
        target_branch = gitutil.current_ref(root)
        gitutil.push_branch(root, target_branch)
        console.print(f"[green]pushed[/green] {target_branch} to origin")
    if pr:
        console.print(
            registry_ops.prepare_pull_request(root, gitutil.current_ref(root), execute=True)
        )
    if not commit:
        console.print("changes are local only - review them, then commit (or re-run with --commit)")


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


# -- inspecting and configuring registries ------------------------------------------------


def _cache_info(name: str, remote: Remote) -> dict[str, object]:
    """What is known about a registry without touching the network."""
    import time

    from owl import paths
    from owl.registry import load_index
    from owl.stores.registry import STAMP

    local = not gitutil.is_git_url(remote.url)
    root = Path(remote.url).expanduser() if local else paths.home() / "registries" / name
    info: dict[str, object] = {"cached": False, "location": str(root)}
    if not root.is_dir() or (not local and not gitutil.is_repo(root)):
        return info
    info["cached"] = True
    index = load_index(root)
    info["skills"] = index["count"] if index else None
    info["indexed"] = index is not None
    info["index_generated_at"] = (index or {}).get("generated_at")
    info["commit"] = gitutil.head_commit(root) if gitutil.is_repo(root) else None
    stamp = root / STAMP
    if stamp.exists():
        age = time.time() - stamp.stat().st_mtime
        info["fetched_hours_ago"] = round(age / 3600, 1)
        info["stale"] = age > remote.update_interval
    return info


@registry_app.command("show")
def registry_show(
    name: Annotated[str, typer.Argument(autocompletion=complete_remote)],
    as_json: Annotated[bool, typer.Option("--json", help="Machine readable.")] = False,
) -> None:
    """Show a registry's settings and what its local cache contains (no network access)."""
    cfg = load_config()
    remote = cfg.remote(name)
    if remote.kind != "registry":
        raise OwlError(f"'{name}' is a server, not a registry")
    data = {
        "name": name,
        "url": remote.url,
        "ref": remote.ref,
        "enabled": remote.enabled,
        "default": cfg.default_remote == name,
        "auto_update": remote.auto_update,
        "update_interval": remote.update_interval,
        "offline": remote.offline,
        "verify": remote.verify,
        "trusted": remote.trusted,
        "targets": remote.targets,
        "cache": _cache_info(name, remote),
    }
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    for key, value in data.items():
        if key == "cache":
            for k, v in value.items():  # type: ignore[union-attr]
                typer.echo(f"cache.{k}: {v}")
        else:
            typer.echo(f"{key}: {value}")


REGISTRY_KEYS = {
    "url": str,
    "ref": str,
    "enabled": bool,
    "auto_update": bool,
    "update_interval": int,
    "offline": str,
    "verify": bool,
    "trusted": bool,
    "targets": list,
}


@registry_app.command("set")
def registry_set(
    name: Annotated[str, typer.Argument(autocompletion=complete_remote)],
    key: str,
    value: str,
) -> None:
    """Change a registry setting: url, ref, enabled, auto_update, update_interval, offline, verify,
    trusted or targets (comma separated). An empty value clears ref/targets."""
    cfg = load_config()
    remote = cfg.remote(name)
    if remote.kind != "registry":
        raise OwlError(f"'{name}' is a server; use `owl remote` for servers")
    if key not in REGISTRY_KEYS:
        raise OwlError(f"Unknown setting '{key}'. Settings: {', '.join(REGISTRY_KEYS)}")
    kind = REGISTRY_KEYS[key]
    if kind is bool:
        if value.lower() not in ("true", "false", "yes", "no", "1", "0"):
            raise OwlError(f"{key} must be true or false")
        parsed: object = value.lower() in ("true", "yes", "1")
    elif kind is int:
        if not value.isdigit():
            raise OwlError(f"{key} must be a number of seconds")
        parsed = int(value)
    elif kind is list:
        parsed = [v.strip() for v in value.split(",") if v.strip()] or None
    else:
        parsed = value or None
        if key == "offline" and parsed not in ("cache", "fail"):
            raise OwlError("offline must be cache or fail")
        if key == "url" and not parsed:
            raise OwlError("url cannot be empty")
    setattr(remote, key, parsed)
    save_config(cfg)
    console.print(f"[green]{name}[/green] {key} = {parsed}")


@registry_app.command("doctor")
def registry_doctor(
    name: Annotated[str | None, typer.Argument(autocompletion=complete_remote)] = None,
    network: Annotated[
        bool, typer.Option(help="Check that the remote answers (git ls-remote).")
    ] = True,
) -> None:
    """Diagnose a registry (or all): reachability, cache, index, and index-vs-content integrity."""
    from rich.table import Table

    cfg = load_config()
    names = [name] if name else _registry_names(cfg.remotes)
    if not names:
        raise NotFound("No registries configured")
    table = Table(header_style="bold")
    for column in ("", "Registry", "Check", "Detail"):
        table.add_column(column)
    failed = False

    def row(status: str, reg: str, check: str, detail: str = "") -> None:
        colour = {"OK": "green", "WARN": "yellow", "FAIL": "red"}[status]
        table.add_row(f"[{colour}]{status}[/{colour}]", reg, check, escape(detail))

    for reg in names:
        remote = cfg.remote(reg)
        if remote.kind != "registry":
            raise OwlError(f"'{reg}' is a server, not a registry")
        row("OK" if remote.enabled else "WARN", reg, "enabled", str(remote.enabled))
        if network and gitutil.is_git_url(remote.url):
            try:
                refs = gitutil.ls_remote(remote.url, timeout=20)
                row("OK", reg, "remote reachable", f"{len(refs)} refs")
            except OwlError as exc:
                row("WARN", reg, "remote reachable", str(exc))
        info = _cache_info(reg, remote)
        if not info["cached"]:
            row("WARN", reg, "cache", "not fetched yet - run `owl registry update`")
            continue
        age = info.get("fetched_hours_ago")
        row(
            "WARN" if info.get("stale") else "OK",
            reg,
            "cache",
            f"commit {str(info.get('commit'))[:10]}"
            + (f", fetched {age} h ago" if age is not None else ""),
        )
        store = RegistryStore(
            remote.url,
            reg,
            Path(str(info["location"])) if gitutil.is_git_url(remote.url) else Path("."),
            ref=remote.ref,
            auto_update=False,
            verify=True,
        )
        if gitutil.is_git_url(remote.url):
            store.cache_dir = Path(str(info["location"]))
        try:
            if not info.get("indexed"):
                row(
                    "WARN",
                    reg,
                    "index",
                    "no index.json - the repository is scanned instead (slower)",
                )
            else:
                row(
                    "OK",
                    reg,
                    "index",
                    f"{info['skills']} skills, generated {info['index_generated_at']}",
                )
            problems = []
            for summary in store.list():
                try:
                    store.get(summary.author, summary.name)
                except OwlError as exc:
                    problems.append(f"{summary.ref}: {exc}")
            if problems:
                failed = True
                row(
                    "FAIL",
                    reg,
                    "index matches content",
                    "; ".join(problems[:3])
                    + (f" (+{len(problems) - 3} more)" if len(problems) > 3 else ""),
                )
            else:
                row("OK", reg, "index matches content", "every entry verified")
            checks, warnings = registry.check_registry(Path(str(info["location"])))
            if checks:
                row("WARN", reg, "registry rules", f"{len(checks)} problem(s), e.g. {checks[0]}")
            if warnings:
                row("WARN", reg, "registry warnings", f"{len(warnings)}, e.g. {warnings[0]}")
        except OwlError as exc:
            failed = True
            row("FAIL", reg, "read", str(exc))
        finally:
            store.close()
    console.print(table)
    raise typer.Exit(1 if failed else 0)


# -- creating a registry (optionally also the remote repository) ----------------------------


@registry_app.command("create")
def registry_create(
    name: Annotated[str, typer.Argument(help="Registry (and repository) name.")],
    directory: Annotated[
        Path | None, typer.Option("--dir", help="Where to create it (default ./NAME).")
    ] = None,
    description: Annotated[str, typer.Option(help="One-line description.")] = "",
    provider: Annotated[
        str | None,
        typer.Option(
            help="Also create the remote repository: github, gitlab or gitea (explicit and confirmed)."
        ),
    ] = None,
    owner: Annotated[
        str | None, typer.Option(help="Organisation/namespace (default: your own account).")
    ] = None,
    visibility: Annotated[str, typer.Option(help="private (default) or public.")] = "private",
    base_url: Annotated[
        str | None, typer.Option(help="Self-hosted gitlab/gitea/forgejo URL.")
    ] = None,
    push: Annotated[
        bool, typer.Option("--push", help="Push the initial commit (explicit).")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the typed confirmation.")] = False,
) -> None:
    """Create a local registry; with --provider also the remote repository, after confirmation.

    Nothing is created remotely unless --provider is given, a token is found in the environment
    (e.g. GITHUB_TOKEN) and you confirmed the account, name and visibility shown.
    """
    from owl import providers

    if visibility not in ("private", "public"):
        raise OwlError("--visibility must be private or public")
    if provider and provider not in providers.PROVIDERS:
        raise OwlError(f"--provider must be one of: {', '.join(providers.PROVIDERS)}")
    path = (directory or Path(name)).expanduser()
    token = providers.find_token(provider) if provider else None
    if provider and not token:
        raise OwlError(
            f"No access token for {provider}: set one of {', '.join(providers.TOKEN_ENV[provider])} "
            "in the environment. Nothing was created."
        )
    repo = None
    if provider:
        assert token is not None
        account = providers.whoami(provider, token, base_url)
        target = f"{owner or account}/{name}"
        console.print(
            f"About to create a [bold]{visibility.upper()}[/bold] repository on [bold]{provider}[/bold]:\n"
            f"  account (token owner): {account}\n  repository:            {target}\n"
            f"  API:                   {base_url or providers.DEFAULT_BASE[provider]}"
        )
        if not yes:
            typed = typer.prompt(f"Type the repository name '{target}' to confirm")
            if typed.strip() != target:
                raise OwlError("Confirmation did not match; nothing was created")
    root = registry.init_registry(path, name=name, description=description, commit=False)
    console.print(f"[green]registry created[/green] at {root}")
    if provider:
        assert token is not None
        repo = providers.create_repository(
            provider,
            name,
            token=token,
            owner=owner,
            private=visibility == "private",
            description=description or f"Skill registry {name}",
            base_url=base_url,
        )
        console.print(f"[green]remote repository created[/green] {repo.html_url}")
        gitutil.set_remote(root, repo.clone_url)
        registry.scaffold(
            root,
            name=name,
            description=description or f"Skill registry {name}",
            git_url=repo.clone_url,
            overwrite=True,
        )
    registry.write_index(root)
    gitutil.commit_all(root, "chore: initialise registry")
    if repo and push:
        gitutil.push_branch(root, "main")
        console.print("[green]pushed[/green] main to origin")
    elif repo:
        console.print(f"Publish it when you are ready: git -C {root} push -u origin main")
    else:
        console.print("Next: owl registry publish ./my-skill --dir " + str(root))


@registry_app.command("merge")
def registry_merge(
    source: Annotated[str, typer.Argument(autocompletion=complete_remote)],
    into: Annotated[str, typer.Option("--into", help="Destination registry/library.")],
    skill: Annotated[list[str] | None, typer.Option("--skill", "-s")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    interactive: Annotated[bool, typer.Option("--interactive", "-i")] = False,
    on_conflict: Annotated[str, typer.Option()] = "fail",
    commit: Annotated[bool, typer.Option("--commit")] = False,
    message: Annotated[str | None, typer.Option("-m", "--message")] = None,
    report: Annotated[Path | None, typer.Option()] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Merge one registry into another (same as `owl merge`)."""
    from owl.cli_git import run_merge

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
