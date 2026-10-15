"""Skill registries: git repositories with a machine- and human-readable index.

A registry is a git repository with a *flat* layout - the author is metadata, not a directory::

    registry.json            marker + name/description
    index.json               generated: every skill with version, tags, hashes, last update
    stats.json               generated: aggregated statistics
    INDEX.md, STATS.md       generated: the same data, quick to read
    skills/<name>/           SKILL.md, skill.json, bundled files
    .github/workflows/registry.yml   CI that validates PRs and keeps the generated files current

Registries are passive data: nothing from a skill is ever executed while indexing.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from owl import gitutil
from owl.models import MAX_TOTAL_BYTES, OwlError, Skill
from owl.parsing import META_FILE, SKILL_FILE, find_skill_dirs, load_skill_dir, split_frontmatter

REGISTRY_FILE = "registry.json"
INDEX_FILE = "index.json"
STATS_FILE = "stats.json"
INDEX_MD = "INDEX.md"
STATS_MD = "STATS.md"
GENERATED_FILES = (INDEX_FILE, STATS_FILE, INDEX_MD, STATS_MD)
INDEX_FORMAT = 2
READABLE_FORMATS = (1, 2)
MAX_FILE_BYTES = 5 * 1024 * 1024
OWL_REPO = "https://github.com/MichaelWeissDEV/OWL"
OWL_RAW = "https://raw.githubusercontent.com/MichaelWeissDEV/OWL/master"

WORKFLOW = f"""\
# Managed by OWL (`owl registry init` / `owl registry upgrade`).
name: registry

on:
  pull_request:
    paths: ["skills/**", "registry.json"]
  push:
    branches: [main]
    paths: ["skills/**", "registry.json"]
  workflow_dispatch:

# No permissions by default; the jobs below ask for exactly what they need.
permissions: {{}}

concurrency:
  group: registry-${{{{ github.workflow }}}}-${{{{ github.ref }}}}
  cancel-in-progress: ${{{{ github.event_name == 'pull_request' }}}}

jobs:
  validate:
    name: validate skills
    runs-on: ubuntu-latest
    permissions:
      contents: read          # pull requests (even from forks) never get write access
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: astral-sh/setup-uv@v5
      - name: Install OWL
        run: uv tool install "git+{OWL_REPO}"
      - name: Check structure, names, frontmatter, paths, sizes and index consistency
        run: owl registry check .
        # Only reads files. Skill scripts are never executed.

  index:
    name: update index
    needs: validate
    if: github.event_name != 'pull_request'
    runs-on: ubuntu-latest
    permissions:
      contents: write         # only this job may push, and only after validation succeeded
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0      # full history: update times and revisions come from git
      - uses: astral-sh/setup-uv@v5
      - name: Install OWL
        run: uv tool install "git+{OWL_REPO}"
      - name: Regenerate index.json, stats.json, INDEX.md and STATS.md
        run: owl registry index .
      - name: Commit the generated files (only if they changed)
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add index.json stats.json INDEX.md STATS.md
          if git diff --cached --quiet; then
            echo "generated files are up to date"
          else
            git commit -m "chore: update registry index [skip ci]"
            git push
          fi
"""

README_TEMPLATE = """\
<p align="center">
  <img src="assets/owl.png" alt="OWL" width="120">
</p>

<h1 align="center">{name}</h1>

<p align="center">{description}</p>

<p align="center">
{badges}
</p>

> **Alpha:** this registry is served by [OWL]({owl_repo}), which is under active development; the
> registry layout and index format may still change.

A skill registry for [OWL]({owl_repo}). Browse [`INDEX.md`](INDEX.md) for a quick overview,
[`STATS.md`](STATS.md) for statistics, or read [`index.json`](index.json) from tools.

## Use it

```console
$ owl registry add {name} {url_hint}
$ owl search <words> -r {name}
$ owl install <skill> -r {name}                    # one skill
$ owl install --all -r {name}                      # everything
$ owl install --all -r {name} --target opencode    # for OpenCode instead of Claude Code
```

## Contribute

Add a skill directory `skills/<name>/` with a `SKILL.md` (`name` and `description` frontmatter) and
open a pull request - see [`CONTRIBUTING.md`](CONTRIBUTING.md). CI validates every pull request;
after a merge CI regenerates `index.json`, `stats.json`, `INDEX.md` and `STATS.md`. Never edit
the generated files by hand.

