from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from owl import completion, gitutil
from owl.cli import app
from owl.parsing import write_skill_dir
from tests.conftest import make_skill

runner = CliRunner()


def owl(*args, ok=True):
    result = runner.invoke(app, list(args))
    if ok:
        assert result.exit_code == 0, result.output
    return result


@pytest.fixture
def lib(tmp_path):
    """A directory with two skills, and an initialised standalone OWL."""
    write_skill_dir(
        make_skill("git-helper", "alice", tags=["git"], topics=["devtools"]), tmp_path / "lib" / "g"
    )
    write_skill_dir(make_skill("sql-tuner", "bob", tags=["sql"]), tmp_path / "lib" / "s")
    owl("init", "--author", "tester")
    owl("add", str(tmp_path / "lib"))
    return tmp_path / "lib"


def test_search_list_show_json(lib):
    data = json.loads(owl("search", "--author", "alice", "--json").stdout)
    assert [d["name"] for d in data] == ["git-helper"]
    assert json.loads(owl("search", "-t", "sql", "--json").stdout)[0]["author"] == "bob"
    assert len(json.loads(owl("list", "--json").stdout)) == 2
    assert owl("show", "git-helper", "--raw").stdout.startswith("---\nname: git-helper")
    assert "alice\t1" in owl("authors").stdout
    assert owl("show", "nope", ok=False).exit_code != 0


def test_install_remove_flow(lib, tmp_path):
    target = tmp_path / "skills"
    owl("install", "alice/git-helper", "--dir", str(target))
    assert (target / "git-helper" / "SKILL.md").is_file()
    assert "alice/git-helper" in owl("installed", "--dir", str(target)).stdout
    owl("uninstall", "git-helper", "--dir", str(target))
    assert not (target / "git-helper").exists()
    # a multi-skill directory needs --skill or --all
    assert owl("install", str(lib), "--dir", str(target), ok=False).exit_code != 0
    owl("install", str(lib), "--all", "--dir", str(target))
    assert (target / "sql-tuner").is_dir()
    owl("remove", "bob/sql-tuner", "--yes")
    assert "sql-tuner" not in owl("list").stdout


def test_validate_command(tmp_path):
    write_skill_dir(make_skill("fine"), tmp_path / "fine")
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "SKILL.md").write_text("no frontmatter")
    assert owl("validate", str(tmp_path / "fine")).exit_code == 0
    assert owl("validate", str(tmp_path / "broken"), ok=False).exit_code == 1


def test_new_scaffold(tmp_path):
    owl("init")
    owl("new", "fresh-skill", "--dir", str(tmp_path), "-t", "demo")
    owl("validate", str(tmp_path / "fresh-skill"))
    assert (tmp_path / "fresh-skill" / "SKILL.md").read_text().startswith("---\nname: fresh-skill")


def test_config_is_private_and_hides_tokens(tmp_path):
    from owl import paths

    owl("init", "--mode", "client")
    owl("remote", "add", "x", "http://example.invalid", "--token", "topsecret")
    assert (paths.config_file().stat().st_mode & 0o777) == 0o600
    assert "topsecret" not in owl("config", "show").stdout
    owl("remote", "remove", "x")


def test_completion_reads_local_data_only(lib, owl_home):
    assert "alice/git-helper" in completion.complete_ref("al")
    assert "git-helper" in completion.complete_ref("git")
    assert completion.complete_tag("s") == ["sql"]
    assert completion.complete_author("b") == ["bob"]


def test_completion_never_creates_files_or_raises(owl_home):
    assert completion.complete_ref("") == []
    assert completion.complete_remote("") == []
    assert not owl_home.exists()


def test_git_backend_sync(tmp_path, monkeypatch):
    bare = tmp_path / "origin.git"
    gitutil._git(["init", "--bare", "--quiet", str(bare)])
    owl("init", "--backend", "git", "--git-url", f"file://{bare}")
    write_skill_dir(make_skill("gitted", "alice"), tmp_path / "src" / "gitted")
    owl("add", str(tmp_path / "src"))
    owl("sync")
    # a second machine clones the same repo and sees the skill
    clone = tmp_path / "clone"
    gitutil.clone(f"file://{bare}", clone, depth=None)
    assert (clone / "skills" / "gitted" / "SKILL.md").is_file()
    # installing straight from the git URL works too
    target = tmp_path / "inst"
    owl("install", f"file://{bare}", "--dir", str(target))
    assert (target / "gitted" / "SKILL.md").is_file()


def test_sync_requires_git_backend():
    owl("init")
    assert owl("sync", ok=False).exit_code == 1


def test_git_sync_conflict_aborts_cleanly(tmp_path, monkeypatch):
    """Two machines edit the same skill: the second sync fails and leaves no rebase behind."""
    bare = tmp_path / "origin.git"
    gitutil._git(["init", "--bare", "--quiet", "-b", "main", str(bare)])
    url = f"file://{bare}"
    skill_dir = tmp_path / "src" / "shared"
    write_skill_dir(make_skill("shared", "alice"), skill_dir)

    monkeypatch.setenv("OWL_HOME", str(tmp_path / "a"))
    owl("init", "--backend", "git", "--git-url", url)
    owl("add", str(tmp_path / "src"))
    owl("sync")

    monkeypatch.setenv("OWL_HOME", str(tmp_path / "b"))
    owl("init", "--backend", "git", "--git-url", url, "--location", str(tmp_path / "b-repo"))
    write_skill_dir(
        make_skill("shared", "alice", description="edit from b"), tmp_path / "b-src" / "shared"
    )
    owl("add", str(tmp_path / "b-src"))
    owl("sync")

    monkeypatch.setenv("OWL_HOME", str(tmp_path / "a"))
    write_skill_dir(
        make_skill("shared", "alice", description="edit from a"), tmp_path / "a-src" / "shared"
    )
    owl("add", str(tmp_path / "a-src"))
    result = owl("sync", ok=False)
    assert result.exit_code != 0
    repo = tmp_path / "a" / "repo"
    assert not (repo / ".git" / "rebase-merge").exists()
    assert not (repo / ".git" / "rebase-apply").exists()


