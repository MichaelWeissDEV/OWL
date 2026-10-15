"""``owl format``, ``owl export`` and ``owl import``: converting skills between formats."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from owl import formats
from owl.cli import (
    JsonOpt,
    LocalOpt,
    RemoteOpt,
    _one,
    app,
    console,
    err_console,
)
from owl.completion import complete_ref
from owl.models import OwlError, SearchQuery

format_app = typer.Typer(
    help="List, add and inspect output formats (built-in and templates).", no_args_is_help=True
)
app.add_typer(format_app, name="format")


def _complete_format(incomplete: str) -> list[str]:
    try:
        names = [*formats.BUILTIN_FORMATS, *formats.custom_formats()]
        return sorted(n for n in names if n.startswith(incomplete))
    except Exception:  # noqa: BLE001
        return []


@format_app.command("list")
def format_list(as_json: JsonOpt = False) -> None:
    """List the available output formats."""
    rows = [
        {
            "name": b.name,
            "kind": "built-in",
            "extension": b.extension or "(directory)",
            "description": b.description,
            "lossy": b.lossy,
        }
        for b in formats.BUILTIN_FORMATS.values()
    ] + [
        {
            "name": n,
            "kind": "template",
            "extension": m["extension"],
            "description": "user template",
            "lossy": "depends on the template",
        }
        for n, m in formats.custom_formats().items()
    ]
    if as_json:
        typer.echo(json.dumps(rows, indent=2))
        return
    for r in rows:
        note = f"  [lossy: {r['lossy']}]" if r["lossy"] else ""
        typer.echo(f"{r['name']}\t{r['kind']}\t.{r['extension']}\t{r['description']}{note}")


@format_app.command("show")
def format_show(name: Annotated[str, typer.Argument(autocompletion=_complete_format)]) -> None:
    """Show a format's description, or a template's text."""
    if name in formats.BUILTIN_FORMATS:
        b = formats.BUILTIN_FORMATS[name]
        typer.echo(f"{b.name}: {b.description}")
        if b.lossy:
            typer.echo(f"lossy: {b.lossy}")
        return
    custom = formats.custom_formats()
    if name not in custom:
        raise OwlError(f"Unknown format '{name}'")
    typer.echo(Path(custom[name]["path"]).read_text("utf-8"), nl=False)


@format_app.command("add")
def format_add(
    name: str,
    template: Annotated[
        Path, typer.Argument(help="Template file with {{ skill.field }} placeholders.")
    ],
    extension: Annotated[
        str | None, typer.Option(help="Output extension (default: the template's).")
    ] = None,
) -> None:
    """Register a template as an output format. It is test-rendered before it is accepted."""
    stored = formats.add_format(name, template.expanduser(), extension)
    console.print(f"[green]added[/green] format {name} ({stored})")
    console.print(f"Use it with: owl export <skill> --format {name}")


@format_app.command("remove")
def format_remove(name: Annotated[str, typer.Argument(autocompletion=_complete_format)]) -> None:
    """Remove a custom format."""
    formats.remove_format(name)
    console.print(f"[green]removed[/green] format {name}")


@app.command()
def export(
    refs: Annotated[list[str] | None, typer.Argument(autocompletion=complete_ref)] = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Target file or directory (default: current directory)."),
    ] = None,
    everything: Annotated[bool, typer.Option("--all", help="Export every skill.")] = False,
    fmt: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="agent-skills (directory), markdown, zip, command-md or a custom template.",
            autocompletion=_complete_format,
        ),
    ] = "agent-skills",
    layout: Annotated[
        str,
        typer.Option(
            help="agent-skills only: flat (<out>/<name>/) or repo (<out>/skills/<name>/ + skill.json)."
        ),
    ] = "flat",
    force: Annotated[bool, typer.Option("--force", help="Replace existing targets.")] = False,
    remote: RemoteOpt = None,
    local: LocalOpt = False,
    as_json: JsonOpt = False,
) -> None:
    """Export skills as a directory, a markdown file, a zip archive or through a template.

    Formats that cannot carry bundled files say so and list what was left out.
    """
    if layout not in ("flat", "repo"):
        raise OwlError("--layout must be 'flat' or 'repo'")
    results = []
    with _one(remote, local) as store:
        wanted = [s.ref for s in store.search(SearchQuery(limit=100000))] if everything else refs
        if not wanted:
            raise OwlError("Name at least one skill or pass --all")
        several = len(wanted) > 1
        for ref in wanted:
            skill = store.get_ref(ref)
            if fmt == "agent-skills" and layout == "repo":
                from owl.fsutil import replace_dir
                from owl.installer import backup_root

                base = (out or Path("export")) / "skills" / skill.name
                if base.exists() and not force:
                    raise OwlError(f"{base} already exists; use --force (a backup is kept)")
                files = dict(skill.files)
                files["SKILL.md"] = skill.content.encode("utf-8")
                files["skill.json"] = (
                    json.dumps(skill.meta(), indent=2, ensure_ascii=False) + "\n"
                ).encode()
                replace_dir(base, files, keep_backup_in=backup_root() if base.exists() else None)
                result = formats.ExportResult([base], [])
            else:
                result = formats.export_skill(skill, fmt, out, several=several, force=force)
            results.append((skill.ref, result))
    if as_json:
        typer.echo(
            json.dumps(
                [
                    {
                        "ref": ref,
                        "paths": [str(p) for p in r.paths],
                        "not_exported": r.dropped,
                        "lossy": r.lossy,
                    }
                    for ref, r in results
                ],
                indent=2,
            )
        )
        return
    for ref, r in results:
        console.print(f"[green]exported[/green] {ref} -> {', '.join(str(p) for p in r.paths)}")
        if r.dropped:
            err_console.print(
                f"[yellow]warning:[/yellow] {len(r.dropped)} bundled file(s) of {ref} are NOT part of this "
                f"export: {', '.join(r.dropped[:5])}{'...' if len(r.dropped) > 5 else ''}"
            )


@app.command("import")
def import_cmd(
    sources: Annotated[list[str], typer.Argument(help="Files, archives, directories or git URLs.")],
    fmt: Annotated[
        str,
        typer.Option("--format", "-f", help="agent-skills, markdown, command-md or zip."),
    ] = "agent-skills",
    author: Annotated[str | None, typer.Option(help="Author for imported skills.")] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show only what would happen.")
    ] = False,
) -> None:
    """Import skills from other formats; metadata that the format lacks is filled with defaults.

    command-md and markdown files become skills (name from the file name, description from the
    frontmatter or the first paragraph, marked as generated). Custom templates are export-only.
    """
    if fmt in formats.custom_formats():
        raise OwlError(f"'{fmt}' is a custom template and can only be used for export")
    if fmt not in ("agent-skills", "markdown", "command-md", "zip"):
        raise OwlError("--format must be agent-skills, markdown, command-md or zip")
    from owl.cli_import import add as add_command

    add_command(
        sources=sources,
        ref=None,
        subdir=None,
        author=author,
        skill=None,
        allow_incomplete=True,
        interactive=False,
        dry_run=dry_run,
        yes=True,
        recursive=True,
        as_json=False,
    )