Locally: `owl registry publish ./my-skill --dir .` copies a skill in and updates the index.
"""

CONTRIBUTING_TEMPLATE = """\
# Contributing to {name}

Thank you for adding a skill! A skill is a directory below `skills/`:

```text
skills/<name>/
  SKILL.md        required: YAML frontmatter + instructions
  skill.json      optional: extra metadata (author, version, tags, topics, license, ...)
  scripts/ references/ assets/    optional bundled files
```

## Rules

- The directory name **must equal** the skill `name` (lower case, digits, single hyphens, at most
  64 characters). There is no author directory - put the author into the metadata
  (`author:` in the frontmatter or in `skill.json`).
- `SKILL.md` needs `name` and `description` (at most 1024 characters) in its frontmatter.
- Names are unique in this registry. If a name is taken, choose another one.
- No symlinks, no absolute or `..` paths, files at most 5 MiB, a skill at most 20 MiB.
- Skills are data: CI never executes anything from a skill, and neither should the registry.

## Workflow

1. Fork and create a branch.
2. `owl registry publish ./my-skill --dir .` (or copy the directory by hand).
3. `owl registry check .` - fix everything it reports.
4. Open a pull request. CI repeats the check with read-only permissions.
5. After the merge CI updates `index.json`, `stats.json`, `INDEX.md` and `STATS.md`.
   Do not edit these files.
