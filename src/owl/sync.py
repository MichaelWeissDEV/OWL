"""Decide how a skill is synchronised between the local store and a remote."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Plan:
    action: str  #: "copy" | "noop" | "skip"
    reason: str


def plan_pull(local: str | None, remote: str | None, base: str | None, force: bool) -> Plan:
    """Plan a remote -> local transfer given the SHAs of both sides and the last synced SHA."""
    if remote is None:
        return Plan("skip", "not found on remote")
    if local == remote:
        return Plan("noop", "up to date")
    if local is None:
        return Plan("copy", "new")
    if force:
        return Plan("copy", "forced")
    if remote == base:
        return Plan("skip", "local is ahead of remote (push it, or pull --force)")
    if local == base:
        return Plan("copy", "updated on remote")
    return Plan("skip", "diverged: changed both locally and on the remote (use --force)")


def plan_push(local: str | None, remote: str | None, base: str | None, force: bool) -> Plan:
    """Plan a local -> remote transfer."""
    if local is None:
        return Plan("skip", "not found locally")
    if local == remote:
        return Plan("noop", "up to date")
    if remote is None:
        return Plan("copy", "new")
    if force:
        return Plan("copy", "forced")
    if local == base:
        return Plan("skip", "remote is ahead of local (pull it, or push --force)")
    if remote == base:
        return Plan("copy", "updated locally")
    return Plan("skip", "diverged: changed both locally and on the remote (use --force)")
