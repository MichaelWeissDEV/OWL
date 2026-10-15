"""Favorites, collections, notes, metadata, edit, history, search flags, validate, db commands."""

from __future__ import annotations

import json
import stat
import sys

import pytest
from typer.testing import CliRunner

from owl.cli import app
from owl.localdb import LocalDB
from owl.parsing import write_skill_dir
from tests.conftest import make_skill

runner = CliRunner()


def owl(*args, input=None, ok=True):
    result = runner.invoke(app, list(args), input=input)
    if ok:
        assert result.exit_code == 0, result.output + str(result.exception)
    return result


@pytest.fixture
def lib(tmp_path):
    root = tmp_path / "src"
    write_skill_dir(
        make_skill("git-helper", "alice", tags=["git"], topics=["devtools"]), root / "g"
    )
    write_skill_dir(make_skill("sql-tuner", "bob", tags=["sql"]), root / "s")
    write_skill_dir(make_skill("docs-writer", "alice", tags=["docs"]), root / "d")
    owl("init", "--author", "tester")
    owl("add", str(root))
    return root


def test_favorites(lib):
    owl("favorite", "add", "git-helper")
    assert "already" in owl("favorite", "add", "alice/git-helper").stdout
    assert owl("favorite", "list").stdout.split() == ["alice/git-helper"]
    assert json.loads(owl("favorite", "list", "--json").stdout) == ["alice/git-helper"]
    assert owl("favorite", "add", "nope", ok=False).exit_code != 0
    owl("favorite", "remove", "git-helper")
    assert owl("favorite", "list").stdout.strip() == ""
    assert owl("favorite", "remove", "git-helper", ok=False).exit_code != 0


def test_collections(lib):
    owl("collection", "create", "security", "--description", "audit stuff")
    assert owl("collection", "create", "security", ok=False).exit_code != 0
    owl("collection", "add", "security", "git-helper", "sql-tuner")
    assert "security\t2 skills" in owl("collection", "list").stdout
    assert owl("collection", "show", "security").stdout.split() == [
        "alice/git-helper",
        "bob/sql-tuner",
    ]
    owl("collection", "remove", "security", "sql-tuner")
    assert json.loads(owl("collection", "show", "security", "--json").stdout) == [
        "alice/git-helper"
    ]
    assert owl("collection", "add", "missing", "git-helper", ok=False).exit_code != 0
    owl("collection", "delete", "security")
    assert owl("collection", "list").stdout.strip() == ""


def test_notes_are_local_only(lib):
    owl("note", "set", "git-helper", "Useful for code reviews")
    assert owl("note", "show", "git-helper").stdout.strip() == "Useful for code reviews"
    assert "alice/git-helper" in owl("note", "list").stdout
    skill = json.loads(owl("show", "git-helper", "--json").stdout)
    assert "Useful for code reviews" not in json.dumps(skill)  # never part of the skill
    owl("note", "delete", "git-helper")
    assert owl("note", "show", "git-helper", ok=False).exit_code != 0


def test_metadata_set_unset_show(lib):
    owl("metadata", "set", "git-helper", "version", "2.0.0")
    owl("metadata", "set", "git-helper", "tags", "Git, VCS ,git")
    owl("metadata", "set", "git-helper", "license", "MIT")
    meta = json.loads(owl("metadata", "show", "git-helper", "--json").stdout)
    assert (
        meta["version"] == "2.0.0" and meta["tags"] == ["git", "vcs"] and meta["license"] == "MIT"
    )
    shown = json.loads(owl("show", "git-helper", "--json").stdout)
    assert "version: 2.0.0" not in shown["content"]  # SKILL.md itself is untouched
    owl("metadata", "unset", "git-helper", "license")
    owl("metadata", "unset", "git-helper", "tags")
    assert json.loads(owl("metadata", "show", "git-helper", "--json").stdout)["tags"] == []
    owl("metadata", "set", "git-helper", "author", "carol")  # identity moves with the author
    assert [
        s["author"] for s in json.loads(owl("list", "--json").stdout) if s["name"] == "git-helper"
    ] == ["carol"]


def test_metadata_refuses_invalid_results_and_renames(lib):
    assert owl("metadata", "set", "git-helper", "description", "  ", ok=False).exit_code != 0
    assert owl("metadata", "set", "git-helper", "name", "other", ok=False).exit_code != 0
    assert owl("metadata", "unset", "git-helper", "description", ok=False).exit_code != 0
    assert json.loads(owl("show", "git-helper", "--json").stdout)["description"].startswith(
        "The git-helper"
    )


def test_local_metadata_overrides_do_not_touch_the_skill(lib):
    before = json.loads(owl("show", "git-helper", "--json").stdout)["sha256"]
    owl("metadata", "set", "git-helper", "priority", "high", "--local")
    assert json.loads(owl("show", "git-helper", "--json").stdout)["sha256"] == before
    shown = json.loads(owl("metadata", "show", "git-helper", "--json").stdout)
    assert shown["local_overrides"] == {"priority": "high"}
    owl("metadata", "unset", "git-helper", "priority", "--local")


