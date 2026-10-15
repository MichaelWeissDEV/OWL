"""Thin wrapper around the ``git`` command line."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from owl.models import OwlError

COMMIT_RE = re.compile(r"[0-9a-f]{7,40}")
URL_RE = re.compile(r"^(https?|ssh|git|file)://|^git@[\w.-]+:")


def is_git_url(source: str) -> bool:
    return bool(URL_RE.match(source))


def _git(
    args: list[str], cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess:
    if shutil.which("git") is None:
        raise OwlError("git is not installed or not on PATH")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, env=env, check=False
    )
    if check and proc.returncode != 0:
        raise OwlError(f"git {' '.join(args[:2])} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc


def clone(url: str, dest: Path, ref: str | None = None, depth: int | None = 1) -> None:
    """Clone *url* into *dest* (shallow by default)."""
    args = ["clone", "--quiet"]
    commit_ref = bool(ref and COMMIT_RE.fullmatch(ref))
    if depth and not commit_ref:
        args += ["--depth", str(depth)]
    if ref and not commit_ref:
        args += ["--branch", ref]
    _git([*args, "--", url, str(dest)])
    if commit_ref:
        _git(["checkout", "--quiet", "--detach", str(ref)], cwd=dest)


def is_repo(path: Path) -> bool:
    return (path / ".git").exists()


def init(path: Path, branch: str | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "--quiet", *(["-b", branch] if branch else [])], cwd=path)


def set_remote(path: Path, url: str) -> None:
    existing = _git(["remote", "get-url", "origin"], cwd=path, check=False)
    if existing.returncode == 0:
        _git(["remote", "set-url", "origin", url], cwd=path)
    else:
        _git(["remote", "add", "origin", url], cwd=path)


def remote_url(path: Path) -> str | None:
    proc = _git(["remote", "get-url", "origin"], cwd=path, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def has_remote(path: Path) -> bool:
    return _git(["remote", "get-url", "origin"], cwd=path, check=False).returncode == 0


def is_dirty(path: Path) -> bool:
    return bool(_git(["status", "--porcelain"], cwd=path).stdout.strip())


def commit_all(path: Path, message: str) -> bool:
    """Stage and commit everything; returns ``False`` when there was nothing to commit."""
    if not is_dirty(path):
        return False
    _git(["add", "-A"], cwd=path)
    _git(
        [
            "-c",
            "user.name=" + (_config(path, "user.name") or "owl"),
            "-c",
            "user.email=" + (_config(path, "user.email") or "owl@localhost"),
            "commit",
            "--quiet",
            "-m",
            message,
        ],
        cwd=path,
    )
    return True


def _config(path: Path, key: str) -> str:
    return _git(["config", key], cwd=path, check=False).stdout.strip()


def current_branch(path: Path) -> str:
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path).stdout.strip()


def has_commits(path: Path) -> bool:
    return _git(["rev-parse", "--verify", "HEAD"], cwd=path, check=False).returncode == 0


def pull(path: Path) -> None:
    """Fetch and rebase onto the upstream; aborts the rebase on conflicts."""
    branch = current_branch(path)
    fetch = _git(["fetch", "--quiet", "origin"], cwd=path)
    del fetch
    remote_ref = f"origin/{branch}"
    if _git(["rev-parse", "--verify", remote_ref], cwd=path, check=False).returncode != 0:
        return  # remote branch does not exist yet (first push)
    proc = _git(["rebase", remote_ref], cwd=path, check=False)
    if proc.returncode != 0:
        _git(["rebase", "--abort"], cwd=path, check=False)
        raise OwlError(
            "Merge conflict while syncing - resolve it manually in "
            f"{path} (git pull --rebase), then run sync again.\n{proc.stderr.strip()}"
        )


def push(path: Path) -> None:
    _git(["push", "--quiet", "-u", "origin", "HEAD"], cwd=path)


def fetch_reset(path: Path, ref: str | None = None) -> None:
    """Update a shallow clone to the latest commit of *ref* (default: the remote's HEAD)."""
    _git(["fetch", "--quiet", "--depth", "1", "origin", ref or "HEAD"], cwd=path)
    _git(["reset", "--quiet", "--hard", "FETCH_HEAD"], cwd=path)


def head_commit(path: Path) -> str | None:
    """SHA of ``HEAD`` in the repository at *path*, or ``None``."""
    proc = _git(["rev-parse", "HEAD"], cwd=path, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def clone_at(url: str, dest: Path, commit: str) -> None:
    """Check out exactly *commit* of *url* into *dest* (shallow when the server allows it)."""
    if not COMMIT_RE.fullmatch(commit):
        raise OwlError(f"Not a commit id: {commit!r}")
    dest.mkdir(parents=True, exist_ok=True)
    _git(["init", "--quiet"], cwd=dest)
    _git(["remote", "add", "origin", url], cwd=dest)
    shallow = _git(["fetch", "--quiet", "--depth", "1", "origin", commit], cwd=dest, check=False)
    if shallow.returncode != 0:  # some servers refuse fetching arbitrary commits: fetch everything
        _git(["fetch", "--quiet", "origin"], cwd=dest)
    _git(["checkout", "--quiet", "--detach", commit], cwd=dest)
    if head_commit(dest) != commit and not (head_commit(dest) or "").startswith(commit):
        raise OwlError(f"Could not check out {commit} from {url}")


def ls_remote(url: str, timeout: float = 30) -> list[str]:
    """Heads/tags of a remote (used to check reachability); raises :class:`OwlError`."""
    if shutil.which("git") is None:
        raise OwlError("git is not installed or not on PATH")
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--heads", "--tags", url],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        raise OwlError(f"{url} did not answer within {timeout:.0f}s") from exc
    if proc.returncode != 0:
        raise OwlError(proc.stderr.strip() or f"git ls-remote failed for {url}")
    return [line.split("\t", 1)[1] for line in proc.stdout.splitlines() if "\t" in line]


def current_ref(path: Path) -> str:
    """Branch name of the checkout (or ``HEAD`` when detached)."""
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path).stdout.strip()


def create_branch(path: Path, name: str) -> None:
    _git(["checkout", "--quiet", "-b", name], cwd=path)


def push_branch(path: Path, branch: str) -> None:
    """Push *branch* to origin. Never forces."""
    _git(["push", "--quiet", "-u", "origin", branch], cwd=path)
