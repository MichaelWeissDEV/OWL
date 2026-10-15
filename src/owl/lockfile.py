"""``owl.lock``: reproducible installations.

The lock file pins each installed skill to the *revision* it came from (git URL, commit, path)
and to its content hash. Installing from a lock fetches exactly that revision and verifies the
hash; a mismatch aborts that skill.

A SHA-256 hash detects changes. It is **not** a signature: someone who controls the source can
change content *and* hash together. The lock protects against accidental drift and against content
changing under a fixed commit, not against a malicious publisher.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from owl import gitutil
from owl.config import Config
from owl.fsutil import safe_relpath
from owl.installer import list_installed
from owl.models import OwlError, Skill
from owl.parsing import load_skill_dir
from owl.stores import open_remote
from owl.targets import all_targets, resolve_targets

LOCK_FILE = "owl.lock"
LOCK_FORMAT = 1


class IntegrityError(OwlError):
    """The fetched content does not match the hash recorded in the lock."""


def lock_path(root: Path) -> Path:
    return root / LOCK_FILE


def build_lock(
    root: Path, cfg: Config, targets: list[str] | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Describe the skills installed in the project at *root* (all known tools by default).

    Returns ``(lock, warnings)``; skills without a recorded revision are listed as *unpinned*.
    """
    entries: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for tname, tdir in resolve_targets(
        targets or ["all"],
        project=True,
        project_root=root,
        configured=cfg.targets,
        custom=cfg.custom_targets,
    ):
        for item in list_installed(tdir):
            entry = entries.setdefault(
                item.ref,
                {
                    "ref": item.ref,
                    "name": item.name,
                    "version": item.version,
                    "sha256": item.sha256,
                    "source": _source_of(item.provenance, item.source, cfg),
                    "targets": [],
                },
            )
            if tname not in entry["targets"]:
                entry["targets"].append(tname)
            if entry["sha256"] != item.sha256:
                warnings.append(f"{item.ref}: different versions are installed for different tools")
    for entry in entries.values():
        src = entry["source"]
        if src["kind"] in ("git", "registry") and not src.get("commit") and not _is_dir(src):
            warnings.append(
                f"{entry['ref']}: no commit recorded (installed before provenance tracking?) - "
                "it is locked by content hash only; reinstall it from its source to pin the revision"
            )
    lock = {
        "format": LOCK_FORMAT,
        "skills": sorted(entries.values(), key=lambda e: e["ref"]),
    }
    return lock, warnings


def _is_dir(src: dict[str, Any]) -> bool:
    url = str(src.get("url") or "")
    return bool(url) and not gitutil.is_git_url(url)


def _source_of(provenance: dict | None, legacy_source: str, cfg: Config) -> dict[str, Any]:
    if provenance:
        keys = ("kind", "registry", "url", "ref", "commit", "path")
        return {k: provenance.get(k) for k in keys if provenance.get(k) is not None}
    remote = cfg.remotes.get(legacy_source)
    if remote is not None:
        return {"kind": remote.kind, "registry": legacy_source, "url": remote.url}
    return {"kind": "unknown", "url": legacy_source}


def write_lock(path: Path, lock: dict[str, Any]) -> None:
    text = json.dumps(lock, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_name(f".{path.name}.owl-tmp")
    tmp.write_text(text, "utf-8")
    tmp.replace(path)


def read_lock(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text("utf-8"))
    except OSError as exc:
        raise OwlError(f"Cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise OwlError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("format") != LOCK_FORMAT:
        raise OwlError(f"{path}: unsupported lock format (expected {LOCK_FORMAT})")
    for entry in data.get("skills", []):
        for key in ("ref", "name", "sha256", "source"):
            if key not in entry:
                raise OwlError(f"{path}: entry without '{key}': {entry}")
        if not isinstance(entry["source"], dict):
            raise OwlError(f"{path}: invalid source for {entry['ref']}")
    return data


def fetch_locked(entry: dict[str, Any], cfg: Config) -> Skill:
    """Fetch the exact skill described by *entry* and verify its content hash."""
    src = entry["source"]
    kind = src.get("kind")
    skill: Skill | None = None
    if kind in ("git", "registry", "directory") and src.get("url"):
        url, path = str(src["url"]), src.get("path")
        if path is None:
            raise OwlError(f"{entry['ref']}: the lock has no path for its source")
        rel = safe_relpath(str(path)) if path not in (".", "") else "."
        if gitutil.is_git_url(url):
            commit = src.get("commit")
            if not commit:
                raise OwlError(
                    f"{entry['ref']}: not pinned to a commit - cannot install reproducibly"
                )
            with tempfile.TemporaryDirectory(prefix="owl-lock-") as tmp:
                repo = Path(tmp) / "repo"
                gitutil.clone_at(url, repo, str(commit))
                skill = _load(repo, rel, entry)
        else:
            skill = _load(Path(url).expanduser(), rel, entry)
    elif kind == "server" or (kind == "registry" and src.get("registry") in cfg.remotes):
        store = open_remote(cfg, str(src.get("registry")))
        try:
            author, name = entry["ref"].split("/", 1)
            skill = store.get(author, name)
        finally:
            store.close()
    if skill is None:
        raise OwlError(f"{entry['ref']}: cannot fetch from source {src}")
    if skill.sha256 != entry["sha256"]:
        raise IntegrityError(
            f"{entry['ref']}: content hash {skill.sha256[:12]} does not match the locked "
            f"{entry['sha256'][:12]} - refusing to install"
        )
    skill.provenance = {**src, "sha256": skill.sha256}
    return skill


def _load(base: Path, rel: str, entry: dict[str, Any]) -> Skill:
    directory = (base / rel).resolve()
    if not directory.is_relative_to(base.resolve()) or not (directory / "SKILL.md").is_file():
        raise OwlError(f"{entry['ref']}: {rel} does not contain a skill at the locked revision")
    result = load_skill_dir(directory)
    if not result.valid:
        raise OwlError(f"{entry['ref']}: {'; '.join(result.problems)}")
    return result.skill


def verify_lock(root: Path, lock: dict[str, Any], cfg: Config) -> list[dict[str, str]]:
    """Compare the installed skills with the lock: ok / missing / changed / modified."""
    rows: list[dict[str, str]] = []
    known = set(all_targets(cfg.custom_targets))
    for entry in lock.get("skills", []):
        names = [t for t in entry.get("targets") or ["claude"] if t in known] or ["claude"]
        for tname, tdir in resolve_targets(
            names,
            project=True,
            project_root=root,
            configured=cfg.targets,
            custom=cfg.custom_targets,
        ):
            installed = {i.ref: i for i in list_installed(tdir)}.get(entry["ref"])
            if installed is None:
                status = "missing"
            elif installed.sha256 != entry["sha256"]:
                status = "changed"
            elif installed.modified_files():
                status = "modified"
            else:
                status = "ok"
            rows.append({"ref": entry["ref"], "target": tname, "status": status})
    return rows
