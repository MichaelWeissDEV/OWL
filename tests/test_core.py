from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from owl.fsutil import safe_relpath
from owl.installer import install_skill, list_installed, uninstall_skill
from owl.models import OwlError, Skill, validate_skill
from owl.parsing import load_skill_dir, load_skills, skill_from_markdown, write_skill_dir
from owl.server import create_app
from owl.sync import plan_pull, plan_push
from tests.conftest import TOKEN, make_skill


# -- parsing and hashing --------------------------------------------------------------------
def test_frontmatter_fields_including_nested_metadata():
    text = (
        "---\nname: demo\ndescription: A demo\nmetadata:\n  version: '2.0'\n"
        "tags: [B, a, a]\ntopics: 'x, y'\n---\n# Demo\n"
    )
    skill, problems = skill_from_markdown(text, default_author="Me")
    assert problems == []
    assert (skill.author, skill.version) == ("me", "2.0")
    assert skill.tags == ["a", "b"] and skill.topics == ["x", "y"]


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("no frontmatter", "Missing YAML frontmatter"),
        ("---\nname: x\n", "Unclosed"),
        ("---\nname: Bad_Name\ndescription: d\n---\nbody", "Invalid skill name"),
        ("---\nname: ok\n---\nbody", "description"),
    ],
)
def test_validation_problems(text, fragment):
    _skill, problems = skill_from_markdown(text, fallback_name="fallback")
    assert any(fragment in p for p in problems), problems


def test_hash_ignores_timestamps_but_not_content():
    a, b = make_skill("h"), make_skill("h")
    b.updated_at = "2020-01-01"
    assert a.sha256 == b.sha256
    assert make_skill("h", files={"f": b"1"}).sha256 != a.sha256
    assert make_skill("h", tags=["t"]).sha256 != a.sha256


def test_reserved_file_names_rejected():
    skill = make_skill("r", files={"SKILL.md": b"x"})
    assert any("reserved" in p for p in validate_skill(skill))


def test_directory_roundtrip_with_overlay(tmp_path):
    original = make_skill("rt", tags=["x"], extra={"license": "MIT"}, files={"a/b.txt": b"hi"})
    write_skill_dir(original, tmp_path / "rt")
    loaded = load_skill_dir(tmp_path / "rt")
    assert loaded.valid and loaded.skill.sha256 == original.sha256


def test_load_skills_ignores_symlinks(tmp_path):
    outside = tmp_path / "outside"
    write_skill_dir(make_skill("secret"), outside)
    root = tmp_path / "repo"
    write_skill_dir(make_skill("real"), root / "real")
    (root / "link").symlink_to(outside, target_is_directory=True)
    (root / "real" / "leak.txt").symlink_to(outside / "SKILL.md")
    found = load_skills(root)
    assert [r.skill.name for r in found] == ["real"]
    assert "leak.txt" not in found[0].skill.files


@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "a/../../b", "", "a\\b", ".git/config"])
def test_safe_relpath_rejects(bad):
    with pytest.raises(OwlError):
        safe_relpath(bad)


# -- installer ------------------------------------------------------------------------------
def test_install_uninstall_and_protection(tmp_path):
    skill = make_skill("inst", files={"scripts/x.sh": b"echo"})
    dest = install_skill(skill, tmp_path, source="test")
    assert (dest / "SKILL.md").is_file() and (dest / "scripts" / "x.sh").is_file()
    assert [i.ref for i in list_installed(tmp_path)] == ["alice/inst"]
    install_skill(skill, tmp_path)  # same author: reinstall is fine
    with pytest.raises(OwlError):
        install_skill(make_skill("inst", "bob"), tmp_path)
    install_skill(make_skill("inst", "bob"), tmp_path, force=True)
    uninstall_skill("inst", tmp_path)
    assert not dest.exists()


