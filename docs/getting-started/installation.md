# Installation

## Requirements

| Requirement | Needed for |
| --- | --- |
| Python **3.13+** | everything |
| `git` on `PATH` | git backend, `owl sync`, installing/adding from git URLs |
| A PostgreSQL server (13+) | only if you choose the PostgreSQL backend |

## Install from source

OWL is not on PyPI yet; install from a checkout.

```console
$ git clone https://github.com/MichaelWeissDEV/OWL.git
$ cd OWL
$ python3.13 -m venv .venv && . .venv/bin/activate
$ pip install .                       # standalone + client
$ pip install ".[server]"             # + `owl serve`  (FastAPI, uvicorn)
$ pip install ".[postgres]"           # + PostgreSQL driver (psycopg 3)
$ pip install ".[all]"                # everything
```

With [uv](https://docs.astral.sh/uv/):

```console
$ uv sync --all-extras                # development environment, then: uv run owl ...
```

## Extras

| Extra | Adds | Required for |
| --- | --- | --- |
| *(none)* | SQLAlchemy, PyYAML, Typer, httpx, rich | standalone, git backend, client mode |
| `server` | FastAPI, uvicorn | `owl serve` |
| `postgres` | `psycopg[binary]` | PostgreSQL backend (client *or* server side of a database) |
| `all` | all of the above | |

If an extra is missing OWL tells you exactly which one to install:

```console
$ owl serve
error: The server needs extra dependencies: pip install 'owl[server]'
```

## Verify the installation

```console
$ owl --version
owl 0.1.0
$ owl doctor
```

`owl doctor` checks the configuration, the store, `git`, the optional extras, the install directory
and every configured remote (see {doc}`../guide/maintenance`).

## Shell completion

```console
$ owl --install-completion          # detects bash / zsh / fish / PowerShell
```

Restart the shell afterwards. {doc}`../guide/completion` explains what is completed and how it works.

## Where OWL keeps its files

Everything lives below `OWL_HOME` (default `~/.owl`):

| Path | Content |
| --- | --- |
| `config.json` | configuration, created with mode `0600` |
| `state.json` | sync bookmarks and the completion cache |
| `skills.sqlite3` | default SQLite database |
| `repo/` | default working copy of the git backend |
| `registries/<name>/` | cached shallow clones of git registries |

Set `OWL_HOME` to relocate or isolate an installation – the test suite and all examples in this
documentation that must not touch your real setup use it.

## Upgrading and uninstalling

```console
$ pip install --upgrade .
$ pip uninstall owl
$ rm -rf ~/.owl                       # removes config, database and caches - irreversible
```

Installed skills (in `~/.claude/skills`, `~/.config/opencode/skills` or elsewhere) are **not** touched by uninstalling OWL.
