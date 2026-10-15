"""Discovery, import strategies (strict / defaults / interactive / dry-run) and drafts."""

from __future__ import annotations

import json
import os
import stat
import zipfile

import pytest
from typer.testing import CliRunner

from owl import discovery, gitutil
from owl.cli import app
from owl.importer import DEFAULTS, STRICT, build_plan, suggest_fields
from owl.localdb import LocalDB
from owl.models import OwlError
from owl.parsing import write_skill_dir
from tests.conftest import make_skill

runner = CliRunner()


def owl(*args, input=None, ok=True):
    result = runner.invoke(app, list(args), input=input)
    if ok:
        assert result.exit_code == 0, result.output + str(result.exception)
    return result


def write_plain(dir_, name, text):
    d = dir_ / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(text)
    return d


@pytest.fixture
def mess(tmp_path):
    """A monorepo with valid, incomplete and broken skills."""
    root = tmp_path / "mono"
    write_skill_dir(make_skill("good", "alice", tags=["x"]), root / "packages" / "a" / "good")
    write_plain(
        root / "packages" / "b", "no-frontmatter", "# Plain Skill\n\nDoes something useful.\n"
    )
    write_plain(
        root / "deep" / "er" / "x", "no-description", "---\nname: no-description\n---\n# T\n"
    )
    write_plain(root, "broken-yaml", "---\nname: [unclosed\n---\nbody\n")
    return root


# -- discovery ------------------------------------------------------------------------------
def test_discovery_is_recursive_and_structured(mess):
    found = discovery.discover(mess)
    by_name = {c.name: c for c in found}
    assert set(by_name) >= {"good", "no-frontmatter", "no-description", "broken-yaml"}
    good = by_name["good"]
    assert good.status == "valid" and good.relative == "packages/a/good" and good.author == "alice"
    assert good.tags == ["x"] and len(good.sha256) == 64 and good.text.startswith("---")
    assert by_name["no-frontmatter"].status == "incomplete"
    assert by_name["no-description"].status == "incomplete"
    assert by_name["broken-yaml"].status == "invalid"
    assert good.to_dict()["origin"].endswith("good")


def test_discovery_can_be_non_recursive(mess):
    shallow = discovery.discover(mess, recursive=False)
    assert [c.name for c in shallow] == ["broken-yaml"]


def test_discovery_single_markdown_file_and_command_dirs(tmp_path):
    f = tmp_path / "review-code.md"
    f.write_text("---\ndescription: Review code\n---\nLook at the diff.\n")
    [c] = discovery.discover(f)
    assert c.format == "markdown" and c.name == "review-code" and c.status == "incomplete"
    cmds = tmp_path / "repo" / ".claude" / "commands"
    cmds.mkdir(parents=True)
    (cmds / "fix.md").write_text("Fix the bug\n")
    assert [c.format for c in discovery.discover(tmp_path / "repo")] == ["markdown"]
    with pytest.raises(OwlError, match="not a markdown"):
        discovery.discover(tmp_path / "x.txt") if (tmp_path / "x.txt").write_text("x") else None


def test_discovery_records_git_commit(tmp_path):
    repo = tmp_path / "gitrepo"
    write_skill_dir(make_skill("committed"), repo / "committed")
    gitutil.init(repo)
    gitutil.commit_all(repo, "add")
    with discovery.discover_source(str(repo)) as found:
        assert len(found[0].commit or "") == 40
    with discovery.discover_source(f"file://{repo}") as found:
        assert found[0].commit == gitutil.head_commit(repo)


def test_discovery_refuses_symlinked_root(tmp_path):
    real = tmp_path / "real"
    write_skill_dir(make_skill("s"), real / "s")
    (tmp_path / "link").symlink_to(real, target_is_directory=True)
    with pytest.raises(OwlError, match="symbolic link"):
        discovery.discover(tmp_path / "link")