def _editor(tmp_path, body):
    script = tmp_path / "editor.py"
    script.write_text(f"import sys\nopen(sys.argv[1], 'w').write({body!r})\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return f"{sys.executable} {script}"


def test_edit_valid_change_is_stored(lib, tmp_path, monkeypatch):
    new = "---\nname: git-helper\ndescription: Edited description\n---\n# New body\n"
    monkeypatch.setenv("EDITOR", _editor(tmp_path, new))
    out = owl("edit", "git-helper").stdout
    assert "updated" in out
    shown = json.loads(owl("show", "git-helper", "--json").stdout)
    assert shown["description"] == "Edited description" and "# New body" in shown["content"]
    assert shown["author"] == "alice" and shown["tags"] == ["git"]  # untouched fields are kept


def test_edit_invalid_result_never_replaces_the_valid_skill(lib, tmp_path, monkeypatch):
    monkeypatch.setenv("EDITOR", _editor(tmp_path, "---\nname: git-helper\n---\nno description\n"))
    result = owl("edit", "git-helper", "--on-invalid", "draft", ok=False)
    assert result.exit_code != 0 and "Saved as draft" in str(result.exception)
    assert json.loads(owl("show", "git-helper", "--json").stdout)["description"].startswith(
        "The git-helper"
    )
    with LocalDB() as db:
        assert len(db.drafts()) == 1
    abort = owl("edit", "git-helper", "--on-invalid", "abort", ok=False)
    assert "unchanged" in str(abort.exception)
    # interactive: 'a'bort
    asked = owl("edit", "git-helper", input="a\n", ok=False)
    assert asked.exit_code != 0


def test_edit_cannot_rename(lib, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "EDITOR", _editor(tmp_path, "---\nname: renamed\ndescription: x\n---\nbody\n")
    )
    assert owl("edit", "git-helper", "--on-invalid", "abort", ok=False).exit_code != 0


def test_drafts_promote_flow(lib, tmp_path, monkeypatch):
    with LocalDB() as db:
        draft_id = db.draft_add(
            "fixme", "test", "---\nname: fixme\n---\nbody\n", ["Missing description"]
        )
    assert "fixme" in owl("drafts", "list").stdout
    fixed = "---\nname: fixme\ndescription: Now fixed\n---\nbody\n"
    monkeypatch.setenv("EDITOR", _editor(tmp_path, fixed))
    assert "valid" in owl("drafts", "edit", str(draft_id)).stdout
    owl("drafts", "promote", str(draft_id))
    assert "tester/fixme" in json.dumps(
        json.loads(owl("list", "--json").stdout)
        and [f"{s['author']}/{s['name']}" for s in json.loads(owl("list", "--json").stdout)]
    )
    assert owl("drafts", "list").stdout.strip() == ""


def test_validate_by_ref_and_all(lib):
    assert "OK" in owl("validate", "git-helper").stdout
    assert json.loads(owl("validate", "--all", "--json").stdout)["ok"] is True


def test_history_and_installation_records(lib, tmp_path):
    target = tmp_path / "skills"
    owl("install", "git-helper", "--dir", str(target))
    owl("uninstall", "git-helper", "--dir", str(target))
    ops = [h["operation"] for h in json.loads(owl("history", "--json").stdout)]
    assert "install" in ops and "uninstall" in ops and "add" in ops
    with LocalDB() as db:
        assert db.installations() == []  # forgotten after uninstall
    owl("install", "git-helper", "-t", "opencode", "-p", "--dir", str(target))
    with LocalDB() as db:
        [row] = db.installations()
    assert (
        row["ref"] == "alice/git-helper" and row["scope"] == "custom" and len(row["sha256"]) == 64
    )


def test_search_flags_filters_sort_and_paging(lib, tmp_path):
    owl("favorite", "add", "sql-tuner")
    owl("collection", "create", "c")
    owl("collection", "add", "c", "git-helper")
    owl("install", "docs-writer", "--dir", str(tmp_path / "inst"))
    rows = {r["name"]: r for r in json.loads(owl("search", "--json").stdout)}
    assert rows["sql-tuner"]["favorite"] and not rows["git-helper"]["favorite"]
    assert rows["docs-writer"]["installed"] and not rows["docs-writer"]["update_available"]
    names = lambda *a: [r["name"] for r in json.loads(owl("search", *a, "--json").stdout)]  # noqa: E731
    assert names("--favorites") == ["sql-tuner"]
    assert names("--installed") == ["docs-writer"]
    assert names("--collection", "c") == ["git-helper"]
    assert names("--sort", "name") == ["docs-writer", "git-helper", "sql-tuner"]
    assert names("--sort", "name", "--limit", "1", "--offset", "1") == ["git-helper"]
    # a changed library skill marks the recorded installation as outdated
    owl("metadata", "set", "docs-writer", "version", "9.9.9")
    rows = {r["name"]: r for r in json.loads(owl("search", "--json").stdout)}
    assert rows["docs-writer"]["update_available"] is True


def test_db_commands_and_source_trust(lib):
    status = owl("db", "status").stdout
    assert "catalog: v2 of v2" in status and "local: v2 of v2" in status
    assert "up to date" in owl("db", "migrate").stdout
    assert owl("db", "backup").stdout.count("backup") >= 2
    owl("source", "add", "mine", "/some/dir")
    owl("trust", "add", "mine", "--note", "my own")
    assert "mine\tdirectory\t/some/dir\ttrusted" in owl("source", "list").stdout
    owl("trust", "remove", "mine")
    owl("source", "remove", "mine")
    assert owl("trust", "remove", "mine", ok=False).exit_code != 0


def test_install_a_whole_collection(lib, tmp_path):
    owl("collection", "create", "review")
    owl("collection", "add", "review", "git-helper", "docs-writer")
    target = tmp_path / "t"
    owl("install", "--collection", "review", "--dir", str(target))
    assert sorted(p.name for p in target.iterdir()) == ["docs-writer", "git-helper"]
    owl("collection", "create", "empty")
    assert owl("install", "--collection", "empty", ok=False).exit_code != 0
