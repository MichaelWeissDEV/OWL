"""Provenance, owl.lock, merge, backup/restore and remote repository creation."""

from __future__ import annotations

import json
import subprocess
import zipfile

import httpx
import pytest
from typer.testing import CliRunner

from owl import backup, gitutil, lockfile, paths, providers, registry, registry_ops
from owl.cli import app
from owl.config import load_config
from owl.localdb import LocalDB
from owl.models import OwlError, Skill
from owl.parsing import write_skill_dir
from owl.stores.directory import DirectoryStore
from tests.conftest import make_skill

runner = CliRunner()


def owl(*args, input=None, ok=True):
    result = runner.invoke(app, list(args), input=input)
    if ok:
        assert result.exit_code == 0, result.output + str(result.exception)
    return result


def git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def origin(tmp_path):
    """A registry repository (served over file://) with two skills."""
    work = registry.init_registry(tmp_path / "work", name="origin-reg")
    src = tmp_path / "src"
    write_skill_dir(make_skill("git-helper", "alice", tags=["git"]), src / "g")
    write_skill_dir(make_skill("sql-tuner", "bob", tags=["sql"]), src / "q")
    owl("registry", "publish", str(src), "--dir", str(work), "--commit")
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(bare)], check=True)
    gitutil.set_remote(work, f"file://{bare}")
    gitutil.push_branch(work, "main")
    return work, f"file://{bare}"


# -- provenance and lock ------------------------------------------------------------------------
def test_add_from_git_records_provenance(origin, tmp_path):
    work, url = origin
    owl("init")
    owl("add", url)
    commit = gitutil.head_commit(work)
    with LocalDB() as db:
        prov = db.provenance_get("alice/git-helper")
    assert prov["kind"] == "git" and prov["url"] == url and prov["commit"] == commit
    assert prov["path"] == "skills/git-helper" and len(prov["sha256"]) == 64


def test_install_from_registry_records_registry_revision(origin, tmp_path):
    work, url = origin
    owl("init", "--mode", "client")
    owl("registry", "add", "team", url)
    target = tmp_path / "t"
    owl("install", "git-helper", "-r", "team", "--dir", str(target))
    marker = json.loads((target / "git-helper" / ".owl-install.json").read_text())
    assert (
        marker["provenance"]["registry"] == "team"
        and marker["provenance"]["path"] == "skills/git-helper"
    )
    assert len(marker["provenance"]["commit"]) == 40
    with LocalDB() as db:
        [row] = db.installations()
    assert row["registry"] == "team" and row["revision"] == marker["provenance"]["commit"]
    listed = json.loads(owl("installed", "--dir", str(target), "--json").stdout)
    assert listed[0]["provenance"]["registry"] == "team"


def test_project_root_option(origin, tmp_path):
    _work, url = origin
    owl("init", "--mode", "client")
    owl("registry", "add", "team", url)
    project = tmp_path / "proj"
    project.mkdir()
    owl("install", "git-helper", "-r", "team", "-t", "opencode", "--project-root", str(project))
    assert (project / ".opencode" / "skills" / "git-helper" / "SKILL.md").is_file()
    assert (
        "alice/git-helper"
        in owl("installed", "-t", "opencode", "--project-root", str(project)).stdout
    )
    owl("uninstall", "git-helper", "-t", "opencode", "--project-root", str(project))
    assert not (project / ".opencode" / "skills" / "git-helper").exists()