"""

GITIGNORE = ".DS_Store\n__pycache__/\n"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def is_registry(path: Path) -> bool:
    return (path / REGISTRY_FILE).is_file()


def _github_slug(git_url: str | None) -> str | None:
    if not git_url:
        return None
    match = re.search(r"github\.com[:/]+([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", git_url)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def _badges(name: str, slug: str | None) -> str:
    badges = [
        '  <img alt="Development status: alpha" '
        'src="https://img.shields.io/badge/status-alpha-orange">',
        f'  <a href="{OWL_REPO}"><img alt="Served by OWL" '
        'src="https://img.shields.io/badge/served%20by-OWL-8b5a2b"></a>',
    ]
    if slug:
        raw = f"https://raw.githubusercontent.com/{slug}/main/index.json"
        badges.append(
            f'  <a href="https://github.com/{slug}/blob/main/INDEX.md"><img alt="Skills" '
            f'src="https://img.shields.io/badge/dynamic/json?url={raw}&query=%24.count'
            '&label=skills&color=blue"></a>'
        )
        badges.append(
            f'  <a href="https://github.com/{slug}/actions/workflows/registry.yml"><img '
            f'alt="Validation" src="https://github.com/{slug}/actions/workflows/registry.yml'
            '/badge.svg"></a>'
        )
        badges.append(
            f'  <a href="https://github.com/{slug}"><img alt="Registry" '
            f'src="https://img.shields.io/badge/registry-{name.replace("-", "--")}-green"></a>'
        )
    return "\n".join(badges)


def render_readme(name: str, description: str, git_url: str | None) -> str:
    return README_TEMPLATE.format(
        name=name,
        description=description,
        owl_repo=OWL_REPO,
        badges=_badges(name, _github_slug(git_url)),
        url_hint=git_url or "<git-url>",
    )


def _write_logo(root: Path) -> None:
    target = root / "assets" / "owl.png"
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with resources.as_file(resources.files("owl") / "assets" / "owl-256.png") as logo:
        shutil.copyfile(logo, target)


def scaffold(
    root: Path,
    *,
    name: str,
    description: str,
    git_url: str | None = None,
    overwrite: bool = False,
) -> list[str]:
    """Create the files every registry should have; with *overwrite* refresh the managed ones.

    Returns the relative paths that were written. User content (skills) is never touched.
    """
    written: list[str] = []

    def put(rel: str, text: str, managed: bool = True) -> None:
        target = root / rel
        if target.exists() and not (overwrite and managed):
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, "utf-8")
        written.append(rel)

    (root / "skills").mkdir(exist_ok=True)
    if not any((root / "skills").iterdir()):
        (root / "skills" / ".gitkeep").touch()
    put(
        REGISTRY_FILE,
        json.dumps({"format": INDEX_FORMAT, "name": name, "description": description}, indent=2)
        + "\n",
        managed=False,
    )
    put(".github/workflows/registry.yml", WORKFLOW)
    put("README.md", render_readme(name, description, git_url))
    put("CONTRIBUTING.md", CONTRIBUTING_TEMPLATE.format(name=name))
    put(".gitignore", GITIGNORE, managed=False)
    _write_logo(root)
    return written


def init_registry(
    path: Path,
    *,
    name: str | None = None,
    description: str = "",
    git_url: str | None = None,
    commit: bool = True,
) -> Path:
    """Create a new registry repository at *path* (git init, layout, CI workflow, empty index)."""
    path = path.expanduser().resolve()
    if is_registry(path):
        raise OwlError(f"{path} already is a registry")
    if path.exists() and any(path.iterdir()) and not gitutil.is_repo(path):
        raise OwlError(f"{path} exists and is not empty")
    name = name or path.name
    description = description or f"Skill registry {name}"
    if not gitutil.is_repo(path):
        gitutil.init(path, branch="main")
    if git_url:
        existing = gitutil.remote_url(path)
        if existing and existing != git_url:
            raise OwlError(f"{path} already has origin {existing}")
        gitutil.set_remote(path, git_url)
    scaffold(path, name=name, description=description, git_url=git_url)
    write_index(path)
    if commit:
        gitutil.commit_all(path, "chore: initialise registry")
    return path


# -- discovery and validation -------------------------------------------------------------


@dataclass
class Scan:
    """Result of scanning ``skills/`` for the index."""

    skills: list[tuple[Skill, str]] = field(default_factory=list)  # (skill, relative dir)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _symlinks(root: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in [*dirnames, *filenames]:
            candidate = Path(dirpath) / name
            if candidate.is_symlink():
                found.append(candidate.relative_to(root).as_posix())
    return sorted(found)


def legacy_dirs(root: Path) -> list[Path]:
    """Author directories of the old ``skills/<author>/<name>`` layout."""
    skills = root / "skills"
    if not skills.is_dir():
        return []
    return sorted(
        d
        for d in skills.iterdir()
        if d.is_dir()
        and not d.name.startswith(".")
        and not (d / SKILL_FILE).is_file()
        and any((sub / SKILL_FILE).is_file() for sub in d.iterdir() if sub.is_dir())
    )


def scan_registry(root: Path) -> Scan:
    """Validate every skill under ``root/skills`` (read-only; nothing is executed)."""
    root = root.resolve()
    scan = Scan()
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        scan.problems.append("missing skills/ directory")
        return scan
    for link in _symlinks(skills_dir):
        scan.problems.append(f"skills/{link}: symbolic links are not allowed")
    for author_dir in legacy_dirs(root):
        scan.problems.append(
            f"{author_dir.relative_to(root).as_posix()}: legacy skills/<author>/<name> layout - "
            "run `owl registry migrate`"
        )
    seen_names: dict[str, str] = {}
    for directory in find_skill_dirs(skills_dir):
        rel = directory.relative_to(root).as_posix()
        result = load_skill_dir(directory)
        if not result.valid:
            scan.problems.extend(f"{rel}: {p}" for p in result.problems)
            continue
        skill = result.skill
        if directory.parent != skills_dir.resolve() and not legacy_dirs(root):
            scan.problems.append(f"{rel}: skills must be direct children of skills/")
        if directory.name != skill.name:
            scan.problems.append(f"{rel}: directory name must equal the skill name '{skill.name}'")
        if skill.name in seen_names:
            scan.problems.append(
                f"{rel}: name collision with {seen_names[skill.name]} (names are unique)"
            )
        seen_names[skill.name] = rel
        for path, data in skill.files.items():
            if len(data) > MAX_FILE_BYTES:
                scan.problems.append(
                    f"{rel}/{path}: larger than {MAX_FILE_BYTES // (1024 * 1024)} MiB"
                )
        if skill.total_bytes > MAX_TOTAL_BYTES:
            scan.problems.append(f"{rel}: skill larger than {MAX_TOTAL_BYTES // (1024 * 1024)} MiB")
        if skill.author in ("", "local") and not _declares_author(directory):
            scan.warnings.append(f"{rel}: no author declared (frontmatter or skill.json)")
        scan.warnings.extend(f"{rel}: {w}" for w in result.warnings if "directory name" not in w)
        scan.skills.append((skill, rel))
    refs = [s.ref for s, _ in scan.skills]
    for dup in sorted({r for r in refs if refs.count(r) > 1}):
        scan.problems.append(f"duplicate skill {dup}")
    return scan


def _declares_author(directory: Path) -> bool:
    try:
        meta = json.loads((directory / META_FILE).read_text("utf-8"))
        if isinstance(meta, dict) and meta.get("author"):
            return True
    except (OSError, ValueError):
        pass
    frontmatter, _, _ = split_frontmatter((directory / SKILL_FILE).read_text("utf-8", "replace"))
    nested = frontmatter.get("metadata")
    return bool(frontmatter.get("author") or (isinstance(nested, dict) and nested.get("author")))


# -- index --------------------------------------------------------------------------------


def _git_info(root: Path, rel: str) -> tuple[str, str] | None:
    """``(commit time, commit sha)`` of the last commit touching *rel*, if committed and clean."""
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", rel],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if status.returncode != 0 or status.stdout.strip():
            return None
        log = subprocess.run(
            ["git", "log", "-1", "--format=%cI %H", "--", rel],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    value = log.stdout.strip()
    if log.returncode != 0 or " " not in value:
        return None
    when, sha = value.split(" ", 1)
    return datetime.fromisoformat(when).astimezone(UTC).isoformat(timespec="seconds"), sha


def _frontmatter_value(skill: Skill, key: str) -> str | None:
    value = skill.extra.get(key)
    if value is None:
        fm, _body, _ = split_frontmatter(skill.content)
        value = fm.get(key)
        nested = fm.get("metadata")
        if value is None and isinstance(nested, dict):
            value = nested.get(key)
    return str(value) if value not in (None, "") else None


def _entry(skill: Skill, rel: str, updated_at: str, revision: str | None) -> dict[str, Any]:
    return {
        "ref": skill.ref,
        "author": skill.author,
        "name": skill.name,
        "version": skill.version,
        "description": skill.description,
        "tags": skill.tags,
        "topics": skill.topics,
        "license": _frontmatter_value(skill, "license"),
        "compatibility": _frontmatter_value(skill, "compatibility"),
        "sha256": skill.sha256,
        "path": rel,
        "files": len(skill.files) + 1,
        "size": skill.total_bytes,
        "updated_at": updated_at,
        "revision": revision,
    }


def load_index(root: Path) -> dict[str, Any] | None:
    file = root / INDEX_FILE
    try:
        data = json.loads(file.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("skills"), list):
        return None
    if data.get("format") not in READABLE_FORMATS:
        return None
    return data


def build_index(root: Path) -> dict[str, Any]:
    """Build the index document. Raises :class:`OwlError` listing every problem found.

    ``updated_at`` (and ``revision``) of a skill are kept from the previous index while its hash is
    unchanged; for new or changed skills they come from the git history of the skill directory, or
    are *now* for an uncommitted change. The output is stable between runs.
    """
    root = root.resolve()
    scan = scan_registry(root)
    if scan.problems:
        raise OwlError("registry has problems:\n  " + "\n  ".join(scan.problems))
    previous = {e.get("ref"): e for e in (load_index(root) or {}).get("skills", [])}
    entries: list[dict[str, Any]] = []
    for skill, rel in scan.skills:
        old = previous.get(skill.ref)
        same = old is not None and old.get("sha256") == skill.sha256
        old_stamp = old.get("updated_at") if old is not None and same else None
        old_revision = old.get("revision") if old is not None and same else None
        if old_stamp and old_revision:
            stamp, revision = old_stamp, old_revision
        else:
            info = _git_info(root, rel)  # also upgrades an uncommitted entry once it is committed
            if info:
                stamp, revision = info
            elif old_stamp:
                stamp, revision = old_stamp, None
            else:
                stamp, revision = _now(), None
        entries.append(_entry(skill, rel, stamp, revision))
    entries.sort(key=lambda e: e["ref"])
    meta: dict[str, Any] = {}
    with contextlib.suppress(OSError, ValueError):
        meta = json.loads((root / REGISTRY_FILE).read_text("utf-8"))
    return {
        "format": INDEX_FORMAT,
        "name": meta.get("name", root.name),
        "description": meta.get("description", ""),
        "generated_at": max((e["updated_at"] for e in entries), default=""),
        "count": len(entries),
        "skills": entries,
    }


def build_stats(index: dict[str, Any]) -> dict[str, Any]:
    """Aggregate statistics from the index. Only facts derivable from the registry itself."""
    skills = index["skills"]

    def count(values: list[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in values:
            out[v] = out.get(v, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

    return {
        "format": INDEX_FORMAT,
        "registry": index["name"],
        "generated_at": index["generated_at"],
        "totals": {
            "skills": len(skills),
            "files": sum(e["files"] for e in skills),
            "size_bytes": sum(e["size"] for e in skills),
            "invalid_entries": 0,  # an index is only written when every skill is valid
        },
        "by_author": count([e["author"] for e in skills]),
        "by_tag": count([t for e in skills for t in e["tags"]]),
        "by_topic": count([t for e in skills for t in e["topics"]]),
        "by_compatibility": count([e["compatibility"] for e in skills if e.get("compatibility")]),
        "by_license": count([e["license"] for e in skills if e.get("license")]),
    }


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(index: dict[str, Any]) -> str:
    """The quick-to-read overview (INDEX.md) generated from the index."""
    skills = index["skills"]
    plural = "s" if index["count"] != 1 else ""
    lines = [
        "<!-- generated by `owl registry index` - do not edit -->",
        f"# {index['name']} - skill index",
        "",
        index.get("description") or "",
        "",
        f"**{index['count']} skill{plural}** · last update: `{index.get('generated_at') or '-'}` · "
        "[statistics](STATS.md)",
        "",
        "Machine readable: [`index.json`](index.json). Install with "
        "`owl install <name> -r <registry>` (see `owl registry add`).",
        "",
        "## All skills",
        "",
        "| Skill | Author | Version | Description | Tags | Updated |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for e in skills:
        desc = _cell(e["description"])
        if len(desc) > 140:
            desc = desc[:137] + "..."
        lines.append(
            f"| [`{e['name']}`]({e['path']}/SKILL.md) | {e['author']} | {e['version']} | {desc} | "
            f"{_cell(', '.join(e['tags']))} | {e['updated_at'][:10]} |"
        )
    for title, key in (("topic", "topics"), ("tag", "tags")):
        groups: dict[str, list[str]] = {}
        for e in skills:
            for value in e[key]:
                groups.setdefault(value, []).append(e["name"])
        if groups:
            lines += ["", f"## By {title}", ""]
            for value in sorted(groups):
                names = ", ".join(f"`{n}`" for n in groups[value])
                lines.append(f"- **{value}** ({len(groups[value])}): {names}")
    return "\n".join(lines) + "\n"


def render_stats_markdown(stats: dict[str, Any]) -> str:
    t = stats["totals"]
    lines = [
        "<!-- generated by `owl registry index` - do not edit -->",
        f"# {stats['registry']} - statistics",
        "",
        f"Last index build: `{stats['generated_at'] or '-'}`",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Skills | {t['skills']} |",
        f"| Files | {t['files']} |",
        f"| Total size | {t['size_bytes']:,} bytes |",
        f"| Invalid entries | {t['invalid_entries']} |",
    ]
    for title, key in (
        ("Skills by author", "by_author"),
        ("Skills by topic", "by_topic"),
        ("Skills by tag", "by_tag"),
        ("Skills by compatibility", "by_compatibility"),
        ("Skills by license", "by_license"),
    ):
        data = stats[key]
        if data:
            lines += ["", f"## {title}", "", "| Value | Skills |", "| --- | --- |"]
            lines += [f"| {_cell(k)} | {v} |" for k, v in data.items()]
    return "\n".join(lines) + "\n"


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def render_outputs(root: Path) -> dict[str, str]:
    index = build_index(root)
    stats = build_stats(index)
    return {
        INDEX_FILE: _dump(index),
        STATS_FILE: _dump(stats),
        INDEX_MD: render_markdown(index),
        STATS_MD: render_stats_markdown(stats),
    }


def write_index(root: Path) -> dict[str, Any]:
    """Regenerate the four generated files; only files whose content changed are touched.

    Nothing is written when validation fails, so the previous valid state is preserved.
    """
    root = root.resolve()
    outputs = render_outputs(root)
    for name, text in outputs.items():
        target = root / name
        if not target.exists() or target.read_text("utf-8") != text:
            target.write_text(text, "utf-8")
    return json.loads(outputs[INDEX_FILE])


def index_is_current(root: Path) -> bool:
    root = root.resolve()
    outputs = render_outputs(root)
    return all(
        (root / name).is_file() and (root / name).read_text("utf-8") == text
        for name, text in outputs.items()
    )


def check_registry(root: Path, *, fresh: bool = False) -> tuple[list[str], list[str]]:
    """Validate a registry; returns ``(problems, warnings)``.

    Checks structure, names, frontmatter, paths, sizes, collisions and that an existing
    ``index.json`` is well-formed and points at real skills. With *fresh* the generated files must
    also be up to date.
    """
    root = root.resolve()
    problems: list[str] = []
    if not is_registry(root):
        problems.append(f"{REGISTRY_FILE} is missing - not a registry (see `owl registry init`)")
    scan = scan_registry(root)
    problems.extend(scan.problems)
    warnings = list(scan.warnings)
    if (root / INDEX_FILE).exists():
        index = load_index(root)
        if index is None:
            problems.append(f"{INDEX_FILE} is not a valid index (format {READABLE_FORMATS})")
        else:
            for entry in index["skills"]:
                path = root / str(entry.get("path", ""))
                if not (path.resolve().is_relative_to(root) and (path / SKILL_FILE).is_file()):
                    problems.append(
                        f"{INDEX_FILE}: entry {entry.get('ref')} points to a missing path"
                    )
    if fresh and not problems and not index_is_current(root):
        problems.append("generated files are out of date: run `owl registry index`")
    return problems, warnings


# -- migration ----------------------------------------------------------------------------


@dataclass
class MigrationPlan:
    moves: list[tuple[Path, Path, str]] = field(default_factory=list)  # (source, target, author)
    conflicts: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.moves and not self.conflicts


def plan_migration(root: Path) -> MigrationPlan:
    """Plan the move from ``skills/<author>/<name>`` to ``skills/<name>``."""
    root = root.resolve()
    plan = MigrationPlan()
    skills = root / "skills"
    targets: dict[Path, Path] = {}
    for author_dir in legacy_dirs(root):
        for source in sorted(p for p in author_dir.iterdir() if p.is_dir()):
            if not (source / SKILL_FILE).is_file():
                continue
            result = load_skill_dir(source, default_author=author_dir.name)
            if not result.valid:
                plan.conflicts.append(f"{source.relative_to(root)}: {'; '.join(result.problems)}")
                continue
            target = skills / result.skill.name
            if target.exists():
                plan.conflicts.append(
                    f"{source.relative_to(root)} -> {target.relative_to(root)}: target exists"
                )
            elif target in targets:
                plan.conflicts.append(
                    f"{source.relative_to(root)}: name '{result.skill.name}' is also used by "
                    f"{targets[target].relative_to(root)}"
                )
            else:
                targets[target] = source
                plan.moves.append((source, target, author_dir.name))
    return plan


def migrate_registry(root: Path, *, dry_run: bool = False) -> MigrationPlan:
    """Convert a legacy registry to the flat layout.

    Each skill is copied to its new location, verified (same content hash, author kept in
    ``skill.json``) and only then removed from the old place. Conflicts abort the whole migration
    before anything is touched. Running it again after success does nothing.
    """
    root = root.resolve()
    plan = plan_migration(root)
    if plan.conflicts:
        raise OwlError("migration aborted, nothing was changed:\n  " + "\n  ".join(plan.conflicts))
    if dry_run or not plan.moves:
        return plan
    in_git = gitutil.is_repo(root)
    done: list[tuple[Path, Path]] = []
    try:
        for source, target, author in plan.moves:
            before = load_skill_dir(source, default_author=author).skill
            shutil.copytree(source, target, symlinks=False)
            if not (target / META_FILE).exists():  # keep the author the old path implied
                (target / META_FILE).write_text(
                    json.dumps(before.meta(), indent=2, ensure_ascii=False) + "\n", "utf-8"
                )
            after = load_skill_dir(target).skill
            if after.sha256 != before.sha256:
                shutil.rmtree(target)
                raise OwlError(f"{source}: content hash changed during migration; aborted")
            done.append((source, target))
    except BaseException:
        for _src, target in done:
            shutil.rmtree(target, ignore_errors=True)
        raise
    for source, _target in done:
        if in_git:
            subprocess.run(["git", "rm", "-r", "-q", "--", str(source)], cwd=root, check=False)
        shutil.rmtree(source, ignore_errors=True)
        parent = source.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    write_index(root)
    return plan
