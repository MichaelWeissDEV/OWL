"""Skill registries: git repositories with a machine- and human-readable index.

A registry is a git repository laid out like OWL's directory store::

    registry.json            marker + name/description
    index.json               generated: every skill with version, tags, hashes, last update
    INDEX.md                 generated: quick-to-read overview that links to every skill
    skills/<author>/<name>/  SKILL.md, skill.json, bundled files
    .github/workflows/registry.yml   CI that keeps index.json / INDEX.md current

Clients read ``index.json`` to search without touching every skill; CI regenerates it.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from owl import gitutil
from owl.models import OwlError, Skill
from owl.parsing import find_skill_dirs, load_skill_dir

REGISTRY_FILE = "registry.json"
INDEX_FILE = "index.json"
INDEX_MD = "INDEX.md"
INDEX_FORMAT = 1
OWL_REPO = "https://github.com/MichaelWeissDEV/OWL"

WORKFLOW = f"""\
name: registry

on:
  pull_request:
    paths: ["skills/**", "registry.json"]
  push:
    branches: [main]
    paths: ["skills/**", "registry.json"]
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: registry-${{{{ github.ref }}}}
  cancel-in-progress: false

jobs:
  index:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # full history: last-update times come from git
      - uses: astral-sh/setup-uv@v5
      - name: Install OWL
        run: uv tool install "git+{OWL_REPO}"
      - name: Validate skills
        run: |
          if [ -d skills ] && [ -n "$(find skills -name SKILL.md -print -quit)" ]; then
            owl validate skills
          fi
      - name: Regenerate index.json and INDEX.md
        if: github.event_name != 'pull_request'
        run: owl registry index .
      - name: Commit the index
        if: github.event_name != 'pull_request'
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add index.json INDEX.md
          if git diff --cached --quiet; then
            echo "index is up to date"
          else
            git commit -m "chore: update registry index [skip ci]"
            git push
          fi
"""

README_TEMPLATE = """\
# {name}

{description}

A skill registry for [OWL]({owl_repo}). Browse [`INDEX.md`](INDEX.md) for a quick overview or read
[`index.json`](index.json) from tools.

## Use it

```console
$ owl registry add {name} {url_hint}
$ owl search <words> -r {name}
$ owl install <author>/<skill> -r {name}          # one skill
$ owl install --all -r {name}                     # everything
$ owl install --all -r {name} --target opencode   # for OpenCode instead of Claude Code
```

## Contribute

Add a skill directory below `skills/<author>/<name>/` (`SKILL.md` with `name` and `description`
frontmatter) and open a pull request. CI validates it; after the merge CI regenerates
`index.json` and `INDEX.md` - never edit those by hand.

