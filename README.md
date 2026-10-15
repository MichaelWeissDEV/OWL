# OWL - a skill manager

**Documentation:** build it with `cd docs && make html` (Sphinx, Read the Docs ready - see
`.readthedocs.yaml`) or read the sources in [`docs/`](docs/index.md).

OWL manages **skills** (a `SKILL.md` with YAML frontmatter plus optional bundled files, as used
by Claude Code and other agents). It keeps them in a database or a git repository, lets you
search by text, author, tag and topic, installs them into your agent's skills directory and can
synchronise them between machines through one or more **OWL servers**.

```
            ┌────────────── standalone ──────────────┐
            │  SQLite file   or   plain git repo     │
            └────────────────────────────────────────┘
   client ──── HTTP ────►  owl serve  ──►  SQLite / PostgreSQL / git repo
   client ──── HTTP ────►  owl serve  ──►  (a second, independent server)
```

| Mode | What it is | Typical setup |
| --- | --- | --- |
| **standalone** | Local library only. | `owl init` (SQLite) or `owl init --backend git` |
| **server** | `owl serve` exposes a store over HTTP. | `owl serve --db-url postgresql://...` |
| **client** | Local library + any number of remote servers to search, `pull` from and `push` to. | `owl init --mode client`, `owl remote add ...` |

## Install

```bash
pip install ".[server,postgres]"      # inside a virtualenv; or: uv pip install ...
```

The `server` extra adds FastAPI/uvicorn (needed for `owl serve`), the `postgres` extra adds the
PostgreSQL driver. A plain `pip install .` is enough for standalone and client use. Requires
Python 3.13+ and, for git features, `git`.

### Shell completion

```bash
owl --install-completion     # bash, zsh, fish, PowerShell - then restart your shell
```

Completion covers commands, options, **skill names, authors, tags, topics, remote names and
installed skills**. It only reads local data (your SQLite/git library and a small cache that is
refreshed whenever you list or search a remote); it never contacts a server while you press TAB.

## Quick start (standalone)

```bash
owl init --author michael            # SQLite database in ~/.owl/skills.sqlite3
owl add ./my-skills                  # import every SKILL.md below a directory
owl add https://github.com/acme/skills.git      # ...or from a git repository
owl search "commit message" --tag git --author michael
owl show conventional-commits
owl install conventional-commits     # -> ~/.claude/skills/conventional-commits (Claude Code)
owl install conventional-commits -p  # -> ./.claude/skills (project local)
owl install conventional-commits -t opencode -p   # OpenCode, this project
owl install --all -r owl -t claude -t opencode    # everything from the default registry
```

`owl install` also installs straight from a git repository or a directory without importing
them first - pick one skill, several, or everything:

```bash
owl install https://github.com/acme/skills.git --skill pdf --skill docx
owl install https://github.com/acme/skills.git --all
```

OWL only overwrites directories it created itself (it leaves a `.owl-install.json` marker), unless
you pass `--force`. `owl installed` lists what it installed, `owl uninstall NAME` removes it.

## Registries (the default way to get skills)

