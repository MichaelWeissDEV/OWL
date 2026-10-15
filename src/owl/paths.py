"""Locations of OWL's own files. Everything lives below ``OWL_HOME`` (default ``~/.owl``)."""

from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("OWL_HOME") or "~/.owl").expanduser()


def config_file() -> Path:
    return home() / "config.json"


def state_file() -> Path:
    return home() / "state.json"


def default_db() -> Path:
    return home() / "skills.sqlite3"


def default_repo() -> Path:
    return home() / "repo"