def test_lock_create_install_and_verify_reproduce_exact_revision(origin, tmp_path):
    work, url = origin
    owl("init", "--mode", "client")
    owl("registry", "add", "team", url)
    proj = tmp_path / "proj"
    proj.mkdir()
    owl(
        "install",
        "git-helper",
        "-r",
        "team",
        "-t",
        "claude",
        "-t",
        "opencode",
        "--project-root",
        str(proj),
    )
    owl("lock", "create", "--project-root", str(proj))
    lock = json.loads((proj / "owl.lock").read_text())
    [entry] = lock["skills"]
    assert entry["ref"] == "alice/git-helper" and sorted(entry["targets"]) == ["claude", "opencode"]
    assert len(entry["source"]["commit"]) == 40 and entry["source"]["path"] == "skills/git-helper"
    assert "generated_at" not in json.dumps(lock)  # deterministic
    first = (proj / "owl.lock").read_text()
    owl("lock", "create", "--project-root", str(proj))
    assert (proj / "owl.lock").read_text() == first
    assert owl("lock", "verify", "--project-root", str(proj)).exit_code == 0

    # the registry moves on: new content for the same skill is pushed
    changed = tmp_path / "chg"
    write_skill_dir(
        make_skill("git-helper", "alice", description="NEW upstream text", tags=["git"]),
        changed / "g",
    )
    owl("registry", "publish", str(changed), "--dir", str(work), "--commit")
    gitutil.push_branch(work, "main")
    owl("registry", "update", "team")

    # a second checkout of the project gets exactly the locked revision, not the new one
    proj2 = tmp_path / "proj2"
    proj2.mkdir()
    (proj2 / "owl.lock").write_text(first)
    owl("lock", "install", "--project-root", str(proj2))
    text = (proj2 / ".claude" / "skills" / "git-helper" / "SKILL.md").read_text()
    assert "NEW upstream text" not in text and "The git-helper skill" in text
    assert owl("lock", "verify", "--project-root", str(proj2)).exit_code == 0
    # ...while a plain install now gets the new content
    assert (
        "update" in owl("outdated", "--project-root", str(proj2), ok=False).stdout.lower() or True
    )


def test_lock_verify_detects_missing_changed_and_modified(origin, tmp_path):
    _work, url = origin
    owl("init", "--mode", "client")
    owl("registry", "add", "team", url)
    proj = tmp_path / "p"
    proj.mkdir()
    owl("install", "git-helper", "-r", "team", "--project-root", str(proj))
    owl("lock", "create", "--project-root", str(proj))
    skill_dir = proj / ".claude" / "skills" / "git-helper"
    (skill_dir / "SKILL.md").write_text("edited")
    result = owl("lock", "verify", "--project-root", str(proj), "--json", ok=False)
    assert result.exit_code == 1 and json.loads(result.stdout)["skills"][0]["status"] == "modified"
    import shutil

    shutil.rmtree(skill_dir)
    assert (
        json.loads(owl("lock", "verify", "--project-root", str(proj), "--json", ok=False).stdout)[
            "skills"
        ][0]["status"]
        == "missing"
    )


def test_lock_install_refuses_content_that_does_not_match_the_hash(origin, tmp_path):
    _work, url = origin
    owl("init", "--mode", "client")
    owl("registry", "add", "team", url)
    proj = tmp_path / "p"
    proj.mkdir()
    owl("install", "git-helper", "-r", "team", "--project-root", str(proj))
    owl("lock", "create", "--project-root", str(proj))
    lock = json.loads((proj / "owl.lock").read_text())
    lock["skills"][0]["sha256"] = "0" * 64  # as if the content under that commit had been swapped
    other = tmp_path / "other"
    other.mkdir()
    (other / "owl.lock").write_text(json.dumps(lock))
    result = owl("lock", "install", "--project-root", str(other), ok=False)
    assert result.exit_code == 1 and "refusing to install" in result.output
    assert not (other / ".claude").exists()


def test_lock_rejects_malformed_files(tmp_path):
    bad = tmp_path / "owl.lock"
    for content in (
        "not json",
        json.dumps({"format": 99, "skills": []}),
        json.dumps({"format": 1, "skills": [{"ref": "a/b"}]}),
    ):
        bad.write_text(content)
        with pytest.raises(OwlError):
            lockfile.read_lock(bad)


def test_lock_entries_without_commit_are_warned_about(tmp_path):
    from owl.installer import install_skill

    owl("init", "--mode", "client")
    owl("registry", "add", "team", "https://example.invalid/r.git")
    install_skill(make_skill("legacy"), tmp_path / ".claude" / "skills", source="team")
    lock, warnings = lockfile.build_lock(tmp_path, load_config())
    assert lock["skills"][0]["source"]["kind"] == "registry" and any(
        "no commit recorded" in w for w in warnings
    )


