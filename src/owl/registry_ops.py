"""Working with registries as *writable* git repositories: checkouts, publishing and merging.

Everything here is local by default. Pushing and opening pull requests only happen when the caller
asks for them explicitly, never with ``--force``, and only into branches the caller named.
"""

from __future__ import annotations

import difflib
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from owl import gitutil, paths, registry
from owl.config import Config
from owl.models import NAME_RE, OwlError, Skill
from owl.parsing import split_frontmatter
from owl.stores.base import SkillStore
from owl.stores.directory import DirectoryStore, NameCollision

# -- locating a writable registry -----------------------------------------------------------


def checkout_dir(name: str) -> Path:
    return paths.home() / "checkouts" / name


def writable_registry(cfg: Config, target: str | None, directory: Path | None) -> Path:
    """Resolve ``--dir`` / ``--to NAME`` to a local, writable registry checkout.

    A configured registry that points to a local directory is used directly. A git URL gets a
    full working clone in ``$OWL_HOME/checkouts/<name>`` (created on first use, never touched when
    it has uncommitted changes).
    """
    if directory is not None:
        root = directory.expanduser().resolve()
    elif target:
        remote = cfg.remote(target)
        if remote.kind != "registry":
            raise OwlError(f"'{target}' is a server, not a registry; use `owl push -r {target}`")
        if gitutil.is_git_url(remote.url):
            root = checkout_dir(target)
            if not gitutil.is_repo(root):
                root.parent.mkdir(parents=True, exist_ok=True)
                gitutil.clone(remote.url, root, ref=remote.ref, depth=None)
            elif gitutil.is_dirty(root):
                raise OwlError(
                    f"The checkout {root} has uncommitted changes; commit or discard them first"
                )
            else:
                gitutil.pull(root)
        else:
            root = Path(remote.url).expanduser().resolve()
    else:
        root = Path.cwd()
    if not registry.is_registry(root):
        raise OwlError(
            f"{root} is not a registry (no {registry.REGISTRY_FILE}); see `owl registry init`"
        )
    return root


# -- publishing -----------------------------------------------------------------------------


@dataclass
class PublishItem:
    skill: Skill
    action: str  #: add | update | unchanged | collision
    note: str = ""
    diff: str = ""


def plan_publish(root: Path, skills: list[Skill]) -> list[PublishItem]:
    store = DirectoryStore(root)
    items: list[PublishItem] = []
    all_skills = {(s.author, s.name): store.get(s.author, s.name) for s in store.list()}
    by_name = {name: author for (author, name) in all_skills}
    for skill in skills:
        current = all_skills.get((skill.author, skill.name))
        if current is not None:
            if current.sha256 == skill.sha256:
                items.append(PublishItem(skill, "unchanged"))
            else:
                items.append(
                    PublishItem(
                        skill,
                        "update",
                        f"{current.version} -> {skill.version}",
                        _diff(current, skill),
                    )
                )
        elif skill.name in by_name:
            items.append(
                PublishItem(
                    skill,
                    "collision",
                    f"name already used by author '{by_name[skill.name]}' (choose another name)",
                )
            )
        else:
            items.append(PublishItem(skill, "add"))
    return items


def _diff(old: Skill, new: Skill) -> str:
    lines: list[str] = []
    for label, a, b in (
        ("SKILL.md", old.content, new.content),
        ("skill.json", _meta(old), _meta(new)),
    ):
        lines += difflib.unified_diff(
            a.splitlines(keepends=True),
            b.splitlines(keepends=True),
            f"registry/{label}",
            f"new/{label}",
        )
    changed = sorted(
        set(old.files) ^ set(new.files)
        | {p for p in old.files.keys() & new.files.keys() if old.files[p] != new.files[p]}
    )
    if changed:
        lines.append(f"# bundled files changed: {', '.join(changed)}\n")
    return "".join(lines)


def _meta(skill: Skill) -> str:
    import json

    return json.dumps(skill.meta(), indent=2, ensure_ascii=False) + "\n"


