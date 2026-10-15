"""Install targets: where each LLM tool / agent looks for skills.

All of these tools read the same Agent Skills layout (``<dir>/<name>/SKILL.md``); they only
differ in the directory. A *target* names the pair of directories (global for the user,
project for the current repository). Users can add their own in the config.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from owl.models import OwlError


@dataclass(frozen=True, slots=True)
class Target:
    name: str
    global_dir: str  #: user level, ``~`` is expanded
    project_dir: str  #: relative to the project root (the current directory)
    description: str

    def path(self, project: bool, root: Path | None = None) -> Path:
        if project:
            return (root or Path.cwd()) / self.project_dir
        return Path(self.global_dir).expanduser()


BUILTIN_TARGETS: dict[str, Target] = {
    t.name: t
    for t in (
        Target("claude", "~/.claude/skills", ".claude/skills", "Claude Code"),
        Target("opencode", "~/.config/opencode/skills", ".opencode/skills", "OpenCode"),
        Target("agents", "~/.agents/skills", ".agents/skills", "Cross-tool .agents standard"),
        Target("codex", "~/.agents/skills", ".agents/skills", "OpenAI Codex CLI"),
        Target("gemini", "~/.gemini/skills", ".gemini/skills", "Gemini CLI"),
        Target("copilot", "~/.copilot/skills", ".github/skills", "GitHub Copilot"),
        Target("cursor", "~/.cursor/skills", ".cursor/skills", "Cursor"),
    )
}

DEFAULT_TARGETS = ["claude"]


def all_targets(custom: dict[str, dict[str, str]] | None = None) -> dict[str, Target]:
    """Built-in targets plus those defined in the config (custom wins on name clashes)."""
    targets = dict(BUILTIN_TARGETS)
    for name, spec in (custom or {}).items():
        targets[name] = Target(
            name,
            spec.get("global", ""),
            spec.get("project", ""),
            spec.get("description", "custom target"),
        )
    return targets


def resolve_targets(
    names: list[str] | None,
    *,
    directory: str | None = None,
    project: bool = False,
    configured: list[str] | None = None,
    install_dir: str | None = None,
    custom: dict[str, dict[str, str]] | None = None,
) -> list[tuple[str, Path]]:
    """Turn CLI/config choices into ``(target name, directory)`` pairs.

    Precedence: an explicit directory, then ``--target`` names (``all`` = every known tool),
    then the configured custom ``install_dir`` (global scope only), then the configured targets.
    """
    if directory:
        return [("custom", Path(directory).expanduser())]
    known = all_targets(custom)
    chosen = names or None
    if chosen is None:
        if install_dir and not project:
            return [("custom", Path(install_dir).expanduser())]
        chosen = configured or DEFAULT_TARGETS
    if "all" in chosen:
        chosen = list(known)
    resolved: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for name in chosen:
        if name not in known:
            raise OwlError(f"Unknown target '{name}'. Known targets: {', '.join(sorted(known))}")
        target = known[name]
        if not (target.project_dir if project else target.global_dir):
            raise OwlError(f"Target '{name}' has no {'project' if project else 'global'} directory")
        path = target.path(project)
        if path not in seen:  # codex/agents share a directory: install once
            seen.add(path)
            resolved.append((name, path))
    return resolved
