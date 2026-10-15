# Git backend

With the git backend the skill library is a **plain directory of files in a git working copy**.
There is no database; history, review, branches and hosting come from git.

## Layout

```text
<working copy>/
└── skills/
    └── <author>/
        └── <name>/
            ├── SKILL.md
            ├── skill.json
            └── ...bundled files
```

`skill.json` holds the normalised metadata (see {doc}`skill-format`), `SKILL.md` is stored verbatim.
Files are written byte for byte – no newline translation – so the content hash is stable across
platforms.

## Set up

New repository (no remote yet):

```console
$ owl init --backend git --author michael
```

Clone an existing repository:

```console
$ owl init --backend git --git-url git@github.com:me/my-skills.git
```

Custom working copy location:

```console
$ owl init --backend git --location ~/work/my-skills --git-url https://github.com/me/my-skills.git
```

`init` clones the URL if the directory is not a repository yet, otherwise it only (re)sets `origin`.

## Working with it

Everything that works with SQLite works here too:

```console
$ owl add ./new-skill          # writes skills/<author>/<name>/...
$ owl search git
$ owl install my-skill
$ owl remove michael/old-skill -y
```

Edit files in the working copy directly if you like – OWL re-reads the directory on every command.
A skill whose `SKILL.md` has become invalid is ignored with a warning on stderr:

```text
owl: ignoring invalid skill /.../skills/michael/x: Invalid YAML: ...
```

## Synchronising: `owl sync`

```console
$ owl sync -m "add pdf skill"
```

1. commit all local changes (`git add -A`, commit message from `-m`; if `user.name`/`user.email` are
   not configured, `owl`/`owl@localhost` are used for that commit),
2. `git fetch` and **rebase** onto `origin/<branch>`,
3. push.

If there is no `origin`, the changes are committed locally and OWL says so. If the rebase hits a
conflict, OWL **aborts the rebase** (the repository is never left half-merged) and exits with an
error telling you to resolve it manually in the working copy with `git pull --rebase`.

## Serving a git library

A git-backed library can be exposed to clients like any other store:

```console
$ OWL_SERVER_TOKEN=... owl serve        # serves the configured git working copy
```

Pushes from clients are written into the working copy; run `owl sync` on the server (for example from
cron) to publish them to the git remote.

## Using a repository only as an install source

You do not need the git backend to *use* somebody else's repository:

```console
$ owl install https://github.com/acme/skills.git --skill pdf
$ owl add     https://github.com/acme/skills.git          # import into your library
```

Any repository with `SKILL.md` files works; see {doc}`installing`.

## When to choose git

| Choose git when… | Choose a database when… |
| --- | --- |
| you want history, review and branches | you want fast search over thousands of skills |
| the library is small/medium | many users write concurrently |
| you already host skills on GitHub/GitLab | you want to run a shared server |
