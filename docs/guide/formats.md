# Formats, export and templates

OWL's canonical format is the open **Agent Skills** layout:

```text
skill-name/
  SKILL.md        frontmatter (name, description, …) + instructions
  scripts/  references/  assets/     optional bundled files
```

Everything else is a **conversion**. OWL says plainly where a conversion loses information.

## Built-in formats

| Format | Output | Lossless? |
| --- | --- | --- |
| `agent-skills` | directory `<out>/<name>/` with `SKILL.md` and all bundled files | yes |
| `zip` | `<name>.zip` containing `<name>/SKILL.md`, `skill.json` and all bundled files | yes |
| `markdown` | a single `<name>.md` (the `SKILL.md` text) | **no** – bundled files are not included |
| `command-md` | a prompt/command file: frontmatter `description` + body | **no** – name, version, author, tags and bundled files are not representable; this is a *command*, not a skill |

```console
$ owl format list
$ owl export conventional-commits --format agent-skills --out ./out       # ./out/conventional-commits/
$ owl export conventional-commits --format markdown --out ./skill.md
$ owl export --all --format zip --out ./archives
$ owl export conventional-commits --format command-md --out .claude/commands/commit.md
```

Lossy exports **do not pretend** otherwise: the CLI prints how many bundled files are *not* part of the
export and lists them (`--json` has `not_exported` and `lossy`). Existing targets are never replaced
without `--force`.

```{note}
Not every `AGENTS.md`, rules file or prompt file is a skill. OWL only converts what actually
corresponds to a skill's content: `SKILL.md`-style text, and – as an explicit, labelled, lossy
mapping – single prompt/command markdown files. Tool-specific rule formats (for example Cursor rules
or `AGENTS.md`) are intentionally *not* advertised as supported; use a custom template if you need
one, and review the result.
```

## Importing other formats

```console
$ owl import ./commands/summarise.md --format command-md
$ owl import ./old-skills.zip --format zip
```

`import` is `add --allow-incomplete`: the name comes from the file name, the description from the
frontmatter or the first paragraph, generated fields are recorded ({doc}`importing`).

## Custom formats (templates)

A template is a text file with `{{ skill.field }}` placeholders:

```text
---
name: {{ skill.name }}
author: {{ skill.author }}
version: {{ skill.version }}
description: {{ skill.description }}
---

# {{ skill.title }}

{{ skill.body }}
```

```console
$ owl format add custom ./template.md          # test-rendered against a sample before it is accepted
$ owl format show custom
$ owl export conventional-commits --format custom --out ./out.md
$ owl format remove custom
```

### Fields

`skill.name`, `skill.author`, `skill.version`, `skill.description`, `skill.title` (first `#` heading
or the name), `skill.body` (text without frontmatter), `skill.tags`, `skill.topics`, `skill.source`,
`skill.sha256`, `skill.content` (the complete `SKILL.md`), `skill.license`, `skill.compatibility`,
`skill.ref`, and `skill.meta.<key>` for extra metadata keys.

### Filters

Add `|filter` after the field: `raw`, `yaml`, `json`, `md` (escape markdown), `list` (comma
separated). Without a filter OWL chooses by context:

| Where | Default escaping |
| --- | --- |
| inside the template's leading `---` frontmatter block | `yaml` – values are quoted when needed, so a description like `Extract text: from PDFs` stays valid; multi-line values become one-line quoted strings and can never fake a frontmatter delimiter |
| any placeholder in a template whose extension is `json` | `json` |
| elsewhere (body text) | `raw`; lists as `a, b` |

### What templates cannot do

They are *declarative*. There is no code execution, no loops or conditions, no attribute access beyond the
listed fields, no file access. Anything else is an error: unknown fields or filters (`Unknown field
'skill.nope'`), Jinja-style tags (`{% … %}`), arithmetic (`{{ 7*7 }}`). Write `\{{` for a literal `{{`.
The rendered output is validated where possible (frontmatter must parse, `.json` must be valid JSON).
Format names are restricted to lower-case letters, digits and hyphens and cannot shadow a built-in
name; templates live in `$OWL_HOME/formats/`.
