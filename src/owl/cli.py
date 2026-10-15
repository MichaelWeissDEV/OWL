"""The ``owl`` command line interface."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.table import Table

from owl import __version__, gitutil, paths
from owl.completion import (
    complete_author,
    complete_installed,
    complete_ref,
    complete_remote,
    complete_tag,
    complete_target,
    complete_topic,
)
from owl.config import (
    BACKENDS,
    MODES,
    Config,
    Remote,
    StoreConfig,
    expand,
    get_synced,
    load_config,
    save_config,
    set_synced,
    update_completion_cache,
)
from owl.installer import install_skill, list_installed, uninstall_skill
from owl.models import MAX_NAME_LEN, NAME_RE, OwlError, SearchQuery, Skill, SkillSummary
from owl.parsing import load_skills, write_skill_dir
from owl.sources import load_source
from owl.stores import SkillStore, open_remote, open_store
from owl.sync import plan_pull, plan_push
from owl.targets import resolve_targets

app = typer.Typer(
    name="owl",
    help="OWL - manage, search, sync and install skills (SKILL.md) from a local database, "
    "a git repository or one or more OWL servers.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
remote_app = typer.Typer(help="Manage the OWL servers this client talks to.", no_args_is_help=True)
app.add_typer(remote_app, name="remote")

console = Console()
err_console = Console(stderr=True)

RemoteOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--remote",
        "-r",
        help="Use this remote server (repeatable).",
        autocompletion=complete_remote,
    ),
]
LocalOpt = Annotated[bool, typer.Option("--local", help="Use the local store.")]
JsonOpt = Annotated[bool, typer.Option("--json", help="Machine readable JSON output.")]


# -- helpers -----------------------------------------------------------------------------


def _version(value: bool) -> None:
    if value:
        typer.echo(f"owl {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show the version.")
    ] = False,
) -> None:
    """OWL skill manager."""


@contextmanager
def _stores(
    remotes: list[str] | None = None, local: bool = False, everything: bool = False
) -> Iterator[list[SkillStore]]:
    """Open the stores a read command should use, honouring the configured mode."""
    cfg = load_config()
    opened: list[SkillStore] = []
    try:
        if everything:
            opened.append(open_store(cfg.store))
            opened.extend(open_remote(cfg, name) for name in cfg.remotes)
        elif remotes:
            opened.extend(open_remote(cfg, name) for name in remotes)
            if local:
                opened.insert(0, open_store(cfg.store))
        elif not local and cfg.mode == "client" and cfg.default_remote:
            opened.append(open_remote(cfg, cfg.default_remote))
        else:
            opened.append(open_store(cfg.store))
        yield opened
    finally:
        for store in opened:
            store.close()


@contextmanager
def _one(remotes: list[str] | None = None, local: bool = False) -> Iterator[SkillStore]:
    with _stores(remotes, local) as stores:
        if len(stores) != 1:
            raise OwlError("This command works with exactly one store; pass a single --remote")
        yield stores[0]


def _local() -> SkillStore:
    return open_store(load_config().store)


def _pick_remote(cfg: Config, name: str | None) -> str:
    if name:
        cfg.remote(name)
        return name
    if cfg.default_remote:
        return cfg.default_remote
    if len(cfg.remotes) == 1:
        return next(iter(cfg.remotes))
    raise OwlError("No remote selected: pass --remote NAME (see: owl remote list)")


def _summary_table(rows: list[SkillSummary], show_source: bool) -> Table:
    table = Table(show_lines=False, header_style="bold")
    if show_source:
        table.add_column("Source", style="magenta")
    table.add_column("Skill", style="cyan", no_wrap=True)
    table.add_column("Version")
    table.add_column("Description", overflow="fold")
    table.add_column("Tags", style="green")
    for s in rows:
        description = s.description if len(s.description) <= 100 else s.description[:97] + "..."
        cells = [s.ref, s.version, description, ", ".join(s.tags)]
        table.add_row(*([s.source or ""] + cells if show_source else cells))
    return table


def _print_summaries(rows: list[SkillSummary], as_json: bool, show_source: bool = False) -> None:
    if as_json:
        data = [{**s.to_dict(), "source": s.source} for s in rows]
        typer.echo(json.dumps(data, indent=2))
    elif not rows:
        err_console.print("[yellow]No skills found.[/yellow]")
    else:
        console.print(_summary_table(rows, show_source))
        err_console.print(f"[dim]{len(rows)} skill(s)[/dim]")


TargetOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--target",
        "-t",
        help="Tool to install for: claude, opencode, codex, gemini, copilot, cursor, agents, "
        "all or a custom target (repeatable). Default: the configured targets.",
        autocompletion=complete_target,
    ),
]
DirOpt = Annotated[
    str | None, typer.Option("--dir", "-d", help="Install into this exact directory instead.")
]
ProjectOpt = Annotated[
    bool, typer.Option("--project", "-p", help="Project scope (e.g. ./.claude/skills).")
]


def _target_dirs(
    cfg: Config, targets: list[str] | None, directory: str | None, project: bool
) -> list[tuple[str, Path]]:
    return resolve_targets(
        targets,
        directory=directory,
        project=project,
        configured=cfg.targets,
        install_dir=cfg.install_dir,
        custom=cfg.custom_targets,
    )


# -- setup -------------------------------------------------------------------------------


@app.command()
def init(
    mode: Annotated[str, typer.Option(help=f"One of: {', '.join(MODES)}.")] = "standalone",
    backend: Annotated[
        str, typer.Option(help="Where skills are stored: sqlite, postgres or git.")
    ] = "sqlite",
    location: Annotated[
        str | None,
        typer.Option(help="SQLite file, PostgreSQL URL or git working copy directory."),
    ] = None,
    git_url: Annotated[
        str | None, typer.Option(help="git backend: repository to clone / sync with.")
    ] = None,
    url_env: Annotated[
        str | None,
        typer.Option(
            help="postgres: environment variable holding the URL (keeps secrets out of the config)."
        ),
    ] = None,
    author: Annotated[str | None, typer.Option(help="Default author for new skills.")] = None,
    target: Annotated[
        list[str] | None,
        typer.Option("--target", "-t", help="Default install target(s), e.g. opencode."),
    ] = None,
) -> None:
    """Create the configuration and initialise the skill store."""
    if mode not in MODES:
        raise OwlError(f"--mode must be one of: {', '.join(MODES)}")
    if backend not in BACKENDS:
        raise OwlError(f"--backend must be one of: {', '.join(BACKENDS)}")
    cfg = load_config()
    cfg.mode = mode
    cfg.store = StoreConfig(
        backend=backend,
        location=location
        or str(
            paths.default_repo()
            if backend == "git"
            else paths.default_db()
            if backend == "sqlite"
            else ""
        ),
        git_url=git_url,
        url_env=url_env,
    )
    if author:
        cfg.author = author.lower()
    if target:
        resolve_targets(target, custom=cfg.custom_targets)  # validates the names
        cfg.targets = target
    if backend == "git":
        repo = expand(cfg.store.location)
        if not gitutil.is_repo(repo):
            if git_url:
                gitutil.clone(git_url, repo, depth=None)
            else:
                gitutil.init(repo)
        if git_url:
            current = gitutil.remote_url(repo)
            if current and current != git_url:
                raise OwlError(
                    f"{repo} already has origin {current}; refusing to change it to {git_url} "
                    "(use `git remote set-url origin ...` yourself if that is intended)"
                )
            gitutil.set_remote(repo, git_url)
    store = open_store(cfg.store)  # creates tables / validates the connection
    store.close()
    save_config(cfg)
    console.print(
        f"[green]OWL initialised[/green] ({mode}, {backend}) - config: {paths.config_file()}"
    )


@app.command()
def new(
    name: Annotated[str, typer.Argument(help="Skill name (lower-case, hyphens).")],
    directory: Annotated[Path, typer.Option("--dir", help="Parent directory.")] = Path("."),
    description: Annotated[
        str, typer.Option(help="One-line description.")
    ] = "TODO: describe when to use this skill",
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Tag (repeatable).")] = None,
) -> None:
    """Scaffold a new skill directory containing a SKILL.md."""
    if not NAME_RE.fullmatch(name) or len(name) > MAX_NAME_LEN:
        raise OwlError("Skill names use lower-case letters, digits and single hyphens (max 64)")
    cfg = load_config()
    dest = directory / name
    if dest.exists():
        raise OwlError(f"{dest} already exists")
    frontmatter = yaml.safe_dump(
        {
            "name": name,
            "description": description,
            "author": cfg.author,
            "version": "0.1.0",
            "tags": sorted(tag or []),
        },
        sort_keys=False,
        allow_unicode=True,
    )
    content = (
        f"---\n{frontmatter}---\n\n# {name.replace('-', ' ').title()}\n\n"
        "Describe what this skill does and how the agent should use it.\n"
    )
    skill = Skill(author=cfg.author, name=name, content=content, description=description)
    write_skill_dir(skill, dest, with_meta=False)
    console.print(f"Created {dest / 'SKILL.md'}")


@app.command()
def validate(
    source: Annotated[Path, typer.Argument(help="A skill directory or a tree of skills.")] = Path(
        "."
    ),
) -> None:
    """Check SKILL.md files without touching any store."""
    cfg = load_config()
    results = load_skills(source.expanduser(), cfg.author)
    if not results:
        raise OwlError(f"No SKILL.md found below {source}")
    failed = 0
    for r in results:
        if r.valid:
            console.print(f"[green]OK[/green]   {r.skill.ref}  ({r.path})")
            for warning in r.warnings:
                console.print(f"       [yellow]warning:[/yellow] {escape(warning)}")
        else:
            failed += 1
            console.print(f"[red]FAIL[/red] {r.path}")
            for problem in r.problems:
                console.print(f"       - {escape(problem)}")
    raise typer.Exit(1 if failed else 0)


# -- local library -----------------------------------------------------------------------


@app.command()
def add(
    source: Annotated[str, typer.Argument(help="Directory with SKILL.md files, or a git URL.")],
    ref: Annotated[str | None, typer.Option("--ref", help="Branch or tag (git sources).")] = None,
    subdir: Annotated[str | None, typer.Option(help="Only look below this sub-directory.")] = None,
    author: Annotated[str | None, typer.Option(help="Author for skills that declare none.")] = None,
    skill: Annotated[
        list[str] | None, typer.Option("--skill", "-s", help="Only add these skill names.")
    ] = None,
) -> None:
    """Import skills from a directory or git repository into the local store."""
    cfg = load_config()
    added = 0
    with load_source(source, default_author=author or cfg.author, ref=ref, subdir=subdir) as found:
        if not found:
            raise OwlError(f"No SKILL.md found in {source}")
        with _local() as store:
            for result in found:
                if skill and result.skill.name not in skill:
                    continue
                if not result.valid:
                    err_console.print(
                        f"[yellow]skipped[/yellow] {result.path}: {escape('; '.join(result.problems))}"
                    )
                    continue
                stored = store.upsert(result.skill)
                added += 1
                console.print(f"[green]added[/green] {stored.ref} {stored.version}")
            update_completion_cache(store.list())
    if not added:
        raise OwlError("Nothing was added")


@app.command("list")
def list_cmd(
    remote: RemoteOpt = None,
    local: LocalOpt = False,
    author: Annotated[
        str | None, typer.Option("--author", "-a", autocompletion=complete_author)
    ] = None,
    as_json: JsonOpt = False,
) -> None:
    """List all skills."""
    with _stores(remote, local) as stores:
        rows = [s for st in stores for s in st.search(SearchQuery(author=author, limit=100000))]
        update_completion_cache(rows)
    _print_summaries(rows, as_json, show_source=len(stores) > 1)


@app.command()
def search(
    query: Annotated[
        str, typer.Argument(help="Words to look for in name, description, tags, text.")
    ] = "",
    author: Annotated[
        str | None,
        typer.Option("--author", "-a", help="Only this author.", autocompletion=complete_author),
    ] = None,
    tag: Annotated[
        list[str] | None,
        typer.Option(
            "--tag", "-t", help="Require this tag (repeatable).", autocompletion=complete_tag
        ),
    ] = None,
    topic: Annotated[
        list[str] | None,
        typer.Option(
            "--topic", "-T", help="Require this topic (repeatable).", autocompletion=complete_topic
        ),
    ] = None,
    remote: RemoteOpt = None,
    local: LocalOpt = False,
    everything: Annotated[
        bool, typer.Option("--all", help="Search the local store and every configured remote.")
    ] = False,
    limit: Annotated[int, typer.Option(help="Maximum results per store.")] = 50,
    as_json: JsonOpt = False,
) -> None:
    """Search skills by text, author, tags and topics - locally or on remotes."""
    q = SearchQuery(text=query, author=author, tags=tag or [], topics=topic or [], limit=limit)
    rows: list[SkillSummary] = []
    with _stores(remote, local, everything) as stores:
        for store in stores:
            try:
                rows.extend(store.search(q))
            except OwlError as exc:
                if len(stores) == 1:
                    raise
                err_console.print(f"[yellow]warning:[/yellow] {escape(str(exc))}")
    update_completion_cache(rows)
    _print_summaries(rows, as_json, show_source=len(stores) > 1)


@app.command()
def show(
    ref: Annotated[str, typer.Argument(help="author/name or name.", autocompletion=complete_ref)],
    remote: RemoteOpt = None,
    local: LocalOpt = False,
    raw: Annotated[bool, typer.Option("--raw", help="Print the SKILL.md text only.")] = False,
    as_json: JsonOpt = False,
) -> None:
    """Show a skill."""
    with _one(remote, local) as store:
        skill = store.get_ref(ref)
    if raw:
        typer.echo(skill.content, nl=False)
    elif as_json:
        typer.echo(json.dumps(skill.to_dict(), indent=2))
    else:
        console.print(
            f"[bold cyan]{skill.ref}[/bold cyan]  v{skill.version}  [dim]{skill.sha256[:12]}[/dim]"
        )
        console.print(f"{skill.description}")
        console.print(
            f"[green]tags:[/green] {', '.join(skill.tags) or '-'}   "
            f"[green]topics:[/green] {', '.join(skill.topics) or '-'}"
        )
        if skill.files:
            console.print(f"[green]files:[/green] {', '.join(sorted(skill.files))}")
        console.print()
        console.print(Markdown(skill.content))


@app.command()
def remove(
    ref: Annotated[str, typer.Argument(autocompletion=complete_ref)],
    remote: RemoteOpt = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
) -> None:
    """Delete a skill from the local store (or from a remote server with --remote)."""
    with _one(remote, local=not remote) as store:
        author, name = store.resolve(ref)
        if not yes:
            typer.confirm(f"Delete {author}/{name} from {store.label}?", abort=True)
        store.delete(author, name)
    console.print(f"[green]removed[/green] {author}/{name}")


def _facet(kind: str, remote: list[str] | None, local: bool, as_json: bool) -> None:
    with _stores(remote, local) as stores:
        merged: dict[str, int] = {}
        for store in stores:
            for value, count in store.facets(kind):
                merged[value] = merged.get(value, 0) + count
    rows = sorted(merged.items(), key=lambda r: (-r[1], r[0]))
    if as_json:
        typer.echo(json.dumps([{"value": v, "count": n} for v, n in rows], indent=2))
        return
    for value, count in rows:
        typer.echo(f"{value}\t{count}")


@app.command()
def authors(remote: RemoteOpt = None, local: LocalOpt = False, as_json: JsonOpt = False) -> None:
    """List authors with their number of skills."""
    _facet("author", remote, local, as_json)


@app.command()
def tags(remote: RemoteOpt = None, local: LocalOpt = False, as_json: JsonOpt = False) -> None:
    """List tags with their number of skills."""
    _facet("tag", remote, local, as_json)


@app.command()
def topics(remote: RemoteOpt = None, local: LocalOpt = False, as_json: JsonOpt = False) -> None:
    """List topics with their number of skills."""
    _facet("topic", remote, local, as_json)


# -- install -----------------------------------------------------------------------------


@app.command()
def install(
    sources: Annotated[
        list[str] | None,
        typer.Argument(
            help="Skills from the store (author/name or name), git URLs or local directories.",
            autocompletion=complete_ref,
        ),
    ] = None,
    skill: Annotated[
        list[str] | None,
        typer.Option("--skill", "-s", help="Install only these skills from a repository."),
    ] = None,
    everything: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Every skill of a repository - or, without SOURCES, of the selected --remote.",
        ),
    ] = False,
    author: Annotated[
        str | None,
        typer.Option(
            "--author", "-a", help="With --all: only this author.", autocompletion=complete_author
        ),
    ] = None,
    tag: Annotated[
        list[str] | None,
        typer.Option(
            "--tag", help="With --all: only skills with this tag.", autocompletion=complete_tag
        ),
    ] = None,
    topic: Annotated[
        list[str] | None,
        typer.Option("--topic", help="With --all: only this topic.", autocompletion=complete_topic),
    ] = None,
    target: TargetOpt = None,
    directory: DirOpt = None,
    project: ProjectOpt = False,
    ref: Annotated[str | None, typer.Option("--ref", help="Branch or tag (git sources).")] = None,
    subdir: Annotated[str | None, typer.Option(help="Only look below this sub-directory.")] = None,
    remote: RemoteOpt = None,
    local: LocalOpt = False,
    force: Annotated[bool, typer.Option("--force", help="Overwrite foreign directories.")] = False,
) -> None:
    """Install skills for one or more tools (Claude Code, OpenCode, Codex, ...), globally or per project."""
    cfg = load_config()
    destinations = _target_dirs(cfg, target, directory, project)
    chosen: list[tuple[Skill, str]] = []
    if not sources:
        if not everything:
            raise OwlError("Name at least one skill or source, or use --all with --remote")
        with _one(remote, local) as store:
            query = SearchQuery(author=author, tags=tag or [], topics=topic or [], limit=100000)
            for summary in store.search(query):
                chosen.append((store.get_ref(summary.ref), store.label))
        if not chosen:
            raise OwlError("No skills matched")
    for source in sources or []:
        from_path = gitutil.is_git_url(source) or (
            not remote and Path(source).expanduser().exists()
        )
        if from_path:
            with load_source(source, default_author=cfg.author, ref=ref, subdir=subdir) as found:
                valid = [r for r in found if r.valid]
                for r in found:
                    if not r.valid:
                        err_console.print(
                            f"[yellow]skipped[/yellow] {r.path}: {escape('; '.join(r.problems))}"
                        )
                if skill:
                    valid = [r for r in valid if r.skill.name in skill]
                if not valid:
                    raise OwlError(f"No matching valid skills found in {source}")
                if len(valid) > 1 and not (everything or skill):
                    names = ", ".join(r.skill.name for r in valid)
                    raise OwlError(
                        f"{len(valid)} skills found ({names}); choose with --skill or use --all"
                    )
                chosen.extend((r.skill, source) for r in valid)
        else:
            with _one(remote, local) as store:
                chosen.append((store.get_ref(source), store.label))
    for item, origin in chosen:
        for tname, tdir in destinations:
            dest = install_skill(item, tdir, source=origin, force=force)
            console.print(f"[green]installed[/green] {item.ref} -> {dest}  [dim]({tname})[/dim]")


@app.command()
def uninstall(
    names: Annotated[list[str], typer.Argument(autocompletion=complete_installed)],
    target: TargetOpt = None,
    directory: DirOpt = None,
    project: ProjectOpt = False,
    force: Annotated[
        bool, typer.Option("--force", help="Also remove locally modified skills (backup kept).")
    ] = False,
) -> None:
    """Remove skills that were installed by owl."""
    for tname, tdir in _target_dirs(load_config(), target, directory, project):
        for name in names:
            try:
                dest = uninstall_skill(name, tdir, force=force)
            except OwlError as exc:
                err_console.print(f"[yellow]{tname}:[/yellow] {escape(str(exc))}")
                continue
            console.print(f"[green]removed[/green] {dest}")


@app.command()
def installed(
    target: TargetOpt = None,
    directory: DirOpt = None,
    project: ProjectOpt = False,
    as_json: JsonOpt = False,
) -> None:
    """List skills installed by owl."""
    rows = [
        (tname, i)
        for tname, tdir in _target_dirs(load_config(), target, directory, project)
        for i in list_installed(tdir)
    ]
    if as_json:
        typer.echo(json.dumps([{**i.to_dict(), "target": t} for t, i in rows], indent=2))
        return
    if not rows:
        err_console.print("[yellow]Nothing installed by owl in the selected targets[/yellow]")
    for tname, i in rows:
        flag = "\tmodified" if i.modified_files() else ""
        typer.echo(f"{i.ref}\t{i.version}\t{tname}\t{i.path}{flag}")


# -- remotes, pull and push --------------------------------------------------------------


@remote_app.command("add")
def remote_add(
    name: str,
    url: Annotated[str, typer.Argument(help="Base URL, e.g. https://skills.example.com")],
    token: Annotated[
        str | None, typer.Option(help="Access token (stored in the 0600 config).")
    ] = None,
    token_env: Annotated[
        str | None, typer.Option(help="Read the token from this environment variable instead.")
    ] = None,
    default: Annotated[bool, typer.Option("--default", help="Use as the default remote.")] = False,
) -> None:
    """Register an OWL server."""
    cfg = load_config()
    cfg.remotes[name] = Remote(
        url=url.rstrip("/"), token=token, token_env=token_env
    )  # kind: server
    if default or cfg.default_remote is None:
        cfg.default_remote = name
    save_config(cfg)
    console.print(f"[green]added[/green] remote {name} -> {url}")


@remote_app.command("list")
def remote_list() -> None:
    """List configured remotes (servers and registries)."""
    cfg = load_config()
    for name, r in cfg.remotes.items():
        marker = "*" if name == cfg.default_remote else " "
        typer.echo(f"{marker} {name}\t{r.kind}\t{r.url}")


@remote_app.command("remove")
def remote_remove(name: Annotated[str, typer.Argument(autocompletion=complete_remote)]) -> None:
    """Forget a remote."""
    cfg = load_config()
    cfg.remote(name)
    del cfg.remotes[name]
    if cfg.default_remote == name:
        cfg.default_remote = next(iter(cfg.remotes), None)
    save_config(cfg)
    console.print(f"[green]removed[/green] remote {name}")


@remote_app.command("ping")
def remote_ping(
    name: Annotated[str | None, typer.Argument(autocompletion=complete_remote)] = None,
) -> None:
    """Check that a remote is reachable and show its info."""
    cfg = load_config()
    store = open_remote(cfg, _pick_remote(cfg, name))
    try:
        typer.echo(json.dumps(store.info(), indent=2))  # type: ignore[attr-defined]
    finally:
        store.close()


def _sync_refs(source: SkillStore, refs: list[str] | None, everything: bool) -> list[str]:
    if everything:
        return [s.ref for s in source.list()]
    if not refs:
        raise OwlError("Name at least one skill or pass --all")
    return refs


def _transfer(
    direction: str,
    refs: list[str] | None,
    remote_name: str | None,
    everything: bool,
    force: bool,
) -> None:
    cfg = load_config()
    name = _pick_remote(cfg, remote_name)
    if direction == "push" and cfg.remote(name).kind == "registry":
        raise OwlError(
            f"'{name}' is a read-only registry: contribute with a pull request, or "
            "`owl registry publish` into a local checkout"
        )
    local = open_store(cfg.store)
    remote = open_remote(cfg, name)
    conflicts = 0
    try:
        source, dest = (remote, local) if direction == "pull" else (local, remote)
        plan_fn = plan_pull if direction == "pull" else plan_push
        for ref in _sync_refs(source, refs, everything):
            try:
                author, skill_name = source.resolve(ref)
            except OwlError as exc:
                console.print(f"[red]error[/red]   {ref}: {exc}")
                conflicts += 1
                continue
            full = f"{author}/{skill_name}"
            l_skill, r_skill = local.get(author, skill_name), remote.get(author, skill_name)
            plan = plan_fn(
                l_skill.sha256 if l_skill else None,
                r_skill.sha256 if r_skill else None,
                get_synced(name, full),
                force,
            )
            if plan.action == "copy":
                src_skill = r_skill if direction == "pull" else l_skill
                assert src_skill is not None
                dest.upsert(src_skill)
                set_synced(name, full, src_skill.sha256)
                console.print(f"[green]{direction}ed[/green] {full} ({plan.reason})")
            elif plan.action == "noop":
                set_synced(name, full, l_skill.sha256 if l_skill else None)
                console.print(f"[dim]ok[/dim]      {full} ({plan.reason})")
            else:
                console.print(f"[yellow]skipped[/yellow] {full}: {plan.reason}")
                conflicts += plan.reason.startswith("diverged")
        update_completion_cache(local.list())
    finally:
        local.close()
        remote.close()
    if conflicts:
        raise typer.Exit(1)


@app.command()
def pull(
    refs: Annotated[list[str] | None, typer.Argument(autocompletion=complete_ref)] = None,
    remote: Annotated[
        str | None, typer.Option("--remote", "-r", autocompletion=complete_remote)
    ] = None,
    everything: Annotated[
        bool, typer.Option("--all", help="Pull every skill of the remote.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite diverged local skills.")
    ] = False,
) -> None:
    """Copy skills from a remote server into the local store."""
    _transfer("pull", refs, remote, everything, force)


@app.command()
def push(
    refs: Annotated[list[str] | None, typer.Argument(autocompletion=complete_ref)] = None,
    remote: Annotated[
        str | None, typer.Option("--remote", "-r", autocompletion=complete_remote)
    ] = None,
    everything: Annotated[bool, typer.Option("--all", help="Push every local skill.")] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite diverged remote skills.")
    ] = False,
) -> None:
    """Publish skills from the local store to a remote server (needs a write token)."""
    _transfer("push", refs, remote, everything, force)


@app.command()
def sync(
    message: Annotated[str, typer.Option("--message", "-m")] = "owl: update skills",
) -> None:
    """git backend: commit local changes, rebase onto the remote and push."""
    cfg = load_config()
    if cfg.store.backend != "git":
        raise OwlError("sync only works with the git backend (owl init --backend git)")
    repo = expand(cfg.store.location)
    if not gitutil.is_repo(repo):
        raise OwlError(f"{repo} is not a git repository")
    if gitutil.commit_all(repo, message):
        console.print("committed local changes")
    if gitutil.has_remote(repo):
        gitutil.pull(repo)
        if gitutil.has_commits(repo):
            gitutil.push(repo)
        console.print("[green]synced[/green] with origin")
    else:
        console.print("[yellow]no 'origin' remote configured - committed locally only[/yellow]")


# -- server ------------------------------------------------------------------------------


@app.command()
def serve(
    host: Annotated[
        str, typer.Option(help="Interface to bind (default: localhost only).")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8765,
    db_url: Annotated[
        str | None,
        typer.Option(
            envvar="OWL_DB_URL",
            help="Serve this database (SQLite path or postgresql:// URL) instead of the configured store.",
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            envvar="OWL_SERVER_TOKEN", help="Write token. Without it the server is read-only."
        ),
    ] = None,
    private: Annotated[
        bool, typer.Option("--private", help="Require the token for reads as well.")
    ] = False,
) -> None:
    """Run the HTTP server that other OWL clients can pull from and push to."""
    try:
        from owl.server import serve as run_server
    except ImportError as exc:
        raise OwlError("The server needs extra dependencies: pip install 'owl[server]'") from exc
    cfg = load_config()
    if db_url:
        backend = "postgres" if "://" in db_url and not db_url.startswith("sqlite") else "sqlite"
        store_cfg = StoreConfig(backend=backend, location=db_url)
    else:
        store_cfg = cfg.store
    if private and not token:
        raise OwlError("--private needs a token (--token or OWL_SERVER_TOKEN)")
    store = open_store(store_cfg, label="server")
    where = "0.0.0.0" if host in ("0.0.0.0", "::") else host  # noqa: S104
    err_console.print(
        f"owl server on http://{where}:{port}  backend={store_cfg.backend}  "
        f"writes={'token' if token else 'disabled'}  reads={'token' if private else 'open'}"
    )
    if host in ("0.0.0.0", "::") and not token:
        err_console.print("[yellow]warning:[/yellow] listening on all interfaces, read-only")
    try:
        run_server(store, host, port, token, private)
    finally:
        store.close()


from owl import cli_registry, cli_tools  # noqa: E402,F401  (register further commands)


def main() -> None:
    """Console-script entry point: show expected errors without a traceback."""
    try:
        app()
    except OwlError as exc:
        err_console.print(f"[red]error:[/red] {escape(str(exc))}")
        sys.exit(1)
    except (typer.Abort, KeyboardInterrupt):
        sys.exit(130)


if __name__ == "__main__":
    main()