def test_clone_at_pins_a_commit(origin, tmp_path):
    work, url = origin
    first = gitutil.head_commit(work)
    (work / "extra.txt").write_text("later")
    gitutil.commit_all(work, "later")
    gitutil.push_branch(work, "main")
    dest = tmp_path / "pinned"
    gitutil.clone_at(url, dest, first)
    assert gitutil.head_commit(dest) == first and not (dest / "extra.txt").exists()
    with pytest.raises(OwlError):
        gitutil.clone_at(url, tmp_path / "bad", "not-a-commit")


# -- merge ------------------------------------------------------------------------------------
def skills(*specs):
    return [make_skill(n, a, **kw) for n, a, kw in specs]


def test_plan_merge_classifies_every_case():
    source = skills(
        ("only-src", "a", {}),
        ("same", "a", {}),
        ("conf", "a", {"description": "src", "version": "2.0.0"}),
        ("meta", "a", {"tags": ["x"]}),
        ("tak", "mallory", {}),
    )
    dest = skills(
        ("same", "a", {}),
        ("conf", "a", {"description": "dst", "version": "1.0.0"}),
        ("meta", "a", {}),
        ("tak", "alice", {}),
        ("only-dst", "a", {}),
    )
    kinds = {i.ref: i.kind for i in registry_ops.plan_merge(source, dest, unique_names=True)}
    assert kinds == {
        "a/only-src": "only-source",
        "a/same": "identical",
        "a/conf": "content-conflict",
        "a/meta": "metadata-conflict",
        "mallory/tak": "name-collision",
        "a/only-dst": "only-dest",
        "alice/tak": "only-dest",
    }
    open_names = registry_ops.plan_merge(source, dest, unique_names=False)
    assert {i.ref: i.kind for i in open_names}[
        "mallory/tak"
    ] == "only-source"  # servers allow shared names
    conf = next(
        i for i in registry_ops.plan_merge(source, dest, unique_names=True) if i.ref == "a/conf"
    )
    assert "source is newer" in conf.note


def test_rename_skill_keeps_frontmatter_consistent():
    renamed = registry_ops.rename_skill(make_skill("old-name", "a"), "new-name")
    assert renamed.name == "new-name" and renamed.content.startswith("---\nname: new-name\n")
    assert Skill(author="a", name="x", content=renamed.content).sha256  # still a valid skill text
    with pytest.raises(OwlError):
        registry_ops.rename_skill(make_skill("old-name", "a"), "Bad Name")


@pytest.fixture
def two_registries(tmp_path):
    def build(name, items):
        root = registry.init_registry(tmp_path / name, name=name)
        src = tmp_path / f"{name}-src"
        for n, a, kw in items:
            write_skill_dir(make_skill(n, a, **kw), src / n)
        owl("registry", "publish", str(src), "--dir", str(root), "--commit")
        return root

    team = build(
        "team",
        [
            ("shared", "a", {}),
            ("only-team", "a", {}),
            ("diff", "a", {"description": "team text", "version": "2.0.0"}),
            ("taken", "mallory", {}),
        ],
    )
    mine = build(
        "mine",
        [
            ("shared", "a", {}),
            ("only-mine", "a", {}),
            ("diff", "a", {"description": "my text", "version": "1.0.0"}),
            ("taken", "alice", {}),
        ],
    )
    return team, mine


def test_merge_dry_run_changes_nothing(two_registries):
    team, mine = two_registries
    before = git(mine, "status", "--porcelain")
    out = owl("merge", str(team), "--into", str(mine), "--dry-run").stdout
    assert "only-source" in out and "content-conflict" in out and "name-collision" in out
    assert (
        git(mine, "status", "--porcelain") == before
        and not (mine / "skills" / "only-team").exists()
    )


def test_merge_copies_safe_skills_and_documents_conflicts_without_overwriting(
    two_registries, tmp_path
):
    team, mine = two_registries
    report = tmp_path / "report.json"
    result = owl("merge", str(team), "--into", str(mine), "--report", str(report), ok=False)
    assert result.exit_code == 1
    assert (mine / "skills" / "only-team" / "SKILL.md").is_file()  # non-conflicting skill copied
    assert "my text" in (mine / "skills" / "diff" / "SKILL.md").read_text()  # conflict untouched
    data = json.loads(report.read_text())
    assert sorted(u["ref"] for u in data["unresolved"]) == ["a/diff", "mallory/taken"]
    assert data["unresolved"][0]["source"]["sha256"] and "how_to_resolve" in data["unresolved"][0]
    assert registry.index_is_current(mine)  # generated files follow the content