def test_install_refuses_foreign_directory(tmp_path):
    (tmp_path / "mine").mkdir()
    (tmp_path / "mine" / "SKILL.md").write_text("hand written")
    with pytest.raises(OwlError):
        install_skill(make_skill("mine"), tmp_path)
    with pytest.raises(OwlError):
        uninstall_skill("mine", tmp_path)


def test_install_rejects_path_traversal(tmp_path):
    evil = Skill(author="a", name="evil", description="d", content="x", files={"../escape": b"x"})
    with pytest.raises(OwlError):
        install_skill(evil, tmp_path / "skills")
    assert not (tmp_path / "escape").exists()


# -- sync planning ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "local, remote, base, force, action",
    [
        (None, "r", None, False, "copy"),  # new
        ("x", "x", "x", False, "noop"),
        ("l", "r", "l", False, "copy"),  # fast-forward
        ("l", "r", "r", False, "skip"),  # local ahead
        ("l", "r", "b", False, "skip"),  # diverged
        ("l", "r", "b", True, "copy"),
        ("l", None, None, False, "skip"),
    ],
)
def test_plan_pull(local, remote, base, force, action):
    assert plan_pull(local, remote, base, force).action == action


@pytest.mark.parametrize(
    "local, remote, base, force, action",
    [
        ("l", None, None, False, "copy"),
        ("l", "l", None, False, "noop"),
        ("l", "r", "r", False, "copy"),
        ("l", "r", "l", False, "skip"),  # remote ahead
        ("l", "r", "b", False, "skip"),  # diverged
        ("l", "r", "b", True, "copy"),
        (None, "r", None, False, "skip"),
    ],
)
def test_plan_push(local, remote, base, force, action):
    assert plan_push(local, remote, base, force).action == action


# -- server ---------------------------------------------------------------------------------
def test_server_auth_modes(server_store):
    skill = make_skill("secured").to_dict()
    auth = {"Authorization": f"Bearer {TOKEN}"}
    open_server = TestClient(create_app(server_store, token=TOKEN))
    assert open_server.put("/api/v1/skills/alice/secured", json=skill).status_code == 401
    bad = {"Authorization": "Bearer wrong"}
    assert (
        open_server.put("/api/v1/skills/alice/secured", json=skill, headers=bad).status_code == 401
    )
    assert (
        open_server.put("/api/v1/skills/alice/secured", json=skill, headers=auth).status_code == 200
    )
    assert open_server.get("/api/v1/skills/alice/secured").status_code == 200  # reads are open
    assert open_server.delete("/api/v1/skills/alice/secured").status_code == 401

    private = TestClient(create_app(server_store, token=TOKEN, private=True))
    assert private.get("/api/v1/skills").status_code == 401
    assert private.get("/api/v1/skills", headers=auth).status_code == 200
    assert private.get("/api/v1/health").status_code == 200

    readonly = TestClient(create_app(server_store))
    assert readonly.put("/api/v1/skills/alice/secured", json=skill, headers=auth).status_code == 403


def test_server_rejects_bad_uploads(server_store):
    client = TestClient(create_app(server_store, token=TOKEN))
    auth = {"Authorization": f"Bearer {TOKEN}"}
    skill = make_skill("up").to_dict()
    assert client.put("/api/v1/skills/alice/other", json=skill, headers=auth).status_code == 422
    skill["files"] = {"../evil": "aGk="}
    assert client.put("/api/v1/skills/alice/up", json=skill, headers=auth).status_code == 422
    skill["files"] = {}
    skill["name"] = "Bad Name"
    assert client.put("/api/v1/skills/alice/Bad Name", json=skill, headers=auth).status_code == 422
    assert server_store.count() == 0


def test_server_index_page_escapes_html(server_store):
    server_store.upsert(make_skill("page", description="<script>alert(1)</script> hi"))
    client = TestClient(create_app(server_store))
    body = client.get("/").text
    assert "<script>alert" not in body and "&lt;script&gt;" in body
    assert "page" in client.get("/", params={"q": "page"}).text


