# Migrating existing skills

## From a folder of skills (e.g. `~/.claude/skills`)

```console
$ owl add ~/.claude/skills
```

Skills are copied into the library; the originals stay as they are (and are *not* marked as OWL
installations – `owl install --force` can adopt them later).

## From a git repository

```console
$ owl add https://github.com/acme/skills.git
$ owl add https://github.com/acme/skills.git --subdir plugins/office --skill pdf --skill docx
```

## From SQLite to PostgreSQL

```console
$ owl export --all -o /tmp/skills --layout repo        # from the SQLite library
$ owl init --backend postgres --url-env OWL_DB_URL      # switch the store
$ owl add /tmp/skills                                   # import (author/name come from skill.json)
```

or via a server: `owl serve` the SQLite library, then from a client `owl pull --all` + `owl push --all`
to the PostgreSQL-backed server.

## From a database to git

```console
$ owl export --all -o ~/my-skills --layout repo
$ cd ~/my-skills && git init && git add . && git commit -m "import"
$ git remote add origin git@github.com:me/my-skills.git && git push -u origin main
$ owl init --backend git --location ~/my-skills --git-url git@github.com:me/my-skills.git
```

## Fixing skills that fail validation

```console
$ owl validate ./old-skills
FAIL /.../old-skills/foo
       - Missing frontmatter 'description'
```

Typical fixes: add `description`, rename `Foo_Bar` to `foo-bar`, close the `---` frontmatter.
