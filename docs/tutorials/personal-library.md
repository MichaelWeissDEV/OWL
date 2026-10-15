# A personal skill library

**Result:** all your skills in one searchable library, installable into any project.

## 1. Initialise

```console
$ owl init --author michael
```

## 2. Collect what you already have

```console
$ owl add ~/.claude/skills            # adopt skills you already installed by hand
$ owl add ~/projects/team-skills --subdir skills
$ owl list
```

Skills without an `author` get `michael`. Invalid ones are listed as `skipped` with the reason –
fix them (`owl validate PATH`) and re-run `owl add`.

## 3. Add tags and topics

Open each `SKILL.md` and add frontmatter fields:

```yaml
tags: [git, review]
topics: [devtools]
```

then `owl add` the directory again. Changed skills update in place.

## 4. Use them

```console
$ owl search review
$ owl install review-pr -p            # only for this project
$ owl install review-pr               # for all projects (~/.claude/skills)
```

## 5. Keep installed skills fresh

```console
$ owl outdated
$ owl update
```

## 6. Back it up

```console
$ owl export --all -o ~/backups/skills-$(date +%F) --layout repo
```

or copy `~/.owl/skills.sqlite3`.
