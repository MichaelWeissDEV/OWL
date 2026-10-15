"""Output formats: built-in adapters and user-defined, declarative templates.

Canonical format: the Agent Skills layout (``<name>/SKILL.md`` + bundled files). Other formats are
*conversions*; lossy ones say so explicitly (a single markdown file cannot carry bundled files,
a prompt/command file is not a skill).

Templates are plain text with ``{{ skill.field }}`` placeholders. They are *declarative*: no code,
no loops, no attribute traversal - unknown fields are errors. Values are escaped for the place they
appear in: YAML frontmatter, JSON, or raw markdown/text.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from owl import paths
from owl.fsutil import replace_dir
from owl.models import NAME_RE, OwlError, Skill
from owl.parsing import SKILL_FILE, split_frontmatter

PLACEHOLDER = re.compile(r"(?<!\\)\{\{\s*([A-Za-z_][\w.]*)\s*(?:\|\s*(\w+)\s*)?\}\}")
FILTERS = ("raw", "yaml", "json", "md", "list")
FIELDS = (
    "name",
    "author",
    "version",
    "description",
    "title",
    "body",
    "tags",
    "topics",
    "source",
    "sha256",
    "content",
    "license",
    "compatibility",
    "ref",
)


class TemplateError(OwlError):
    """A template is malformed or refers to unknown fields."""


@dataclass(frozen=True)
class Builtin:
    name: str
    description: str
    lossy: str  #: what is lost, empty when the conversion is lossless
    extension: str  #: output file extension; ``""`` for directory output


BUILTIN_FORMATS: dict[str, Builtin] = {
    b.name: b
    for b in (
        Builtin(
            "agent-skills", "Agent Skills directory: <name>/SKILL.md plus bundled files", "", ""
        ),
        Builtin(
            "markdown",
            "A single markdown file (the SKILL.md text)",
            "bundled files (scripts, references, assets) are NOT included",
            "md",
        ),
        Builtin(
            "zip", "A zip archive of the complete skill directory (with skill.json)", "", "zip"
        ),
        Builtin(
            "command-md",
            "A prompt/command markdown file (frontmatter 'description' + body). "
            "This is a command, not a skill",
            "name/version/author/tags and bundled files are not representable",
            "md",
        ),
    )
}


# -- template engine ----------------------------------------------------------------------


def _title(skill: Skill) -> str:
    _fm, body, _ = split_frontmatter(skill.content)
    match = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
    return match.group(1).strip() if match else skill.name.replace("-", " ").title()


def skill_fields(skill: Skill) -> dict[str, Any]:
    """The values templates may use (and nothing else)."""
    fm, body, _ = split_frontmatter(skill.content)
    return {
        "name": skill.name,
        "author": skill.author,
        "version": skill.version,
        "description": skill.description,
        "title": _title(skill),
        "body": body.lstrip("\n"),
        "tags": skill.tags,
        "topics": skill.topics,
        "source": str(skill.extra.get("source", "")),
        "sha256": skill.sha256,
        "content": skill.content,
        "license": str(skill.extra.get("license") or fm.get("license") or ""),
        "compatibility": str(fm.get("compatibility") or skill.extra.get("compatibility") or ""),
        "ref": skill.ref,
    }


def _yaml_scalar(value: Any) -> str:
    """A single-line YAML value. Multi-line results fall back to a JSON string (valid YAML), so a
    value can never contain a line that looks like a frontmatter delimiter."""
    dumped = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True, width=10**6).strip()
    dumped = (
        dumped[:-4].rstrip() if dumped.endswith("\n...") else dumped.removesuffix("...").strip()
    )
    return json.dumps(value, ensure_ascii=False) if "\n" in dumped else dumped


def _apply_filter(value: Any, name: str) -> str:
    if name == "raw":
        return ", ".join(value) if isinstance(value, list) else str(value)
    if name == "yaml":
        return _yaml_scalar(value)
    if name == "json":
        return json.dumps(value, ensure_ascii=False)
    if name == "md":
        return re.sub(r"([\\`*_{}\[\]()#+!|<>])", r"\\\1", str(value))
    if name == "list":
        return ", ".join(value) if isinstance(value, list) else str(value)
    raise TemplateError(f"Unknown filter '{name}'. Filters: {', '.join(FILTERS)}")


def _frontmatter_span(template: str) -> tuple[int, int]:
    """Character range of a leading ``---`` block in the template (empty range if none)."""
    if not template.startswith("---"):
        return (0, 0)
    end = template.find("\n---", 3)
    return (0, end + 4) if end != -1 else (0, 0)


def render_template(template: str, skill: Skill, *, extension: str = "md") -> str:
    """Render *template* for *skill*; raises :class:`TemplateError` on any problem."""
    fields = skill_fields(skill)
    fm_start, fm_end = _frontmatter_span(template)

    def lookup(key: str) -> Any:
        parts = key.split(".")
        if parts[0] != "skill" or len(parts) < 2:
            raise TemplateError(f"Unknown placeholder '{key}': use skill.<field>")
        if parts[1] == "meta" and len(parts) == 3:
            return str(skill.extra.get(parts[2], ""))
        if len(parts) != 2 or parts[1] not in fields:
            raise TemplateError(
                f"Unknown field '{key}'. Available: "
                + ", ".join(f"skill.{f}" for f in FIELDS)
                + ", skill.meta.<key>"
            )
        return fields[parts[1]]

    def substitute(match: re.Match[str]) -> str:
        value = lookup(match.group(1))
        filter_name = match.group(2)
        if filter_name is None:
            if extension == "json":
                filter_name = "json"
            elif fm_start <= match.start() < fm_end:
                filter_name = "yaml"  # values inside frontmatter are escaped for YAML
            else:
                filter_name = "raw"
        return _apply_filter(value, filter_name)

    leftover = PLACEHOLDER.sub("", template).replace("\\{{", "")
    if "{{" in leftover or "{%" in leftover:
        raise TemplateError(
            "Unsupported template syntax: only {{ skill.field }} placeholders are allowed "
            "(write \\{{ for a literal '{{')"
        )
    output = PLACEHOLDER.sub(substitute, template).replace("\\{{", "{{")
    _validate_output(output, extension)
    return output


def _validate_output(output: str, extension: str) -> None:
    if extension == "json":
        try:
            json.loads(output)
        except ValueError as exc:
            raise TemplateError(f"The rendered output is not valid JSON: {exc}") from exc
    elif output.startswith("---"):
        fm, _body, problems = split_frontmatter(output)
        if problems:
            raise TemplateError(f"The rendered frontmatter is invalid: {'; '.join(problems)}")


# -- custom format registry ----------------------------------------------------------------


def formats_dir() -> Path:
    return paths.home() / "formats"


def _check_name(name: str) -> None:
    if not NAME_RE.fullmatch(name) or name in BUILTIN_FORMATS:
        raise OwlError(
            f"Invalid format name '{name}': lower-case letters, digits and hyphens, "
            "and not a built-in format name"
        )


def add_format(name: str, source: Path, extension: str | None = None) -> Path:
    """Validate and store a template. The template is test-rendered against a sample skill."""
    _check_name(name)
    text = source.read_text("utf-8")
    ext = (extension or source.suffix.lstrip(".") or "txt").lower()
    if not re.fullmatch(r"[a-z0-9]{1,8}", ext):
        raise OwlError(f"Invalid extension '{ext}'")
    sample = Skill(
        author="sample",
        name="sample-skill",
        version="1.0.0",
        description="A sample: with colon",
        tags=["a", "b"],
        topics=["t"],
        content="---\nname: sample-skill\ndescription: A sample\n---\n# Sample\n\nBody.\n",
    )
    render_template(text, sample, extension=ext)  # raises TemplateError if broken
    target = formats_dir() / f"{name}.tmpl"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, "utf-8")
    (formats_dir() / f"{name}.json").write_text(json.dumps({"extension": ext}), "utf-8")
    return target


def remove_format(name: str) -> None:
    _check_name(name)
    target = formats_dir() / f"{name}.tmpl"
    if not target.exists():
        raise OwlError(f"No custom format '{name}'")
    target.unlink()
    (formats_dir() / f"{name}.json").unlink(missing_ok=True)


def custom_formats() -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    directory = formats_dir()
    if directory.is_dir():
        for tmpl in sorted(directory.glob("*.tmpl")):
            ext = "txt"
            with contextlib.suppress(OSError, ValueError):
                meta = json.loads((directory / f"{tmpl.stem}.json").read_text("utf-8"))
                ext = str(meta.get("extension", "txt"))
            found[tmpl.stem] = {"extension": ext, "path": str(tmpl)}
    return found


# -- exporting -----------------------------------------------------------------------------


@dataclass
class ExportResult:
    paths: list[Path]
    dropped: list[str]  #: bundled files that could not be represented
    lossy: str = ""


def _write_file(path: Path, data: bytes, force: bool) -> None:
    if path.exists() and not force:
        raise OwlError(f"{path} already exists; use --force to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.owl-tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _target_file(out: Path | None, name: str, ext: str, several: bool) -> Path:
    if out is None:
        return Path(f"{name}.{ext}")
    if several or out.is_dir() or out.suffix == "":
        return out / f"{name}.{ext}"
    return out


def export_skill(
    skill: Skill, fmt: str, out: Path | None, *, several: bool = False, force: bool = False
) -> ExportResult:
    """Export *skill* in format *fmt*. Never silently drops bundled files: they are reported."""
    custom = custom_formats()
    if fmt == "agent-skills":
        files = dict(skill.files)
        files[SKILL_FILE] = skill.content.encode("utf-8")
        dest = (out or Path(".")) / skill.name
        if dest.exists() and not force:
            raise OwlError(f"{dest} already exists; use --force to replace it")
        replace_dir(dest, files)
        return ExportResult([dest], [])
    if fmt == "zip":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{skill.name}/{SKILL_FILE}", skill.content)
            zf.writestr(f"{skill.name}/skill.json", json.dumps(skill.meta(), indent=2) + "\n")
            for path, data in sorted(skill.files.items()):
                zf.writestr(f"{skill.name}/{path}", data)
        target = _target_file(out, skill.name, "zip", several)
        _write_file(target, buffer.getvalue(), force)
        return ExportResult([target], [])
    if fmt == "markdown":
        target = _target_file(out, skill.name, "md", several)
        _write_file(target, skill.content.encode("utf-8"), force)
        return ExportResult([target], sorted(skill.files), BUILTIN_FORMATS["markdown"].lossy)
    if fmt == "command-md":
        _fm, body, _ = split_frontmatter(skill.content)
        header = yaml.safe_dump({"description": skill.description}, allow_unicode=True, width=10**6)
        target = _target_file(out, skill.name, "md", several)
        _write_file(target, f"---\n{header}---\n\n{body.lstrip(chr(10))}".encode(), force)
        return ExportResult([target], sorted(skill.files), BUILTIN_FORMATS["command-md"].lossy)
    if fmt in custom:
        ext = custom[fmt]["extension"]
        text = render_template(Path(custom[fmt]["path"]).read_text("utf-8"), skill, extension=ext)
        target = _target_file(out, skill.name, ext, several)
        _write_file(target, text.encode("utf-8"), force)
        return ExportResult([target], sorted(skill.files), "depends on the template")
    known = ", ".join([*BUILTIN_FORMATS, *custom])
    raise OwlError(f"Unknown format '{fmt}'. Known formats: {known}")
