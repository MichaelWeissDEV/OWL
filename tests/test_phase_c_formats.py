"""Export formats and the safe, declarative template engine."""

from __future__ import annotations

import json
import zipfile

import pytest
from typer.testing import CliRunner

from owl import formats
from owl.cli import app
from owl.models import OwlError, Skill
from owl.parsing import split_frontmatter, write_skill_dir
from tests.conftest import make_skill

runner = CliRunner()


def owl(*args, ok=True):
    result = runner.invoke(app, list(args))
    if ok:
        assert result.exit_code == 0, result.output + str(result.exception)
    return result


@pytest.fixture
def lib(tmp_path):
    src = tmp_path / "src"
    content = (
        '---\nname: pdf-tools\ndescription: "Extract text: from PDFs"\n---\n# PDF tools\n\nBody.\n'
    )
    write_skill_dir(
        make_skill(
            "pdf-tools",
            "alice",
            tags=["pdf", "docs"],
            version="1.2.0",
            description="Extract text: from PDFs",
            content=content,
            files={"scripts/run.py": b"print(1)"},
        ),
        src / "p",
    )
    write_skill_dir(make_skill("plain", "bob"), src / "q")
    owl("init")
    owl("add", str(src))
    return tmp_path


SPEC_TEMPLATE = """---
name: {{ skill.name }}
author: {{ skill.author }}
version: {{ skill.version }}
description: {{ skill.description }}
---

# {{ skill.title }}

{{ skill.body }}
"""


def sample(**kw):
    kw.setdefault("description", "A description")
    content = kw.pop("content", "---\nname: x\ndescription: d\n---\n# My Title\n\nBody text.\n")
    return Skill(author="alice", name="x", content=content, **kw)


# -- template engine ------------------------------------------------------------------------
def test_spec_example_template_renders_valid_yaml_even_with_colons():
    skill = sample(description="Extract text: from PDFs # really", version="1.0.0")
    out = formats.render_template(SPEC_TEMPLATE, skill)
    fm, body, problems = split_frontmatter(out)
    assert problems == [] and fm["description"] == "Extract text: from PDFs # really"
    assert fm["version"] == "1.0.0" and "# My Title" in out and "Body text." in body


def test_yaml_injection_is_neutralised():
    nasty = sample(description="x\nadmin: true\n---\nevil")
    out = formats.render_template(SPEC_TEMPLATE, nasty)
    fm, _body, problems = split_frontmatter(out)
    assert problems == [] and "admin" not in fm and fm["description"] == "x\nadmin: true\n---\nevil"


def test_tags_render_as_flow_list_in_frontmatter_and_text_in_body():
    template = "---\ntags: {{ skill.tags }}\n---\nTags: {{ skill.tags }}\n"
    out = formats.render_template(template, sample(tags=["b", "a"]))
    assert out.splitlines()[1] == "tags: [a, b]" and out.splitlines()[3] == "Tags: a, b"


def test_json_templates_are_escaped_and_validated():
    template = (
        '{"name": {{ skill.name }}, "desc": {{ skill.description }}, "tags": {{ skill.tags }}}'
    )
    out = formats.render_template(
        template, sample(description='say "hi"\nnow', tags=["a"]), extension="json"
    )
    assert json.loads(out) == {"name": "x", "desc": 'say "hi"\nnow', "tags": ["a"]}
    with pytest.raises(formats.TemplateError, match="not valid JSON"):
        formats.render_template("{ broken {{ skill.name }}", sample(), extension="json")


def test_explicit_filters_and_meta_fields():
    s = sample(extra={"license": "MIT", "homepage": "https://x.example"})
    out = formats.render_template(
        "{{ skill.description|json }} {{ skill.meta.homepage }} {{ skill.license }} {{ skill.title|md }}",
        s,
    )
    assert out == '"A description" https://x.example MIT My Title'
    assert (
        formats.render_template("{{ skill.description|md }}", sample(description="a*b_c"))
        == "a\\*b\\_c"
    )


@pytest.mark.parametrize(
    "template, message",
    [
        ("{{ skill.nope }}", "Unknown field"),
        ("{{ user.name }}", "Unknown placeholder"),
        ("{{ skill.name.__class__ }}", "Unknown field"),
        ("{{ skill.name|exec }}", "Unknown filter"),
        ("{% for x in y %}{% endfor %}", "Unsupported template syntax"),
        ("{{ skill.name }} {{ 7*7 }}", "Unsupported template syntax"),
        ("---\nname: {{ skill.name }}\n  bad: [unclosed\n---\nx", "frontmatter is invalid"),
    ],
)
def test_templates_cannot_do_anything_but_substitute(template, message):
    with pytest.raises(formats.TemplateError, match=message):
        formats.render_template(template, sample())


def test_escaped_braces_are_literal():
    assert (
        formats.render_template("\\{{ literal }} {{ skill.name }}", sample()) == "{{ literal }} x"
    )