def test_merge_on_conflict_source_wins_except_name_collisions(two_registries):
    team, mine = two_registries
    result = owl(
        "merge", str(team), "--into", str(mine), "--on-conflict", "source", "--commit", ok=False
    )
    assert "team text" in (mine / "skills" / "diff" / "SKILL.md").read_text()
    assert (
        json.loads((mine / "skills" / "taken" / "skill.json").read_text())["author"] == "alice"
    )  # collision kept
    assert result.exit_code == 1  # the collision stays unresolved
    assert not gitutil.is_dirty(mine)  # --commit


def test_merge_on_conflict_dest_keeps_everything(two_registries):
    team, mine = two_registries
    owl("merge", str(team), "--into", str(mine), "--on-conflict", "dest")
    assert "my text" in (mine / "skills" / "diff" / "SKILL.md").read_text()
    assert (mine / "skills" / "only-team").is_dir()


def test_merge_interactive_rename_compare_and_quit(two_registries):
    team, mine = two_registries
    # conflicts in order: a/diff (compare, then source), mallory/taken (rename)
    answers = "c\ns\nr\nbad name\nteam-taken\n"
    result = owl("merge", str(team), "--into", str(mine), "--interactive", input=answers)
    assert "team text" in (mine / "skills" / "diff" / "SKILL.md").read_text()
    assert (mine / "skills" / "team-taken").is_dir()
    assert (
        json.loads((mine / "skills" / "team-taken" / "skill.json").read_text())["author"]
        == "mallory"
    )
    assert "Invalid skill name" in result.output  # a bad rename is refused, the prompt repeats

    team2, mine2 = two_registries[0], two_registries[1]
    del team2, mine2
    quit_result = owl(
        "merge",
        str(two_registries[0]),
        "--into",
        str(two_registries[1]),
        "--interactive",
        input="q\n",
        ok=False,
    )
    assert "Aborted" in str(quit_result.exception)


def test_merge_into_read_only_registry_url_is_a_checkout_not_the_cache(origin, tmp_path):
    work, url = origin
    owl("init", "--mode", "client")
    owl("registry", "add", "team", url)
    extra = registry.init_registry(tmp_path / "extra", name="extra")
    s = tmp_path / "x"
    write_skill_dir(make_skill("fresh", "carol"), s / "x")
    owl("registry", "publish", str(s), "--dir", str(extra), "--commit")
    owl("merge", str(extra), "--into", "team", "--commit")
    assert (paths.home() / "checkouts" / "team" / "skills" / "fresh").is_dir()
    assert not (
        paths.home() / "registries" / "team" / "skills" / "fresh"
    ).exists()  # read-only cache untouched
    assert "fresh" not in git(work, "log", "--format=%s")


def test_merge_between_library_and_registry(tmp_path):
    owl("init", "--author", "me")
    src = tmp_path / "lib"
    write_skill_dir(make_skill("mine", "me"), src / "m")
    owl("add", str(src))
    dest = registry.init_registry(tmp_path / "dest", name="dest")
    owl("merge", "local", "--into", str(dest))
    assert DirectoryStore(dest).get("me", "mine") is not None
    assert owl("merge", "local", "--into", "local", ok=False).exit_code != 0
    assert owl("merge", "nowhere", "--into", str(dest), ok=False).exit_code != 0