# -- zip archives ---------------------------------------------------------------------------
def make_zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def test_zip_with_skills_is_discovered(tmp_path):
    z = make_zip(
        tmp_path / "skills.zip",
        {
            "pkg/zipped/SKILL.md": "---\nname: zipped\ndescription: From a zip\n---\n# Z\n",
            "pkg/zipped/scripts/run.sh": "echo hi",
        },
    )
    with discovery.discover_source(str(z)) as found:
        assert [(c.name, c.status, sorted(c.files)) for c in found] == [
            ("zipped", "valid", ["scripts/run.sh"])
        ]


@pytest.mark.parametrize("member", ["../evil/SKILL.md", "/abs/SKILL.md", "a/../../b/SKILL.md"])
def test_zip_path_traversal_is_rejected(tmp_path, member):
    z = make_zip(tmp_path / "bad.zip", {member: "---\nname: evil\ndescription: x\n---\n"})
    with pytest.raises(OwlError, match="Unsafe"), discovery.discover_source(str(z)):
        pass
    assert not (tmp_path / "evil").exists()


def test_zip_symlink_member_is_rejected(tmp_path):
    z = tmp_path / "link.zip"
    with zipfile.ZipFile(z, "w") as zf:
        info = zipfile.ZipInfo("s/SKILL.md")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")
    with pytest.raises(OwlError, match="symbolic link"), discovery.discover_source(str(z)):
        pass


def test_zip_bomb_limits(tmp_path, monkeypatch):
    z = make_zip(tmp_path / "big.zip", {"s/SKILL.md": "x" * 5000})
    monkeypatch.setattr(discovery, "MAX_ZIP_BYTES", 1000)
    with pytest.raises(OwlError, match="expands to more"), discovery.discover_source(str(z)):
        pass
    monkeypatch.setattr(discovery, "MAX_ZIP_BYTES", 10**9)
    monkeypatch.setattr(discovery, "MAX_ZIP_FILES", 0)
    with pytest.raises(OwlError, match="more than"), discovery.discover_source(str(z)):
        pass


# -- importer: suggestions and plans --------------------------------------------------------
def test_suggestions_for_incomplete_skills(mess):
    found = {c.name: c for c in discovery.discover(mess)}
    f = suggest_fields(found["no-frontmatter"], "me")
    assert f.name == "no-frontmatter" and f.author == "me" and f.version == "0.0.0"
    assert f.description == "Does something useful."
    assert set(f.generated) >= {"description", "author", "version"}


def test_plan_strict_vs_defaults(mess):
    candidates = discovery.discover(mess)
    strict = {
        i.candidate.name: i.action for i in build_plan(candidates, mode=STRICT, default_author="me")
    }
    assert strict == {
        "good": "add",
        "no-frontmatter": "skip",
        "no-description": "skip",
        "broken-yaml": "skip",
    }
    lenient = {
        i.candidate.name: i.action
        for i in build_plan(candidates, mode=DEFAULTS, default_author="me")
    }
    assert lenient == {
        "good": "add",
        "no-frontmatter": "add",
        "no-description": "add",
        "broken-yaml": "draft",
    }


# -- CLI: owl add --------------------------------------------------------------------------
def test_add_strict_imports_only_valid(mess):
    owl("init")
    result = owl("add", str(mess))
    assert "1 added" in result.stdout and "3 skipped" in result.stdout
    assert [s["name"] for s in json.loads(owl("list", "--json").stdout)] == ["good"]


def test_add_dry_run_changes_nothing(mess):
    owl("init")
    out = owl("add", str(mess), "--allow-incomplete", "--dry-run").stdout
    assert "add" in out and "draft" in out
    assert json.loads(owl("list", "--json").stdout) == []
    with LocalDB() as db:
        assert db.drafts() == []


def test_add_allow_incomplete_adds_defaults_and_keeps_drafts(mess):
    owl("init", "--author", "me")
    result = owl("add", str(mess), "--allow-incomplete")
    assert "3 added" in result.stdout and "1 draft" in result.stdout
    shown = json.loads(owl("show", "no-frontmatter", "--json").stdout)
    assert shown["author"] == "me" and shown["description"] == "Does something useful."
    assert shown["extra"]["owl_generated"] == ["author", "description", "name", "version"]
    assert shown["content"].startswith(
        "---\nname: no-frontmatter\ndescription:"
    )  # valid frontmatter
    assert "# Plain Skill" in shown["content"]  # body kept
    assert (
        not (mess / "packages" / "b" / "no-frontmatter" / "SKILL.md").read_text().startswith("---")
    )  # source untouched
    with LocalDB() as db:
        [draft] = db.drafts()
    assert draft["name"] == "broken-yaml" and draft["problems"]
    assert owl("validate", "--all", ok=False).exit_code == 1  # the draft is listed as failing


