"""Configuration (``$OWL_HOME/config.json``) and per-machine state (sync bookmarks, caches)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from owl import paths
from owl.models import NotFound, OwlError

MODES = ("standalone", "client", "server")
BACKENDS = ("sqlite", "postgres", "git")
DEFAULT_INSTALL_DIR = "~/.claude/skills"


@dataclass
class Remote:
    url: str
    token: str | None = None
    token_env: str | None = None  #: read the token from this environment variable instead

    def resolved_token(self) -> str | None:
        if self.token_env:
            return os.environ.get(self.token_env)
        return self.token


@dataclass
class StoreConfig:
    backend: str = "sqlite"
    #: sqlite: file path / URL; postgres: SQLAlchemy/libpq URL; git: working copy path
    location: str = ""
    #: git backend only: URL of the remote repository to sync with
    git_url: str | None = None
    #: postgres only: read the URL from this environment variable (keeps passwords out of the file)
    url_env: str | None = None


@dataclass
class Config:
    mode: str = "standalone"
    author: str = "local"
    store: StoreConfig = field(default_factory=StoreConfig)
    remotes: dict[str, Remote] = field(default_factory=dict)
    default_remote: str | None = None
    install_dir: str = DEFAULT_INSTALL_DIR

    def remote(self, name: str) -> Remote:
        try:
            return self.remotes[name]
        except KeyError:
            raise NotFound(f"Unknown remote '{name}' (see: owl remote list)") from None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "author": self.author,
            "store": {k: v for k, v in vars(self.store).items() if v is not None},
            "remotes": {
                n: {k: v for k, v in vars(r).items() if v is not None}
                for n, r in self.remotes.items()
            },
            "default_remote": self.default_remote,
            "install_dir": self.install_dir,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        store = StoreConfig(**data.get("store", {}))
        remotes = {n: Remote(**r) for n, r in data.get("remotes", {}).items()}
        return cls(
            mode=data.get("mode", "standalone"),
            author=data.get("author", "local"),
            store=store,
            remotes=remotes,
            default_remote=data.get("default_remote"),
            install_dir=data.get("install_dir", DEFAULT_INSTALL_DIR),
        )


def load_config() -> Config:
    """Load the config; a missing file yields the defaults (a SQLite DB below OWL_HOME)."""
    file = paths.config_file()
    config = Config()
    if file.is_file():
        try:
            config = Config.from_dict(json.loads(file.read_text("utf-8")))
        except (ValueError, TypeError) as exc:
            raise OwlError(f"Invalid config file {file}: {exc}") from exc
    if not config.store.location:
        config.store.location = str(
            paths.default_repo() if config.store.backend == "git" else paths.default_db()
        )
    return config


def save_config(config: Config) -> None:
    """Write the config with mode 0600 (it may contain remote tokens)."""
    file = paths.config_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(config.to_dict(), handle, indent=2)
        handle.write("\n")
    tmp.replace(file)


# -- state: sync bookmarks and completion cache ------------------------------------------


def load_state() -> dict[str, Any]:
    file = paths.state_file()
    try:
        data = json.loads(file.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    file = paths.state_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), "utf-8")
    tmp.replace(file)


def get_synced(remote: str, ref: str) -> str | None:
    """SHA of *ref* as of the last successful pull/push with *remote*."""
    return load_state().get("synced", {}).get(remote, {}).get(ref)


def set_synced(remote: str, ref: str, sha: str | None) -> None:
    state = load_state()
    bucket = state.setdefault("synced", {}).setdefault(remote, {})
    if sha is None:
        bucket.pop(ref, None)
    else:
        bucket[ref] = sha
    save_state(state)


def update_completion_cache(summaries: list[Any]) -> None:
    """Remember names/authors/tags/topics seen in listings so TAB completion can offer them."""
    try:
        state = load_state()
        cache = state.setdefault(
            "completion", {"refs": [], "tags": [], "topics": [], "authors": []}
        )
        cache["refs"] = sorted(set(cache["refs"]) | {s.ref for s in summaries})[:5000]
        cache["authors"] = sorted(set(cache["authors"]) | {s.author for s in summaries})
        cache["tags"] = sorted(set(cache["tags"]) | {t for s in summaries for t in s.tags})
        cache["topics"] = sorted(set(cache["topics"]) | {t for s in summaries for t in s.topics})
        save_state(state)
    except Exception:  # noqa: BLE001 - the cache is best effort only
        pass


def expand(path: str) -> Path:
    return Path(path).expanduser()