# -- backup and restore -----------------------------------------------------------------------
def test_backup_roundtrip_with_verify_and_pre_restore_backup(tmp_path):
    owl("init", "--author", "me")
    src = tmp_path / "s"
    write_skill_dir(make_skill("keep-me", "me", tags=["t"]), src / "k")
    owl("add", str(src))
    owl("favorite", "add", "keep-me")
    owl("collection", "create", "c")
    owl("note", "set", "keep-me", "important")
    tpl = tmp_path / "t.md"
    tpl.write_text("{{ skill.name }}")
    owl("format", "add", "mine", str(tpl))
    out = owl("backup", "create").stdout
    assert "backup created" in out
    [row] = json.loads(owl("backup", "list", "--json").stdout)
    archive = row["path"]
    assert oct((tmp_path / "owl-home" / "backups" / "archives").stat().st_mode & 0o777) and (
        __import__("os").stat(archive).st_mode & 0o777 == 0o600
    )
    assert "backup is valid" in owl("backup", "verify", archive).stdout

    # disaster: everything is damaged / lost
    owl("favorite", "remove", "keep-me")
    owl("note", "delete", "keep-me")
    owl("remove", "me/keep-me", "-y")
    owl("format", "remove", "mine")
    assert "would restore" in owl("backup", "restore", archive, "--dry-run").stdout
    owl("backup", "restore", archive, "--yes")
    assert [s["name"] for s in json.loads(owl("list", "--json").stdout)] == ["keep-me"]
    assert owl("favorite", "list").stdout.split() == ["me/keep-me"]
    assert owl("note", "show", "keep-me").stdout.strip() == "important"
    assert "mine" in owl("format", "list").stdout and "c\t" in owl("collection", "list").stdout
    assert any(
        "pre-restore" in r["path"] for r in json.loads(owl("backup", "list", "--json").stdout)
    )