def test_invalid_hand_edited_skill_is_reported(tmp_path, capsys):
    from owl.stores.directory import DirectoryStore

    store = DirectoryStore(tmp_path)
    store.upsert(make_skill("ok"))
    (tmp_path / "skills" / "ok" / "SKILL.md").write_text("broken")
    DirectoryStore(tmp_path).list()
    assert "ignoring invalid skill" in capsys.readouterr().err


def test_config_get_set(owl_home):
    owl("init")
    owl("config", "set", "author", "Neo")
    assert owl("config", "get", "author").stdout.strip() == "neo"
    assert owl("config", "set", "mode", "bogus", ok=False).exit_code != 0
    assert owl("config", "set", "store", "x", ok=False).exit_code != 0
    assert owl("config", "path").stdout.strip().endswith("config.json")


def test_update_outdated_and_export(lib, tmp_path):
    target = tmp_path / "skills"
    owl("install", "alice/git-helper", "--dir", str(target))
    assert owl("outdated", "--dir", str(target)).exit_code == 0
    # change the skill in the library -> the installed copy is now outdated
    write_skill_dir(
        make_skill("git-helper", "alice", description="new text"), tmp_path / "v2" / "g"
    )
    owl("add", str(tmp_path / "v2"))
    assert owl("outdated", "--dir", str(target), ok=False).exit_code == 1
    assert "would update" in owl("update", "--dir", str(target), "--dry-run").stdout
    assert "updated" in owl("update", "--dir", str(target)).stdout
    assert owl("outdated", "--dir", str(target)).exit_code == 0
    owl("export", "--all", "-o", str(tmp_path / "out"), "--layout", "repo")
    assert (tmp_path / "out" / "skills" / "git-helper" / "skill.json").is_file()


def test_stats_and_doctor(lib):
    assert '"skills": 2' in owl("stats", "--json").stdout
    assert owl("doctor", ok=False).exit_code == 0


def test_diff_against_remote(lib, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient as TC

    from owl import stores
    from owl.server import create_app
    from owl.stores.remote import RemoteStore
    from owl.stores.sql import SqlStore

    srv = SqlStore(str(tmp_path / "srv.db"))
    srv.upsert(make_skill("git-helper", "alice", description="remote text"))
    client = TC(create_app(srv, token="t"))
    owl("remote", "add", "r", "http://testserver", "--token", "t")
    monkeypatch.setattr(
        "owl.cli_tools.open_remote",
        lambda cfg, name: RemoteStore("http://testserver", "t", label=name, client=client),
    )
    result = owl("diff", "git-helper", "-r", "r", ok=False)
    assert result.exit_code == 1 and "remote text" in result.stdout
    assert stores  # keep import used


def test_update_skips_locally_modified_installs(lib, tmp_path):
    target = tmp_path / "skills"
    owl("install", "alice/git-helper", "--dir", str(target))
    (target / "git-helper" / "SKILL.md").write_text("hand edited")
    write_skill_dir(
        make_skill("git-helper", "alice", description="new text"), tmp_path / "v2" / "g"
    )
    owl("add", str(tmp_path / "v2"))
    result = owl("update", "--dir", str(target), ok=False)
    assert result.exit_code == 1 and "modified" in result.stdout
    assert (target / "git-helper" / "SKILL.md").read_text() == "hand edited"
    assert "modified" in owl("installed", "--dir", str(target)).stdout
    assert json.loads(owl("installed", "--dir", str(target), "--json").stdout)[0]["modified"] == [
        "SKILL.md"
    ]
    owl("update", "--dir", str(target), "--force")
    assert "new text" in (target / "git-helper" / "SKILL.md").read_text()


def test_export_refuses_to_clobber_existing_directory(lib, tmp_path):
    out = tmp_path / "out"
    (out / "git-helper").mkdir(parents=True)
    (out / "git-helper" / "mine.txt").write_text("keep")
    assert owl("export", "alice/git-helper", "-o", str(out), ok=False).exit_code != 0
    assert (out / "git-helper" / "mine.txt").read_text() == "keep"
    owl("export", "alice/git-helper", "-o", str(out), "--force")
    assert (out / "git-helper" / "SKILL.md").is_file()


def test_init_refuses_to_change_existing_origin(tmp_path):
    repo = tmp_path / "repo"
    gitutil.init(repo)
    gitutil.set_remote(repo, "https://example.invalid/a.git")
    result = owl(
        "init",
        "--backend",
        "git",
        "--location",
        str(repo),
        "--git-url",
        "https://example.invalid/b.git",
        ok=False,
    )
    assert result.exit_code != 0
    assert gitutil.remote_url(repo) == "https://example.invalid/a.git"
