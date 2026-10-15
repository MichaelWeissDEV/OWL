"""Skill storage backends and the factory that opens the configured one."""

from __future__ import annotations

import os

from owl.config import Config, StoreConfig
from owl.models import OwlError
from owl.stores.base import SkillStore


def open_store(cfg: StoreConfig, label: str = "local") -> SkillStore:
    """Open the store described by *cfg*."""
    if cfg.backend == "git":
        from owl.stores.directory import DirectoryStore

        return DirectoryStore(cfg.location, label=label)
    from owl.stores.sql import SqlStore

    location = cfg.location
    if cfg.backend == "postgres":
        if cfg.url_env:
            location = os.environ.get(cfg.url_env, "")
            if not location:
                raise OwlError(f"Environment variable {cfg.url_env} is not set")
        if "://" not in location:
            raise OwlError("The postgres backend needs a URL like postgresql://user@host/db")
    try:
        return SqlStore(location, label=label)
    except ModuleNotFoundError as exc:
        if cfg.backend == "postgres" or "psycopg" in str(exc):
            raise OwlError("PostgreSQL support is missing: pip install 'owl[postgres]'") from exc
        raise


def open_remote(config: Config, name: str) -> SkillStore:
    """Open the configured remote *name* as a store."""
    from owl import paths
    from owl.stores.registry import RegistryStore
    from owl.stores.remote import RemoteStore

    remote = config.remote(name)
    if remote.kind == "registry":
        return RegistryStore(remote.url, name, paths.home() / "registries" / name, ref=remote.ref)
    return RemoteStore(remote.url, remote.resolved_token(), label=name)


__all__ = ["SkillStore", "open_remote", "open_store"]
