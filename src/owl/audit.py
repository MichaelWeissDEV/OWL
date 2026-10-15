"""Best-effort bookkeeping in the local database (history and installation inventory).

Failures here never break the operation that is being recorded.
"""

from __future__ import annotations

import sys
from pathlib import Path

from owl.localdb import LocalDB
from owl.models import Skill


def _safe(action: str, fn) -> None:  # type: ignore[no-untyped-def]
    try:
        with LocalDB() as db:
            fn(db)
    except Exception as exc:  # noqa: BLE001 - bookkeeping must not fail the user's command
        print(f"owl: could not record {action}: {exc}", file=sys.stderr)


def record(operation: str, ref: str | None, status: str = "ok", detail: str = "") -> None:
    _safe("history", lambda db: db.history_add(operation, ref, status, detail))


def record_install(
    skill: Skill,
    *,
    target: str,
    directory: Path,
    source: str,
    project: bool,
    custom: bool,
    registry: str | None = None,
    revision: str | None = None,
) -> None:
    scope = "custom" if custom else "project" if project else "global"

    def work(db: LocalDB) -> None:
        db.installation_record(
            ref=skill.ref,
            name=skill.name,
            target=target,
            directory=str(directory),
            scope=scope,
            project_root=str(directory.parent.parent) if scope == "project" else None,
            version=skill.version,
            sha256=skill.sha256,
            source=source,
            registry=registry,
            revision=revision,
        )
        db.history_add("install", skill.ref, "ok", f"{target}: {directory}")

    _safe("installation", work)


def forget_install(ref: str | None, directory: Path, target: str) -> None:
    def work(db: LocalDB) -> None:
        db.installation_forget(str(directory))
        db.history_add("uninstall", ref, "ok", f"{target}: {directory}")

    _safe("uninstall", work)


def provenance_for(skill: Skill) -> dict | None:
    """Where *skill* came from: its transient provenance, else the recorded import provenance
    (only if it was recorded for exactly this content)."""
    if skill.provenance:
        return skill.provenance
    try:
        with LocalDB() as db:
            recorded = db.provenance_get(skill.ref)
    except Exception:  # noqa: BLE001
        return None
    if recorded and recorded.get("sha256") == skill.sha256:
        return {k: v for k, v in recorded.items() if k != "sha256"} | {"sha256": skill.sha256}
    return None
