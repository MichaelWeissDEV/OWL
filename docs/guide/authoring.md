# Authoring skills

## Scaffold

```console
$ owl new sql-review --dir ./skills --description "Review SQL migrations for safety" -t sql -t review
```

`owl new` validates the name, creates `./skills/sql-review/SKILL.md` with correct, quoted YAML
frontmatter (name, description, author, version `0.1.0`, tags) and a heading. Existing directories are
never overwritten.

## Write a good description

Agents decide whether to load a skill from its `name` and `description` alone, so:

- say **what** it does and **when** to use it ("Use when the user asks for …");
- mention trigger words users would actually say;
- keep it to a few sentences – search results truncate long descriptions.

OWL searches the description, so it also determines how people find the skill.

## Validate while you work

```console
$ owl validate ./skills            # whole tree
$ owl validate ./skills/sql-review # one skill
```

Add this to a pre-commit hook or CI job for skill repositories (see
{doc}`../tutorials/publish-from-ci`).

## Versioning

Bump `version` when you change behaviour. OWL does not interpret it (no semver ranges), but it is
shown in listings, in `outdated`, and recorded when installing. Change detection always uses the
content hash, so editing a skill without bumping the version is still detected as a change.

## Organising a repository of skills

Any layout works for `add` and `install` – OWL finds every `SKILL.md`. Two common layouts:

```text
skills/                       skills/
  pdf/SKILL.md                  michael/pdf/SKILL.md      <- OWL's own layout
  docx/SKILL.md                 michael/docx/SKILL.md          (see git backend)
```

Use `owl export --layout repo` to convert a database library into OWL's native git layout.

## Testing a skill locally

```console
$ owl add ./skills/sql-review
$ owl install sql-review -p           # into the current project (.claude/skills; add -t opencode for OpenCode)
```

Re-run `owl add` after edits; unchanged skills are detected by hash and left alone, changed skills
are updated in place (the previous version is replaced – use git for history).