# -- format registry and export ---------------------------------------------------------------
def test_format_add_list_show_remove(lib, tmp_path):
    tpl = tmp_path / "template.md"
    tpl.write_text(SPEC_TEMPLATE)
    owl("format", "add", "custom", str(tpl))
    listing = owl("format", "list").stdout
    assert "custom\ttemplate\t.md" in listing and "agent-skills\tbuilt-in" in listing
    assert "markdown" in listing and "lossy" in listing
    assert "{{ skill.name }}" in owl("format", "show", "custom").stdout
    assert any(f["name"] == "custom" for f in json.loads(owl("format", "list", "--json").stdout))
    owl("format", "remove", "custom")
    assert owl("format", "show", "custom", ok=False).exit_code != 0


@pytest.mark.parametrize("name", ["../evil", "agent-skills", "Bad Name", ""])
def test_format_names_are_validated(lib, tmp_path, name):
    tpl = tmp_path / "t.md"
    tpl.write_text("{{ skill.name }}")
    assert owl("format", "add", name or " ", str(tpl), ok=False).exit_code != 0


def test_broken_templates_are_rejected_at_registration(lib, tmp_path):
    tpl = tmp_path / "bad.md"
    tpl.write_text("{{ skill.secret }}")
    assert owl("format", "add", "bad", str(tpl), ok=False).exit_code != 0
    assert "bad" not in owl("format", "list").stdout


def test_export_custom_format(lib, tmp_path):
    tpl = tmp_path / "t.md"
    tpl.write_text(SPEC_TEMPLATE)
    owl("format", "add", "custom", str(tpl))
    out = tmp_path / "out" / "skill.md"
    owl("export", "pdf-tools", "--format", "custom", "--out", str(out))
    text = out.read_text()
    assert text.startswith(
        "---\nname: pdf-tools\nauthor: alice\nversion: 1.2.0\ndescription: 'Extract text: from PDFs'"
    )


def test_markdown_export_is_honest_about_bundled_files(lib, tmp_path):
    out = tmp_path / "skill.md"
    result = owl("export", "pdf-tools", "--format", "markdown", "--out", str(out))
    assert out.read_text().startswith("---\nname: pdf-tools")
    assert "NOT part of this export" in result.output and "scripts/run.py" in result.output
    data = json.loads(
        owl(
            "export", "pdf-tools", "--format", "markdown", "--out", str(out), "--force", "--json"
        ).stdout
    )
    assert data[0]["not_exported"] == ["scripts/run.py"] and "NOT included" in data[0]["lossy"]
    clean = owl("export", "plain", "--format", "markdown", "--out", str(tmp_path / "plain.md"))
    assert "NOT part" not in clean.output  # nothing lost, nothing claimed


def test_export_never_overwrites_without_force(lib, tmp_path):
    out = tmp_path / "skill.md"
    out.write_text("precious")
    assert (
        owl("export", "plain", "--format", "markdown", "--out", str(out), ok=False).exit_code != 0
    )
    assert out.read_text() == "precious"
    owl("export", "plain", "--format", "markdown", "--out", str(out), "--force")
    assert out.read_text() != "precious"


def test_export_directory_zip_and_command_md(lib, tmp_path):
    out = tmp_path / "dirs"
    owl("export", "pdf-tools", "--out", str(out))
    assert (out / "pdf-tools" / "scripts" / "run.py").read_bytes() == b"print(1)"
    owl("export", "pdf-tools", "--format", "zip", "--out", str(tmp_path / "z"))
    with zipfile.ZipFile(tmp_path / "z" / "pdf-tools.zip") as zf:
        assert sorted(zf.namelist()) == [
            "pdf-tools/SKILL.md",
            "pdf-tools/scripts/run.py",
            "pdf-tools/skill.json",
        ]
    result = owl("export", "pdf-tools", "--format", "command-md", "--out", str(tmp_path / "cmd.md"))
    body = (tmp_path / "cmd.md").read_text()
    assert (
        body.startswith("---\ndescription: 'Extract text: from PDFs'\n---") and "name:" not in body
    )
    assert "NOT part of this export" in result.output


def test_export_several_to_a_directory_and_unknown_format(lib, tmp_path):
    out = tmp_path / "many"
    owl("export", "--all", "--format", "markdown", "--out", str(out))
    assert sorted(p.name for p in out.iterdir()) == ["pdf-tools.md", "plain.md"]
    assert owl("export", "plain", "--format", "nonsense", ok=False).exit_code != 0
    assert owl("export", ok=False).exit_code != 0


def test_import_rejects_custom_templates(lib, tmp_path):
    tpl = tmp_path / "t.md"
    tpl.write_text("{{ skill.name }}")
    owl("format", "add", "custom", str(tpl))
    assert owl("import", str(tpl), "--format", "custom", ok=False).exit_code != 0
    with pytest.raises(OwlError):
        formats.export_skill(sample(), "does-not-exist", None)
