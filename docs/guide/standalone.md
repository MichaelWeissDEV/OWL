# Standalone mode

Standalone mode is a local skill library without any server. It is the default and needs no extras.

## Initialise

```console
$ owl init --author michael
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--mode` | `standalone` | `standalone`, `client` or `server` |
| `--backend` | `sqlite` | `sqlite`, `postgres` or `git` |
| `--location` | `~/.owl/skills.sqlite3` (sqlite), `~/.owl/repo` (git) | database file / URL / working copy |
| `--author` | `local` | default author for skills without one |
| `--target/-t` | `claude` | default install target(s), e.g. `opencode` |

`owl init` can be repeated; it rewrites the store section of the existing config and keeps remotes.

## Everyday workflow

```console
$ owl add ./skills                  # import / update from a directory
$ owl add https://github.com/acme/skills.git     # ...or a git repository
$ owl list
$ owl search "pull request" -t git
$ owl show michael/review-pr
$ owl install review-pr
$ owl remove michael/review-pr -y   # delete from the library
```

### `add` in detail

```console
$ owl add SOURCE [--ref BRANCH] [--subdir PATH] [--author NAME] [--skill NAME ...]
```

- `SOURCE` is a directory or a git URL (`https://`, `ssh://`, `git@host:path`, `file://`). Git
  sources are shallow-cloned (`--depth 1`) into a temporary directory that is deleted afterwards.
- `--ref` selects a branch or tag, `--subdir` restricts the search to a sub-directory.
- `--skill` (repeatable) imports only skills with these names.
- Invalid skills are reported as `skipped` and not stored; the command fails if nothing was added.
- Re-adding an identical skill is a no-op. A changed skill with the same `author/name` replaces the
  stored one (and gets a new `updated_at`).

## Exporting

```console
$ owl export michael/review-pr -o ./out            # ./out/review-pr/ (like an install dir)
$ owl export --all -o ./repo --layout repo         # ./repo/skills/<author>/<name>/ + skill.json
```

`--layout repo` produces OWL's native git layout – a database library becomes a git repository this
way (`git init && git add . && git commit`, then use the {doc}`git backend <git-backend>`).

## Statistics

```console
$ owl stats
local: 12 skills, 3 authors, 21 tags, 6 topics
Top authors: michael (9), alice (2), bob (1)
Top tags: git (4), sql (3), ...
```