Locally: `owl registry publish ./my-skill --dir .` copies a skill in and updates the index.
"""

GITIGNORE = ".DS_Store\n__pycache__/\n"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def is_registry(path: Path) -> bool:
    return (path / REGISTRY_FILE).is_file()


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
        gitutil.set_remote(path, git_url)
    (path / "skills").mkdir(exist_ok=True)
    (path / "skills" / ".gitkeep").touch()
    (path / REGISTRY_FILE).write_text(
        json.dumps({"format": INDEX_FORMAT, "name": name, "description": description}, indent=2)
        + "\n",
        "utf-8",
    )
    workflow = path / ".github" / "workflows" / "registry.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(WORKFLOW, "utf-8")
    (path / "README.md").write_text(
        README_TEMPLATE.format(
            name=name,
            description=description,
            owl_repo=OWL_REPO,
            url_hint=git_url or "<git-url>",
        ),
        "utf-8",
    )
    (path / ".gitignore").write_text(GITIGNORE, "utf-8")
    write_index(path)
    if commit:
        gitutil.commit_all(path, "chore: initialise registry")
    return path


# -- index -------------------------------------------------------------------------------


def _git_time(root: Path, rel: str) -> str | None:
    """Commit time of the last commit touching *rel*, if it is committed and unmodified."""
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
            ["git", "log", "-1", "--format=%cI", "--", rel],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    value = log.stdout.strip()
    if log.returncode != 0 or not value:
        return None
    return datetime.fromisoformat(value).astimezone(UTC).isoformat(timespec="seconds")


def _entry(skill: Skill, rel: str, updated_at: str) -> dict[str, Any]:
    return {
        "ref": skill.ref,
        "author": skill.author,
        "name": skill.name,
        "version": skill.version,
        "description": skill.description,
        "tags": skill.tags,
        "topics": skill.topics,
        "sha256": skill.sha256,
        "path": rel,
        "files": len(skill.files) + 1,
        "updated_at": updated_at,
    }


def load_index(root: Path) -> dict[str, Any] | None:
    file = root / INDEX_FILE
    try:
        data = json.loads(file.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("skills"), list) else None


def build_index(root: Path) -> dict[str, Any]:
    """Scan ``root/skills`` and build the index document.

    ``updated_at`` of a skill is kept from the previous index while its hash is unchanged;
    for new or changed skills it is the git commit time of the skill directory, or *now* when
    the change is not committed yet. The output is therefore stable between runs.
    """
    root = root.resolve()
    previous = {e.get("ref"): e for e in (load_index(root) or {}).get("skills", [])}
    entries: list[dict[str, Any]] = []
    skills_dir = root / "skills"
    for directory in find_skill_dirs(skills_dir) if skills_dir.is_dir() else []:
        result = load_skill_dir(directory)
        if not result.valid:
            raise OwlError(f"{directory}: {'; '.join(result.problems)}")
        rel = directory.relative_to(root).as_posix()
        skill = result.skill
        old = previous.get(skill.ref)
        if old and old.get("sha256") == skill.sha256 and old.get("updated_at"):
            stamp = old["updated_at"]
        else:
            stamp = _git_time(root, rel) or _now()
        entries.append(_entry(skill, rel, stamp))
    refs = [e["ref"] for e in entries]
    duplicates = sorted({r for r in refs if refs.count(r) > 1})
    if duplicates:
        raise OwlError(f"Duplicate skills in registry: {', '.join(duplicates)}")
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


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(index: dict[str, Any]) -> str:
    """The quick-to-read overview (INDEX.md) generated from the index."""
    skills = index["skills"]
    lines = [
        "<!-- generated by `owl registry index` - do not edit -->",
        f"# {index['name']} - skill index",
        "",
        index.get("description") or "",
        "",
        f"**{index['count']} skill{'s' if index['count'] != 1 else ''}** · last update: `{index.get('generated_at') or '-'}`",
        "",
        "Machine readable: [`index.json`](index.json). Install with "
        "`owl install <author>/<name> -r <registry>` (see `owl registry add`).",
        "",
        "## All skills",
        "",
        "| Skill | Version | Description | Tags | Updated |",
        "| --- | --- | --- | --- | --- |",
    ]
    for e in skills:
        desc = _cell(e["description"])
        if len(desc) > 140:
            desc = desc[:137] + "..."
        lines.append(
            f"| [`{e['ref']}`]({e['path']}/SKILL.md) | {e['version']} | {desc} | "
            f"{_cell(', '.join(e['tags']))} | {e['updated_at'][:10]} |"
        )
    for title, key in (("Topics", "topics"), ("Tags", "tags")):
        groups: dict[str, list[str]] = {}
        for e in skills:
            for value in e[key]:
                groups.setdefault(value, []).append(e["ref"])
        if groups:
            lines += ["", f"## By {title.lower()[:-1] if title == 'Topics' else 'tag'}", ""]
            for value in sorted(groups):
                refs = ", ".join(f"`{r}`" for r in groups[value])
                lines.append(f"- **{value}** ({len(groups[value])}): {refs}")
    return "\n".join(lines).replace("\n\n\n", "\n\n") + "\n"


def write_index(root: Path) -> dict[str, Any]:
    """Regenerate ``index.json`` and ``INDEX.md``; files are only touched when content changes."""
    root = root.resolve()
    index = build_index(root)
    outputs = {
        INDEX_FILE: json.dumps(index, indent=2, ensure_ascii=False) + "\n",
        INDEX_MD: render_markdown(index),
    }
    for name, text in outputs.items():
        target = root / name
        if not target.exists() or target.read_text("utf-8") != text:
            target.write_text(text, "utf-8")
    return index


def index_is_current(root: Path) -> bool:
    root = root.resolve()
    index = build_index(root)
    return (root / INDEX_FILE).is_file() and (root / INDEX_FILE).read_text("utf-8") == (
        json.dumps(index, indent=2, ensure_ascii=False) + "\n"
    )
