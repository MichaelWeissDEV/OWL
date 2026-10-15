"""Backup, verify and restore of OWL's local state (a single zip archive with a manifest).

Contents: ``config.json``, the personal database (``local.sqlite3``), the catalog (SQLite file or the
git library's files), ``state.json``, custom format templates and - optionally - cached registries.
PostgreSQL servers are backed up with ``pg_dump`` (see the operations guide); the manifest records
that the catalog was not part of the archive.

Archives can contain access tokens (they hold ``config.json``) and are created with mode 0600.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from owl import __version__, paths
from owl.config import Config
from owl.fsutil import safe_relpath
from owl.models import OwlError

BACKUP_FORMAT = 1
MANIFEST = "manifest.json"
LOCAL_DB = "local.sqlite3"
CATALOG_DB = "catalog.sqlite3"
SCHEMA_LIMITS = {"catalog": 2, "local": 2}  #: highest schema versions this OWL understands


def backup_dir() -> Path:
    return paths.home() / "backups" / "archives"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot(db_path: Path) -> bytes:
    """A consistent copy of a (possibly open) SQLite database."""
    with tempfile.TemporaryDirectory(prefix="owl-snap-") as tmp:
        target = Path(tmp) / "snap.sqlite3"
        src = sqlite3.connect(db_path)
        try:
            dst = sqlite3.connect(target)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return target.read_bytes()


def _schema_versions(db_bytes: bytes) -> int | None:
    with tempfile.TemporaryDirectory(prefix="owl-ver-") as tmp:
        file = Path(tmp) / "v.sqlite3"
        file.write_bytes(db_bytes)
        conn = sqlite3.connect(file)
        try:
            row = conn.execute("select max(version) from owl_migrations").fetchone()
            return int(row[0]) if row and row[0] is not None else None
        except sqlite3.DatabaseError:
            return None
        finally:
            conn.close()


def _tree(root: Path) -> dict[str, bytes]:
    from owl.fsutil import read_tree

    return read_tree(root) if root.is_dir() else {}


def create_backup(
    cfg: Config, *, include_registries: bool = False, out: Path | None = None, label: str = ""
) -> Path:
    """Write a backup archive and return its path."""
    entries: dict[str, bytes] = {}
    notes: list[str] = []
    versions: dict[str, int | None] = {}
    home = paths.home()
    if paths.config_file().is_file():
        entries["config.json"] = paths.config_file().read_bytes()
    local_db = home / LOCAL_DB
    if local_db.is_file():
        data = _snapshot(local_db)
        entries[LOCAL_DB] = data
        versions["local"] = _schema_versions(data)
    backend = cfg.store.backend
    location = Path(cfg.store.location).expanduser()
    if backend == "sqlite" and location.is_file():
        data = _snapshot(location)
        entries[CATALOG_DB] = data
        versions["catalog"] = _schema_versions(data)
    elif backend == "git":
        for rel, data in _tree(location / "skills").items():
            entries[f"catalog-git/skills/{rel}"] = data
        notes.append("git catalog: only the skills/ files are included, not the .git history")
    elif backend == "postgres":
        notes.append("PostgreSQL catalog is NOT included: use pg_dump for the database")
    if paths.state_file().is_file():
        entries["state.json"] = paths.state_file().read_bytes()
    for rel, data in _tree(home / "formats").items():
        entries[f"formats/{rel}"] = data
    if include_registries:
        for registry_dir in (
            sorted((home / "registries").glob("*")) if (home / "registries").is_dir() else []
        ):
            for rel, data in _tree(registry_dir).items():
                entries[f"registries/{registry_dir.name}/{rel}"] = data
    manifest = {
        "format": BACKUP_FORMAT,
        "owl_version": __version__,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "backend": backend,
        "schema_versions": versions,
        "notes": notes,
        "files": [
            {"path": p, "sha256": _sha(d), "size": len(d)} for p, d in sorted(entries.items())
        ],
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"owl-backup{'-' + label if label else ''}-{stamp}.zip"
    target = (out or backup_dir()) if out is None or out.suffix != ".zip" else out
    archive = target / name if target.suffix != ".zip" else target
    archive.parent.mkdir(parents=True, exist_ok=True)
    tmp = archive.with_name(f".{archive.name}.owl-tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle, zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST, json.dumps(manifest, indent=2))
        for path, data in sorted(entries.items()):
            zf.writestr(path, data)
    tmp.replace(archive)
    return archive


@dataclass
class Verification:
    ok: bool
    problems: list[str] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)


def verify_backup(archive: Path) -> Verification:
    """Check structure, hashes, SQLite integrity and compatibility with this OWL version."""
    problems: list[str] = []
    manifest: dict[str, Any] = {}
    try:
        zf = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as exc:
        return Verification(False, [f"not a readable backup archive: {exc}"])
    with zf:
        bad = zf.testzip()
        if bad:
            problems.append(f"corrupt archive member: {bad}")
        try:
            manifest = json.loads(zf.read(MANIFEST))
        except (KeyError, ValueError):
            return Verification(False, [*problems, "manifest.json is missing or invalid"])
        if manifest.get("format") != BACKUP_FORMAT:
            problems.append(
                f"unsupported backup format {manifest.get('format')!r} (expected {BACKUP_FORMAT})"
            )
        listed = {f["path"]: f for f in manifest.get("files", [])}
        names = set(zf.namelist()) - {MANIFEST}
        for missing in sorted(set(listed) - names):
            problems.append(f"missing file: {missing}")
        for extra in sorted(names - set(listed)):
            problems.append(f"unlisted file in archive: {extra}")
        for path in sorted(names & set(listed)):
            data = zf.read(path)
            if _sha(data) != listed[path]["sha256"]:
                problems.append(f"hash mismatch: {path}")
            elif path.endswith(".sqlite3"):
                with tempfile.TemporaryDirectory(prefix="owl-chk-") as tmp:
                    file = Path(tmp) / "check.sqlite3"
                    file.write_bytes(data)
                    conn = sqlite3.connect(file)
                    try:
                        if conn.execute("pragma integrity_check").fetchone()[0] != "ok":
                            problems.append(f"SQLite integrity check failed: {path}")
                    except sqlite3.DatabaseError as exc:
                        problems.append(f"{path} is not a valid SQLite database: {exc}")
                    finally:
                        conn.close()
        for scope, version in (manifest.get("schema_versions") or {}).items():
            limit = SCHEMA_LIMITS.get(scope)
            if version is not None and limit is not None and version > limit:
                problems.append(
                    f"the {scope} database in this backup has schema version {version}, newer than "
                    f"this OWL understands ({limit}); upgrade OWL first"
                )
    return Verification(not problems, problems, manifest)


def list_backups() -> list[dict[str, Any]]:
    rows = []
    directory = backup_dir()
    for file in sorted(directory.glob("owl-backup*.zip")) if directory.is_dir() else []:
        try:
            with zipfile.ZipFile(file) as zf:
                manifest = json.loads(zf.read(MANIFEST))
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            manifest = {}
        rows.append(
            {
                "path": str(file),
                "size": file.stat().st_size,
                "created_at": manifest.get("created_at", ""),
                "owl_version": manifest.get("owl_version", "?"),
            }
        )
    return rows


def _destination(path: str, cfg_location: Path | None) -> Path | None:
    """Where an archive member goes. Anything not on this whitelist is never restored."""
    home = paths.home()
    if path == "config.json":
        return paths.config_file()
    if path == LOCAL_DB:
        return home / LOCAL_DB
    if path == CATALOG_DB:
        return cfg_location
    if path == "state.json":
        return paths.state_file()
    for prefix, base in (("formats/", home / "formats"), ("registries/", home / "registries")):
        if path.startswith(prefix):
            rel = safe_relpath(path[len(prefix) :])
            return base / rel
    if path.startswith("catalog-git/skills/") and cfg_location is not None:
        return cfg_location / "skills" / safe_relpath(path[len("catalog-git/skills/") :])
    return None


def restore_backup(archive: Path, cfg: Config, *, dry_run: bool = False) -> list[str]:
    """Restore *archive* after verifying it. A pre-restore backup of the current state is made first.

    Returns the restored paths. Nothing is changed when verification fails.
    """
    check = verify_backup(archive)
    if not check.ok:
        raise OwlError(
            "The backup is not valid, nothing was restored:\n  " + "\n  ".join(check.problems)
        )
    location = Path(cfg.store.location).expanduser() if cfg.store.location else None
    actions: list[tuple[str, Path]] = []
    with zipfile.ZipFile(archive) as zf:
        for name in sorted(set(zf.namelist()) - {MANIFEST}):
            dest = _destination(name, location)
            if dest is None:
                raise OwlError(f"Unexpected member in backup, refusing to restore: {name}")
            actions.append((name, dest))
        if dry_run:
            return [str(d) for _n, d in actions]
        create_backup(cfg, include_registries=True, label="pre-restore")
        restored: list[str] = []
        for name, dest in actions:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(f".{dest.name}.owl-restore")
            tmp.write_bytes(zf.read(name))
            if name == "config.json":
                tmp.chmod(0o600)
            tmp.replace(dest)
            restored.append(str(dest))
    # removing stale WAL/SHM files so the restored database is read as is
    for db in (paths.home() / LOCAL_DB, location) if location else (paths.home() / LOCAL_DB,):
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{db}{suffix}")
            if sidecar.exists():
                shutil.rmtree(sidecar, ignore_errors=True) if sidecar.is_dir() else sidecar.unlink()
    return restored
