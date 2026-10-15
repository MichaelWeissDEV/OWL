"""Shell completion callbacks.

These run on every ``owl <TAB>``, so they must be fast, must never touch the network,
must never create files and must never raise: any failure simply yields no suggestions.
Suggestions come from the local store (SQLite / git working copy, when it already exists)
plus a small cache that is refreshed whenever a listing or search ran against a remote.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path

_KIND = {"refs": None, "authors": "author", "tags": "tag", "topics": "topic"}


def _local_values(kind: str) -> set[str]:
    from owl.config import load_config

    cfg = load_config().store
    if cfg.backend == "postgres":
        return set()  # never connect to a database server while completing
    if not Path(cfg.location).exists():
        return set()
    from owl.stores import open_store

    store = open_store(cfg)
    try:
        if kind == "refs":
            summaries = store.list()
            return {s.ref for s in summaries} | {s.name for s in summaries}
        return {v for v, _n in store.facets(_KIND[kind])}  # type: ignore[arg-type]
    finally:
        store.close()


def _cached_values(kind: str) -> set[str]:
    from owl.config import load_state

    values = set(load_state().get("completion", {}).get(kind, []))
    if kind == "refs":
        values |= {v.partition("/")[2] for v in values}
    return values


def _complete(kind: str, incomplete: str) -> list[str]:
    try:
        values = _cached_values(kind)
        with contextlib.suppress(Exception):
            values |= _local_values(kind)
        return sorted(v for v in values if v.lower().startswith(incomplete.lower()))[:200]
    except Exception:  # noqa: BLE001
        return []


def _make(kind: str) -> Callable[[str], list[str]]:
    def callback(incomplete: str) -> list[str]:
        return _complete(kind, incomplete)

    return callback


complete_ref = _make("refs")
complete_author = _make("authors")
complete_tag = _make("tags")
complete_topic = _make("topics")


def complete_remote(incomplete: str) -> list[str]:
    try:
        from owl.config import load_config

        return sorted(n for n in load_config().remotes if n.startswith(incomplete))
    except Exception:  # noqa: BLE001
        return []


def complete_target(incomplete: str) -> list[str]:
    try:
        from owl.config import load_config
        from owl.targets import all_targets

        names = [*all_targets(load_config().custom_targets), "all"]
        return sorted(n for n in names if n.startswith(incomplete))
    except Exception:  # noqa: BLE001
        return []


def complete_installed(incomplete: str) -> list[str]:
    try:
        from owl.config import load_config
        from owl.installer import list_installed
        from owl.targets import resolve_targets

        cfg = load_config()
        dirs = resolve_targets(
            None, configured=cfg.targets, install_dir=cfg.install_dir, custom=cfg.custom_targets
        )
        names = {i.name for _t, d in dirs for i in list_installed(d)}
        return sorted(n for n in names if n.startswith(incomplete))
    except Exception:  # noqa: BLE001
        return []