def apply_publish(root: Path, items: list[PublishItem]) -> list[Skill]:
    store = DirectoryStore(root)
    stored: list[Skill] = []
    for item in items:
        if item.action in ("add", "update"):
            stored.append(store.upsert(item.skill))
    registry.write_index(root)
    return stored


def commit_message(items: list[PublishItem]) -> str:
    added = [i.skill.name for i in items if i.action == "add"]
    updated = [i.skill.name for i in items if i.action == "update"]
    if added and not updated:
        subject = (
            f"feat: add {', '.join(added)}" if len(added) <= 3 else f"feat: add {len(added)} skills"
        )
    elif updated and not added:
        subject = (
            f"feat: update {', '.join(updated)}"
            if len(updated) <= 3
            else f"feat: update {len(updated)} skills"
        )
    else:
        subject = f"feat: add {len(added)} and update {len(updated)} skills"
    body = "\n".join([f"- add {n}" for n in added] + [f"- update {n}" for n in updated])
    return f"{subject}\n\n{body}" if body else subject


def default_branch_name(items: list[PublishItem]) -> str:
    names = [i.skill.name for i in items if i.action in ("add", "update")][:2]
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M")
    return "owl/publish-" + "-".join(names or ["skills"])[:40] + f"-{stamp}"


def has_gh() -> bool:
    return shutil.which("gh") is not None


def prepare_pull_request(root: Path, branch: str, execute: bool) -> str:
    """Create a pull request with the ``gh`` CLI when asked to; otherwise explain how.

    Returns a human readable result. Only ever called for an explicit ``--pr``.
    """
    url = gitutil.remote_url(root) or ""
    slug = registry._github_slug(url)  # noqa: SLF001
    if has_gh() and execute:
        proc = subprocess.run(
            ["gh", "pr", "create", "--fill", "--head", branch],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise OwlError(f"gh pr create failed: {(proc.stderr or proc.stdout).strip()}")
        return proc.stdout.strip()
    if slug:
        return f"Open a pull request: https://github.com/{slug}/compare/{branch}?expand=1"
    return f"Branch '{branch}' is pushed; open a merge/pull request on your git host."


# -- merging ---------------------------------------------------------------------------------


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version)[:4]) or (0,)


@dataclass
class MergeItem:
    kind: str  #: only-source | only-dest | identical | content-conflict | metadata-conflict | name-collision
    source: Skill | None
    dest: Skill | None
    note: str = ""
    resolution: str = ""  #: "" (undecided) | source | dest | skip | rename:<new-name> | manual

    @property
    def ref(self) -> str:
        skill = self.source or self.dest
        assert skill is not None
        return skill.ref

    @property
    def conflict(self) -> bool:
        return self.kind in ("content-conflict", "metadata-conflict", "name-collision")


def _same_payload(a: Skill, b: Skill) -> bool:
    return a.content == b.content and a.files == b.files


def plan_merge(source: list[Skill], dest: list[Skill], *, unique_names: bool) -> list[MergeItem]:
    """Compare two skill sets; never decides anything about conflicts.

    *unique_names* is true for flat registries / git libraries, where two authors cannot share a
    skill name.
    """
    d_by_ref = {s.ref: s for s in dest}
    d_by_name: dict[str, Skill] = {s.name: s for s in dest}
    items: list[MergeItem] = []
    seen: set[str] = set()
    for s in sorted(source, key=lambda x: x.ref):
        seen.add(s.ref)
        d = d_by_ref.get(s.ref)
        if d is None:
            clash = d_by_name.get(s.name) if unique_names else None
            if clash is not None:
                items.append(
                    MergeItem(
                        "name-collision",
                        s,
                        clash,
                        f"name '{s.name}' is used by author '{clash.author}' in the destination",
                    )
                )
            else:
                items.append(MergeItem("only-source", s, None))
        elif s.sha256 == d.sha256:
            items.append(MergeItem("identical", s, d))
        elif _same_payload(s, d):
            items.append(MergeItem("metadata-conflict", s, d, _meta_difference(s, d)))
        else:
            rel = (
                "source is newer"
                if _version_key(s.version) > _version_key(d.version)
                else "destination is newer"
                if _version_key(s.version) < _version_key(d.version)
                else "same version, different content"
            )
            items.append(
                MergeItem("content-conflict", s, d, f"{s.version} (source) vs {d.version} ({rel})")
            )
    for d in sorted(dest, key=lambda x: x.ref):
        if d.ref not in seen:
            items.append(MergeItem("only-dest", None, d))
    return items


