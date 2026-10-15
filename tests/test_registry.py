from __future__ import annotations

import json
import subprocess

import pytest
from typer.testing import CliRunner

from owl import gitutil, registry
from owl.cli import app
from owl.config import DEFAULT_REGISTRY_URL, load_config
from owl.models import OwlError, SearchQuery
from owl.parsing import write_skill_dir
from owl.stores.registry import RegistryStore
from owl.targets import BUILTIN_TARGETS, resolve_targets
from tests.conftest import make_skill

runner = CliRunner()


def owl(*args, ok=True):
    result = runner.invoke(app, list(args))
    if ok:
        assert result.exit_code == 0, result.output
    return result


@pytest.fixture
def reg(tmp_path):
    """A local registry with two published skills."""
    root = registry.init_registry(tmp_path / "myreg", name="myreg", description="Test registry")
    write_skill_dir(
        make_skill("git-helper", "alice", tags=["git"], topics=["devtools"]), tmp_path / "s" / "g"
    )
    write_skill_dir(make_skill("sql-tuner", "bob", tags=["sql"]), tmp_path / "s" / "q")
    owl("registry", "publish", str(tmp_path / "s"), "--dir", str(root))
    return root


# -- registry repository ------------------------------------------------------------------
def test_init_creates_layout_ci_and_commit(tmp_path):
    root = registry.init_registry(tmp_path / "r", git_url="https://example.invalid/r.git")
    for name in (
        "registry.json",
        "index.json",
        "INDEX.md",
        "README.md",
        ".github/workflows/registry.yml",
    ):
        assert (root / name).is_file(), name
    assert gitutil.has_commits(root) and not gitutil.is_dirty(root)
    assert "owl registry index" in (root / ".github/workflows/registry.yml").read_text()
    with pytest.raises(OwlError):
        registry.init_registry(root)


def test_index_content_and_markdown(reg):
    index = json.loads((reg / "index.json").read_text())
    assert index["count"] == 2 and index["name"] == "myreg"
    entry = {e["ref"]: e for e in index["skills"]}["alice/git-helper"]
    assert entry["path"] == "skills/alice/git-helper" and entry["tags"] == ["git"]
    assert len(entry["sha256"]) == 64 and entry["updated_at"]
    md = (reg / "INDEX.md").read_text()
    assert "[`alice/git-helper`](skills/alice/git-helper/SKILL.md)" in md and "2 skills" in md


def test_index_is_stable_and_detects_staleness(reg):
    first = (reg / "index.json").read_text()
    registry.write_index(reg)
    assert (reg / "index.json").read_text() == first  # deterministic, no churn
    assert registry.index_is_current(reg)
    write_skill_dir(make_skill("new-one", "alice"), reg / "skills" / "alice" / "new-one")
    assert not registry.index_is_current(reg)
    assert owl("registry", "index", str(reg), "--check", ok=False).exit_code == 1
    owl("registry", "index", str(reg))
    assert owl("registry", "index", str(reg), "--check").exit_code == 0


def test_updated_at_follows_git_commit_time(reg):
    gitutil.commit_all(reg, "add skills")
    skill_md = reg / "skills" / "alice" / "git-helper" / "SKILL.md"
    skill_md.write_text(skill_md.read_text() + "\nmore\n")
    subprocess.run(["git", "add", "-A"], cwd=reg, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-qm",
            "edit",
            "--date=2030-01-02T03:04:05+00:00",
        ],
        cwd=reg,
        check=True,
        env={
            "GIT_COMMITTER_DATE": "2030-01-02T03:04:05+00:00",
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        },
    )
    index = registry.write_index(reg)
    entry = {e["ref"]: e for e in index["skills"]}["alice/git-helper"]
    assert entry["updated_at"].startswith("2030-01-02T03:04:05")


def test_publish_requires_registry_and_valid_skills(tmp_path):
    write_skill_dir(make_skill("x"), tmp_path / "x")
    assert (
        owl("registry", "publish", str(tmp_path / "x"), "--dir", str(tmp_path), ok=False).exit_code
        != 0
    )


# -- registry as a store ------------------------------------------------------------------
def test_registry_store_from_directory(reg, tmp_path):
    store = RegistryStore(str(reg), "r", tmp_path / "cache")
    assert [s.ref for s in store.search(SearchQuery(tags=["git"]))] == ["alice/git-helper"]
    assert store.facets("author") == [("alice", 1), ("bob", 1)]
    skill = store.get("bob", "sql-tuner")
    assert skill is not None and skill.sha256 == make_skill("sql-tuner", "bob", tags=["sql"]).sha256
    assert store.resolve("sql-tuner") == ("bob", "sql-tuner")
    with pytest.raises(OwlError, match="read-only"):
        store.upsert(skill)
    assert store.info()["indexed"] is True


def test_registry_without_index_is_scanned(tmp_path):
    write_skill_dir(make_skill("plain", "carol"), tmp_path / "repo" / "anything" / "plain")
    store = RegistryStore(str(tmp_path / "repo"), "plain", tmp_path / "cache")
    assert [s.ref for s in store.search(SearchQuery(text="plain"))] == ["carol/plain"]
    assert store.info()["indexed"] is False