# -- Phase A regressions: no data loss ---------------------------------------------------------
def test_installed_json_works_for_slotted_dataclass(tmp_path):
    from owl.installer import list_installed

    install_skill(make_skill("js"), tmp_path)
    data = list_installed(tmp_path)[0].to_dict()
    assert data["ref"] == "alice/js" and data["modified"] == [] and isinstance(data["path"], str)
    import json as _json

    _json.dumps(data)


def test_replace_dir_restores_old_state_on_failure(tmp_path, monkeypatch):
    from pathlib import Path

    from owl.fsutil import replace_dir

    dest = tmp_path / "skill"
    replace_dir(dest, {"SKILL.md": b"old"})
    real_rename = Path.rename

    def flaky(self, target):  # fail only when moving the new staging dir into place
        if ".new-" in self.name:
            raise OSError("disk exploded")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky)
    with pytest.raises(OSError):
        replace_dir(dest, {"SKILL.md": b"new"})
    monkeypatch.undo()
    assert (dest / "SKILL.md").read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["skill"]  # no staging/backup leftovers


def test_replace_dir_failure_while_writing_keeps_old(tmp_path):
    from owl.fsutil import replace_dir

    dest = tmp_path / "skill"
    replace_dir(dest, {"SKILL.md": b"old"})
    with pytest.raises(OwlError):
        replace_dir(dest, {"SKILL.md": b"new", "../evil": b"x"})
    assert (dest / "SKILL.md").read_bytes() == b"old"
    assert not (tmp_path / "evil").exists()


def test_reinstall_refuses_to_overwrite_local_edits(tmp_path, owl_home):
    skill = make_skill("edited")
    dest = install_skill(skill, tmp_path)
    (dest / "SKILL.md").write_text("my own changes")
    (dest / "extra.txt").write_text("new file")
    with pytest.raises(OwlError, match="local modifications"):
        install_skill(make_skill("edited", description="v2"), tmp_path)
    assert (dest / "SKILL.md").read_text() == "my own changes"
    install_skill(make_skill("edited", description="v2"), tmp_path, force=True)
    assert "v2" in (dest / "SKILL.md").read_text()
    backups = list((owl_home / "backups" / "installs").iterdir())
    assert len(backups) == 1 and (backups[0] / "SKILL.md").read_text() == "my own changes"


def test_reinstall_of_unmodified_skill_is_a_noop(tmp_path):
    skill = make_skill("same")
    dest = install_skill(skill, tmp_path)
    before = (dest / ".owl-install.json").stat().st_mtime_ns
    install_skill(skill, tmp_path)
    assert (dest / ".owl-install.json").stat().st_mtime_ns == before


def test_uninstall_protects_modified_skill(tmp_path, owl_home):
    dest = install_skill(make_skill("keepme"), tmp_path)
    (dest / "SKILL.md").write_text("precious")
    with pytest.raises(OwlError, match="modifications"):
        uninstall_skill("keepme", tmp_path)
    uninstall_skill("keepme", tmp_path, force=True)
    assert not dest.exists()
    assert any(
        "precious" in (p / "SKILL.md").read_text()
        for p in (owl_home / "backups" / "installs").iterdir()
    )


def test_directory_store_upsert_is_atomic(tmp_path, monkeypatch):
    from owl.stores.directory import DirectoryStore

    store = DirectoryStore(tmp_path)
    store.upsert(make_skill("atomic"))
    monkeypatch.setattr(
        "owl.stores.directory.replace_dir", lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
    )
    with pytest.raises(OSError):
        store.upsert(make_skill("atomic", description="changed"))
    monkeypatch.undo()
    assert DirectoryStore(tmp_path).get("alice", "atomic").description != "changed"


def test_spec_warnings_and_description_limit(tmp_path):
    write_skill_dir(make_skill("right-name"), tmp_path / "wrong-dir")
    result = load_skill_dir(tmp_path / "wrong-dir")
    assert result.valid and any("differs from skill name" in w for w in result.warnings)
    too_long = make_skill("long", description="x" * 1025)
    assert any("1024" in p for p in validate_skill(too_long))
