# Skill format

A skill is a directory:

```text
pdf-tools/
├── SKILL.md          required – YAML frontmatter + markdown instructions
├── skill.json        optional – metadata overrides, written by OWL's directory/git store
├── scripts/extract.py
└── reference/forms.md
```

## `SKILL.md`

```markdown
---
name: pdf-tools
description: Extract text and tables from PDF files. Use when the user mentions PDFs.
author: michael
version: 1.2.0
tags: [pdf, documents]
topics: [office]
---

# PDF tools

Instructions for the agent ...
```

### Fields

| Field | Required | Rules |
| --- | --- | --- |
| `name` | yes | `[a-z0-9]+(-[a-z0-9]+)*`, at most 64 characters |
| `description` | yes | non-empty string; this is what agents use to decide when to load the skill |
| `author` | no | `[a-z0-9][a-z0-9._-]*` (lower-cased automatically); default is the author from `owl init --author`, otherwise `local` |
| `version` | no | any string, default `0.0.0` |
| `tags` | no | list or comma separated string; lower-cased, de-duplicated, sorted |
| `topics` | no | same as tags; use for broad subject areas. Aliases: `topic`, `categories` |

All of `author`, `version`, `tags` and `topics` are also accepted below a `metadata:` mapping – the
convention used by several published skills:

```yaml
metadata:
  version: "1.0.0"
```

Other frontmatter keys (`compatibility`, `license`, …) stay in the `SKILL.md` text untouched. They
are preserved because OWL always stores the **complete original file**.

### Tags versus topics

Both are free labels, searched with `--tag/-t` and `--topic/-T`. By convention *tags* are specific
(`git`, `sql`, `pdf`) and *topics* are broad areas (`devtools`, `databases`, `office`). OWL does not
enforce any vocabulary.

## `skill.json`

`skill.json` lets you set metadata without touching the frontmatter, and carries arbitrary extra
keys:

```json
{
  "author": "michael",
  "name": "pdf-tools",
  "version": "1.2.0",
  "description": "Extract text and tables from PDF files.",
  "tags": ["documents", "pdf"],
  "topics": ["office"],
  "license": "MIT",
  "homepage": "https://example.org/pdf-tools"
}
```

- The six known keys override the frontmatter.
- Every other key is kept as *extra* metadata, stored, hashed and transferred with the skill.
- OWL's directory store writes this file for every skill so that the git repository contains the
  complete, normalised metadata.

## Bundled files

Everything else in the directory belongs to the skill and is stored and installed with it – scripts,
reference documents, templates, binary files. Rules:

- Paths are relative and use `/`. Absolute paths, `..`, empty components and backslashes are
  rejected.
- `SKILL.md` and `skill.json` are reserved and cannot appear as bundled files.
- Skipped when reading a directory: `.git`, `__pycache__`, `node_modules`, `.DS_Store`,
  `.owl-install.json` and **all symlinks** (OWL never follows links, so a repository cannot make it
  read files outside the skill).
- A skill may be at most **20 MiB** in total.

## Validation

`owl validate PATH` reads one skill or a whole tree and lists every problem:

```console
$ owl validate ./skills
OK   michael/pdf-tools  (/.../skills/pdf-tools)
FAIL /.../skills/broken
       - Missing YAML frontmatter
       - Missing frontmatter 'name'
```

It exits with status 1 if any skill is invalid. Problems detected:

- missing, unclosed or malformed frontmatter; YAML errors; frontmatter that is not a mapping
- missing or malformed `name`; name too long
- invalid `author`
- missing `description`; empty `SKILL.md`; invalid UTF-8
- invalid `skill.json`
- reserved file names, size limit exceeded

Invalid skills are **skipped with a message** by `add` and `install`, and never stored.

## How a directory becomes a skill

1. Read all files below the directory (no symlinks).
2. Split `SKILL.md` into frontmatter and body; parse the YAML.
3. Read `skill.json` if present and overlay it onto the frontmatter values.
4. Fill in defaults (author, version), normalise tags/topics.
5. Validate.
6. Compute the SHA-256 hash.

Skills are found by walking a directory tree: every directory containing a `SKILL.md` is one skill
and its sub-directories belong to it (nested `SKILL.md` files are not treated as separate skills).