A **registry** is a git repository of skills with a generated `index.json` and a quick-to-read
`INDEX.md` (including every skill's last update). OWL knows one out of the box:
`owl` → <https://github.com/MichaelWeissDEV/owl-registry>.

```bash
owl search git -r owl                       # search the registry index
owl install michaelweissdev/conventional-commits -r owl
owl install --all -r owl --tag git -t opencode
owl registry add team https://github.com/acme/skills-registry.git
```

Create your own - CI regenerates the index for you:

```bash
owl registry init ~/work/my-registry --git-url git@github.com:me/my-registry.git
owl registry publish ./my-skill --dir ~/work/my-registry     # copy in + update index
```

Registries are read-only for clients (contribute by pull request) and combine freely with
PostgreSQL-backed servers: `owl search kubernetes --all`.

## Tools: Claude Code, OpenCode, Codex, Gemini, Copilot, Cursor

OWL installs to the directory each tool reads, globally or per project, for one or several tools at
once (`owl targets` lists them):

| Target | Global | Project (`-p`) |
| --- | --- | --- |
| `claude` | `~/.claude/skills` | `.claude/skills` |
| `opencode` | `~/.config/opencode/skills` | `.opencode/skills` |
| `agents` / `codex` | `~/.agents/skills` | `.agents/skills` |
| `gemini` | `~/.gemini/skills` | `.gemini/skills` |
| `copilot` | `~/.copilot/skills` | `.github/skills` |
| `cursor` | `~/.cursor/skills` | `.cursor/skills` |

Set defaults with `owl config set targets claude,opencode`; add your own tools as `custom_targets`
in the config.

## Skill format

A skill is a directory:

```
my-skill/
  SKILL.md        # required: YAML frontmatter + markdown
  skill.json      # optional: metadata overrides (written by OWL's git/directory store)
  scripts/...     # optional: any bundled files
```

Frontmatter fields OWL understands (also accepted below a `metadata:` key):

```yaml
---
name: pdf-tools            # required, lower-case-with-hyphens, max 64 chars
description: Extract text from PDFs. Use when ...   # required
author: michael            # default: the author set in `owl init --author`
version: 1.2.0
tags: [pdf, documents]
topics: [office]
---
```

`skill.json` may override any of these and add arbitrary extra keys. A skill is identified by
`author/name`; a bare `name` works whenever it is unambiguous. Check files with `owl validate PATH`,
scaffold with `owl new my-skill`.

## Storage backends

| Backend | Command | Notes |
| --- | --- | --- |
| SQLite | `owl init` | Default. One file, no server. |
| PostgreSQL | `owl init --backend postgres --location postgresql://u:pw@host/db` | Prefer `--url-env OWL_DB_URL` so the password is not written to the config. |
| git / plain files | `owl init --backend git [--git-url URL]` | Skills live as `skills/<author>/<name>/{SKILL.md,skill.json,...}` in a working copy. `owl sync` commits, rebases onto the remote and pushes. |

```bash
owl init --backend git --git-url git@github.com:me/my-skills.git
owl add ./new-skill && owl sync
```

Any git repository with `SKILL.md` files can also be used read-only as an install source (see above).

## Server mode

```bash
export OWL_SERVER_TOKEN=change-me                  # needed for writes (push/delete)
export OWL_DB_URL=postgresql://owl:pw@db.internal/owl
owl serve --host 0.0.0.0 --port 8765               # default host is 127.0.0.1
owl serve --private                                # token also required for reads
```

* Without a token the server is **read-only**. The token is compared in constant time.
* `--db-url` accepts a SQLite path or a PostgreSQL URL (`postgresql://` is mapped to the
  psycopg 3 driver). Without it, the store from `owl init` is served - including a git working copy.
* Run several servers (different hosts, databases or teams) side by side; clients can use any
  number of them. Put TLS in front of the server (reverse proxy) when it is not on localhost.
* Docker: `docker build -t owl . && docker run -p 8765:8765 -e OWL_SERVER_TOKEN=... -e OWL_DB_URL=... owl`.

### API (`/api/v1`)

| Method & path | Purpose |
| --- | --- |
| `GET /health`, `GET /info` | status, version, skill count |
| `GET /skills?q=&author=&tag=&topic=&limit=&offset=` | search (tags/topics repeatable, all must match) |
| `GET /skills/{author}/{name}` | full skill including files (base64) |
| `PUT /skills/{author}/{name}` | create/update (token) |
| `DELETE /skills/{author}/{name}` | delete (token) |
| `GET /facets/{author\|tag\|topic}` | values with counts |

## Client mode

```bash
owl init --mode client
owl remote add team https://skills.example.com --token-env OWL_TEAM_TOKEN
owl remote add public https://owl.example.org
owl remote list

owl search pdf -r team                # one remote
owl search pdf --all                  # local store + every remote, results labelled by source
owl show team-skill -r team
owl install team-skill -r team        # install directly from a server
owl pull alice/pdf-tools -r team      # copy into the local library
owl pull --all -r team
owl push my-skill -r team             # publish (needs a write token)
```

In `client` mode, read commands (`list`, `search`, `show`, `install`, `authors`, `tags`, `topics`)
default to the default remote; use `--local` to look at the local library instead. Tokens are stored
in `~/.owl/config.json` (mode 0600) or read from an environment variable (`--token-env`).

`pull` and `push` never overwrite silently. OWL remembers the content hash of each skill at the last
sync; if a skill changed on **both** sides it is skipped, reported as *diverged* and the command exits
with status 1. Use `--force` to overwrite deliberately.

## Command overview

`init`, `config show|get|set|path`, `new`, `validate`, `add`, `list`, `search`, `show`, `remove`,
`authors`, `tags`, `topics`, `stats`, `export`, `install`, `uninstall`, `installed`, `outdated`,
`update`, `targets`, `registry init|publish|index|add|list|remove|update`, `remote add|list|remove|ping`, `pull`, `push`, `diff`, `sync`, `serve`, `doctor`. Every listing supports `--json`. Run `owl COMMAND --help` for all options.

Environment: `OWL_HOME` (default `~/.owl`: config, state, default database), `OWL_DB_URL`,
`OWL_SERVER_TOKEN`.

## Development

```bash
uv sync --all-extras
uv run pytest                  # PostgreSQL tests run when OWL_TEST_POSTGRES_URL is set
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv sync --group docs && uv run sphinx-build -W -b html docs docs/_build/html
```

Layout: `src/owl/models.py` (data model, hashing), `parsing.py` (SKILL.md / skill.json),
`stores/` (SQL, directory, remote - one interface, one shared contract test suite), `server.py`
(FastAPI), `installer.py`, `sync.py` (pull/push planning), `cli.py`, `completion.py`.
CI (`.github/workflows/ci.yml`) runs lint, type checks, tests on Linux and macOS, the PostgreSQL
suite against a service container and a build.

## Security notes

* Skill files from git repositories and servers are treated as untrusted: relative paths are
  validated (no absolute paths, `..`), symlinks are never followed, installs only replace
  directories OWL created.
* The server binds to `127.0.0.1` by default and is read-only unless a token is set.
* OWL installs files only - it never executes skill scripts.