def test_registry_store_from_git_url_and_refresh(reg, tmp_path):
    gitutil.commit_all(reg, "x")
    url = f"file://{reg}"
    cache = tmp_path / "cache"
    store = RegistryStore(url, "g", cache)
    assert store.count() == 2
    # new commit upstream; within the TTL the cache is used, an explicit update refetches
    write_skill_dir(make_skill("third", "alice"), reg / "skills" / "alice" / "third")
    registry.write_index(reg)
    gitutil.commit_all(reg, "third")
    assert RegistryStore(url, "g", cache).count() == 2
    fresh = RegistryStore(url, "g", cache)
    fresh.update()
    assert fresh.count() == 3


def test_registry_offline_uses_cache(reg, tmp_path):
    gitutil.commit_all(reg, "x")
    cache = tmp_path / "cache"
    RegistryStore(f"file://{reg}", "g", cache).count()
    store = RegistryStore(f"file://{tmp_path}/gone", "g", cache, ttl=0)
    assert store.count() == 2 and store.warnings


def test_unreachable_registry_without_cache_fails(tmp_path):
    with pytest.raises(OwlError, match="Cannot fetch"):
        RegistryStore(f"file://{tmp_path}/nope", "g", tmp_path / "cache").count()


# -- CLI integration ----------------------------------------------------------------------
def test_default_registry_on_fresh_install(monkeypatch, owl_home):
    monkeypatch.delenv("OWL_DEFAULT_REGISTRY")
    cfg = load_config()
    assert cfg.remotes["owl"].kind == "registry" and cfg.remotes["owl"].url == DEFAULT_REGISTRY_URL
    monkeypatch.setenv("OWL_DEFAULT_REGISTRY", "")
    assert "owl" not in load_config().remotes


def test_search_show_install_from_registry(reg, tmp_path):
    owl("init", "--mode", "client")
    owl("registry", "add", "myreg", str(reg))
    assert "myreg" in owl("registry", "list").stdout
    assert "registry" in owl("remote", "list").stdout
    found = json.loads(owl("search", "git", "-r", "myreg", "--json").stdout)
    assert [f["ref"] if "ref" in f else f"{f['author']}/{f['name']}" for f in found] == [
        "alice/git-helper"
    ]
    pushed = owl("push", "alice/git-helper", "-r", "myreg", ok=False)
    assert pushed.exit_code != 0 and "read-only" in str(pushed.exception)
    claude, opencode = tmp_path / "c", tmp_path / "o"
    owl("install", "--all", "-r", "myreg", "--dir", str(claude))
    assert {p.name for p in claude.iterdir()} == {"git-helper", "sql-tuner"}
    owl("install", "git-helper", "-r", "myreg", "--dir", str(opencode))
    owl("pull", "bob/sql-tuner", "-r", "myreg")
    assert "bob/sql-tuner" in owl("list", "--local").stdout


def test_install_all_with_filters(reg, tmp_path):
    owl("init")
    owl("registry", "add", "myreg", str(reg))
    out = tmp_path / "out"
    owl("install", "--all", "-r", "myreg", "--tag", "sql", "--dir", str(out))
    assert [p.name for p in out.iterdir()] == ["sql-tuner"]
    assert owl("install", "--all", "-r", "myreg", "--author", "nobody", ok=False).exit_code != 0
    assert owl("install", ok=False).exit_code != 0


# -- targets ------------------------------------------------------------------------------
def test_target_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resolve_targets(None)[0][1].parts[-2:] == (".claude", "skills")
    oc = dict(resolve_targets(["opencode"]))["opencode"]
    assert oc.parts[-3:] == ("opencode", "skills") or oc.parts[-2:] == ("opencode", "skills")
    assert (
        dict(resolve_targets(["opencode"], project=True))["opencode"]
        == tmp_path / ".opencode/skills"
    )
    assert len(resolve_targets(["all"])) == len({t.global_dir for t in BUILTIN_TARGETS.values()})
    assert resolve_targets(["claude"], directory=str(tmp_path / "x"))[0][0] == "custom"
    with pytest.raises(OwlError, match="Unknown target"):
        resolve_targets(["emacs"])


def test_install_for_several_tools_in_project(reg, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    owl("init")
    owl("registry", "add", "myreg", str(reg))
    owl(
        "install",
        "git-helper",
        "-r",
        "myreg",
        "-p",
        "-t",
        "claude",
        "-t",
        "opencode",
        "-t",
        "cursor",
    )
    for d in (".claude", ".opencode", ".cursor"):
        assert (tmp_path / d / "skills" / "git-helper" / "SKILL.md").is_file()
    listing = owl("installed", "-p", "-t", "all").stdout
    assert listing.count("alice/git-helper") == 3
    owl("uninstall", "git-helper", "-p", "-t", "opencode")
    assert not (tmp_path / ".opencode/skills/git-helper").exists()
    assert (tmp_path / ".claude/skills/git-helper").exists()


def test_configured_targets_and_custom_target(reg, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    owl("init", "--target", "opencode")
    assert load_config().targets == ["opencode"]
    assert owl("config", "set", "targets", "claude,gemini").exit_code == 0
    assert owl("config", "set", "targets", "claude,nope", ok=False).exit_code != 0
    assert "gemini" in owl("targets").stdout
    cfg_file = tmp_path / "owl-home" / "config.json"
    data = json.loads(cfg_file.read_text())
    data["custom_targets"] = {
        "mytool": {"global": str(tmp_path / "g"), "project": ".mytool/skills"}
    }
    cfg_file.write_text(json.dumps(data))
    owl("registry", "add", "myreg", str(reg))
    owl("install", "git-helper", "-r", "myreg", "-t", "mytool")
    assert (tmp_path / "g" / "git-helper" / "SKILL.md").is_file()