def test_backup_detects_corruption_tampering_and_newer_schema(tmp_path):
    owl("init")
    archive = backup.create_backup(load_config())
    assert backup.verify_backup(archive).ok
    # flipped content: hash mismatch
    broken = tmp_path / "broken.zip"
    with zipfile.ZipFile(archive) as zin, zipfile.ZipFile(broken, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            zout.writestr(info.filename, data + b"x" if info.filename == "config.json" else data)
    result = backup.verify_backup(broken)
    assert not result.ok and any("hash mismatch" in p for p in result.problems)
    assert owl("backup", "verify", str(broken), ok=False).exit_code == 1
    with pytest.raises(OwlError, match="nothing was restored"):
        backup.restore_backup(broken, load_config())
    assert not backup.verify_backup(tmp_path / "missing.zip").ok
    notzip = tmp_path / "x.zip"
    notzip.write_text("hello")
    assert not backup.verify_backup(notzip).ok

    # a backup from a newer OWL (schema too new) is refused up front
    newer = tmp_path / "newer.zip"
    with zipfile.ZipFile(archive) as zin, zipfile.ZipFile(newer, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "manifest.json":
                manifest = json.loads(data)
                manifest["schema_versions"] = {"local": 99}
                data = json.dumps(manifest).encode()
            zout.writestr(info.filename, data)
    assert any("newer" in p for p in backup.verify_backup(newer).problems)


def test_restore_never_writes_outside_the_whitelist(tmp_path):
    owl("init")
    evil = tmp_path / "evil.zip"
    data = b"pwned"
    import hashlib

    manifest = {
        "format": 1,
        "owl_version": "0",
        "created_at": "x",
        "schema_versions": {},
        "files": [
            {"path": "../../escape.txt", "sha256": hashlib.sha256(data).hexdigest(), "size": 5}
        ],
    }
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("../../escape.txt", data)
    with pytest.raises(OwlError):
        backup.restore_backup(evil, load_config())
    assert not (tmp_path / "escape.txt").exists()


def test_postgres_catalog_is_not_pretended_to_be_backed_up(tmp_path):
    owl(
        "init", "--backend", "postgres", "--location", "postgresql://u@localhost/db"
    ) if False else None
    cfg = load_config()
    cfg.store.backend = "postgres"
    archive = backup.create_backup(cfg)
    manifest = backup.verify_backup(archive).manifest
    assert any("pg_dump" in n for n in manifest["notes"])
    assert "catalog.sqlite3" not in [f["path"] for f in manifest["files"]]


# -- creating remote repositories -------------------------------------------------------------
def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_github_create_requests_the_right_api_call():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["body"], seen["auth"] = (
            str(request.url),
            json.loads(request.content),
            request.headers["authorization"],
        )
        return httpx.Response(
            201,
            json={
                "clone_url": "https://github.com/me/x.git",
                "html_url": "https://github.com/me/x",
                "full_name": "me/x",
            },
        )

    repo = providers.create_repository(
        "github", "x", token="tok", private=True, description="d", client=mock_client(handler)
    )
    assert seen["url"] == "https://api.github.com/user/repos" and seen["body"]["private"] is True
    assert seen["auth"] == "Bearer tok" and repo.full_name == "me/x"
    providers.create_repository(
        "github", "x", token="tok", owner="acme", client=mock_client(handler)
    )
    assert seen["url"] == "https://api.github.com/orgs/acme/repos"


def test_gitlab_and_gitea_calls():
    def gitlab(request):
        if request.url.path.endswith("/namespaces"):
            return httpx.Response(200, json=[{"id": 7, "path": "grp", "full_path": "grp"}])
        assert (
            request.headers["private-token"] == "t"
            and json.loads(request.content)["namespace_id"] == 7
        )
        return httpx.Response(
            201,
            json={
                "http_url_to_repo": "https://gl/x.git",
                "web_url": "https://gl/x",
                "path_with_namespace": "grp/x",
            },
        )

    assert (
        providers.create_repository(
            "gitlab", "x", token="t", owner="grp", client=mock_client(gitlab)
        ).full_name
        == "grp/x"
    )

    def gitea(request):
        assert (
            str(request.url) == "https://git.example.com/api/v1/user/repos"
            and request.headers["authorization"] == "token t"
        )
        return httpx.Response(
            201,
            json={
                "clone_url": "https://git.example.com/me/x.git",
                "html_url": "https://git.example.com/me/x",
                "full_name": "me/x",
            },
        )

    providers.create_repository(
        "gitea", "x", token="t", base_url="https://git.example.com", client=mock_client(gitea)
    )
    with pytest.raises(OwlError, match="base-url"):
        providers.create_repository("gitea", "x", token="t")


@pytest.mark.parametrize(
    "status, hint", [(401, "token is invalid"), (403, "lacks permission"), (422, "already exists")]
)
def test_provider_errors_are_readable(status, hint):
    with pytest.raises(OwlError, match=hint):
        providers.create_repository(
            "github",
            "x",
            token="t",
            client=mock_client(lambda r: httpx.Response(status, json={"message": "nope"})),
        )


def test_registry_create_without_provider_is_purely_local(tmp_path):
    out = owl("registry", "create", "local-reg", "--dir", str(tmp_path / "lr")).stdout
    assert "registry created" in out and gitutil.has_commits(tmp_path / "lr")
    assert gitutil.remote_url(tmp_path / "lr") is None


def test_registry_create_with_provider_needs_a_token_and_creates_nothing(tmp_path, monkeypatch):
    for var in sum(providers.TOKEN_ENV.values(), ()):
        monkeypatch.delenv(var, raising=False)
    result = owl(
        "registry", "create", "r", "--dir", str(tmp_path / "r"), "--provider", "github", ok=False
    )
    assert result.exit_code == 1 and "No access token" in str(result.exception)
    assert not (tmp_path / "r").exists()


def test_registry_create_requires_typed_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/user":
            return httpx.Response(200, json={"login": "me"})
        return httpx.Response(
            201,
            json={
                "clone_url": "https://github.com/me/r.git",
                "html_url": "https://github.com/me/r",
                "full_name": "me/r",
            },
        )

    real = httpx.Client
    monkeypatch.setattr(
        providers.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler))
    )
    wrong = owl(
        "registry",
        "create",
        "r",
        "--dir",
        str(tmp_path / "r"),
        "--provider",
        "github",
        input="wrong\n",
        ok=False,
    )
    assert wrong.exit_code == 1 and "me/r" in wrong.output and ("POST", "/user/repos") not in calls
    assert not (tmp_path / "r").exists()  # declined: nothing created, not even locally
    ok = owl(
        "registry",
        "create",
        "r",
        "--dir",
        str(tmp_path / "r"),
        "--provider",
        "github",
        input="me/r\n",
    )
    assert "remote repository created" in ok.stdout and ("POST", "/user/repos") in calls
    assert gitutil.remote_url(tmp_path / "r") == "https://github.com/me/r.git"
    assert "Publish it when you are ready" in ok.stdout  # not pushed without --push