def test_add_never_relaxes_security_rules(tmp_path):
    owl("init")
    root = tmp_path / "src"
    write_skill_dir(make_skill("safe"), root / "safe")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    (root / "safe" / "leak").symlink_to(outside)  # symlinks are ignored, never followed
    owl("add", str(root), "--allow-incomplete")
    skill = json.loads(owl("show", "safe", "--json").stdout)
    assert "leak" not in skill["files"]
    z = make_zip(tmp_path / "bad.zip", {"../x/SKILL.md": "---\nname: x\ndescription: y\n---\n"})
    assert owl("add", str(z), "--allow-incomplete", ok=False).exit_code != 0


def test_interactive_enter_accepts_defaults(mess):
    owl("init", "--author", "me")
    result = owl("add", str(mess), "--interactive", input="\n\n\n")  # Enter, Enter, confirm
    assert "Incomplete skill 1/" in result.stdout
    names = {s["name"] for s in json.loads(owl("list", "--json").stdout)}
    assert names == {"good", "no-frontmatter", "no-description"}
    assert "Aborted" not in result.stdout


def test_interactive_edit_skip_all_and_quit(mess):
    owl("init", "--author", "me")
    # first incomplete: edit the fields; second: skip; confirm
    edit = "e\nrenamed-skill\nbob\n2.0.0\nMy own description\nt1,t2\ntopic1\n"
    result = owl("add", str(mess), "--interactive", input=edit + "s\ny\n")
    assert result.exit_code == 0, result.output
    shown = [s for s in json.loads(owl("list", "--json").stdout)]
    renamed = [s for s in shown if s["name"] == "renamed-skill"]
    assert renamed and renamed[0]["author"] == "bob" and renamed[0]["tags"] == ["t1", "t2"]
    assert not any(s["name"] == "no-description" for s in shown)  # skipped

    owl("init", "--author", "me2")
    quit_result = owl("add", str(mess), "--interactive", input="q\n", ok=False)
    assert quit_result.exit_code != 0 and "Aborted" in str(quit_result.exception)

    all_result = owl("add", str(mess), "--interactive", input="all\ny\n")
    assert all_result.exit_code == 0
    assert "Incomplete skill 2/" not in all_result.stdout  # 'all' stopped further questions


def test_interactive_does_not_ask_about_valid_skills(tmp_path):
    root = tmp_path / "ok"
    for i in range(5):
        write_skill_dir(make_skill(f"fine-{i}"), root / f"fine-{i}")
    owl("init")
    result = owl("add", str(root), "--interactive")  # no input at all: nothing to ask
    assert result.exit_code == 0 and "Incomplete skill" not in result.stdout


def test_scan_lists_candidates_without_importing(mess):
    owl("init")
    data = json.loads(owl("scan", str(mess), "--json").stdout)
    assert {d["status"] for d in data} == {"valid", "incomplete", "invalid"}
    assert json.loads(owl("list", "--json").stdout) == []
    owl("source", "add", "mono", str(mess))
    assert len(json.loads(owl("scan", "--json").stdout)) == 4  # uses the registered source


def test_import_command_md(tmp_path):
    owl("init", "--author", "me")
    f = tmp_path / "summarise.md"
    f.write_text("---\ndescription: Summarise a PR\n---\nSummarise the pull request.\n")
    owl("import", str(f), "--format", "command-md")
    shown = json.loads(owl("show", "summarise", "--json").stdout)
    assert (
        shown["description"] == "Summarise a PR"
        and "Summarise the pull request." in shown["content"]
    )
    assert os.path.exists(f)  # source untouched