def _meta_difference(a: Skill, b: Skill) -> str:
    diffs = [
        k
        for k in ("version", "description", "tags", "topics", "author")
        if getattr(a, k) != getattr(b, k)
    ]
    if a.extra != b.extra:
        diffs.append("extra metadata")
    return "differs in " + ", ".join(diffs or ["metadata"])


def rename_skill(skill: Skill, new_name: str) -> Skill:
    """A copy of *skill* under a new name (frontmatter and metadata are kept consistent)."""
    if not NAME_RE.fullmatch(new_name) or len(new_name) > 64:
        raise OwlError(f"Invalid skill name '{new_name}'")
    fm, body, problems = split_frontmatter(skill.content)
    if problems:
        raise OwlError(f"Cannot rename {skill.ref}: {'; '.join(problems)}")
    fm["name"] = new_name
    ordered = {"name": fm.pop("name"), **fm}
    header = yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, width=10**6)
    content = f"---\n{header}---\n{body}"
    return Skill(
        author=skill.author,
        name=new_name,
        version=skill.version,
        description=skill.description,
        tags=skill.tags,
        topics=skill.topics,
        content=content,
        extra=skill.extra,
        files=skill.files,
    )


def compare_text(item: MergeItem) -> str:
    if item.source is None or item.dest is None:
        return ""
    return _diff(item.dest, item.source)


@dataclass
class MergeResult:
    copied: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    unresolved: list[MergeItem] = field(default_factory=list)
    identical: int = 0

    def report(self) -> dict[str, Any]:
        return {
            "copied": self.copied,
            "replaced": self.replaced,
            "kept_destination": self.kept,
            "renamed": [{"from": a, "to": b} for a, b in self.renamed],
            "identical": self.identical,
            "unresolved": [
                {
                    "ref": i.ref,
                    "kind": i.kind,
                    "note": i.note,
                    "source": _brief(i.source),
                    "destination": _brief(i.dest),
                    "how_to_resolve": "owl merge --interactive, or --on-conflict source|dest, or edit by hand",
                }
                for i in self.unresolved
            ],
        }


def _brief(skill: Skill | None) -> dict[str, str] | None:
    return (
        None
        if skill is None
        else {"ref": skill.ref, "version": skill.version, "sha256": skill.sha256}
    )


def apply_merge(items: list[MergeItem], dest: SkillStore) -> MergeResult:
    """Apply decided items to *dest*. Undecided conflicts stay unresolved (nothing is overwritten)."""
    result = MergeResult()
    for item in items:
        if item.kind == "identical":
            result.identical += 1
        elif item.kind == "only-dest":
            continue
        elif item.kind == "only-source":
            assert item.source is not None
            dest.upsert(item.source)
            result.copied.append(item.ref)
        else:
            res = item.resolution
            if res == "source" and item.kind != "name-collision":
                assert item.source is not None
                dest.upsert(item.source)
                result.replaced.append(item.ref)
            elif res == "dest":
                result.kept.append(item.ref)
            elif res.startswith("rename:") and item.source is not None:
                new = rename_skill(item.source, res.split(":", 1)[1])
                try:
                    dest.upsert(new)
                except NameCollision as exc:
                    raise OwlError(f"{exc}") from exc
                result.renamed.append((item.ref, new.ref))
            elif res == "skip":
                result.kept.append(item.ref)
            else:
                result.unresolved.append(item)
    return result
