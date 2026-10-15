# Troubleshooting

Start with `owl doctor`.

## Installation and start-up

| Symptom | Cause / fix |
| --- | --- |
| `error: The server needs extra dependencies: pip install 'owl[server]'` | install the `server` extra |
| `error: PostgreSQL support is missing: pip install 'owl[postgres]'` | install the `postgres` extra |
| `error: The postgres backend needs a URL like postgresql://…` | `store.location` is not a URL; re-run `owl init --backend postgres --location URL` |
| `error: Environment variable X is not set` | the store uses `url_env` / a remote uses `token_env` and the variable is missing in this shell |
| `Invalid config file …` | fix or delete `~/.owl/config.json` |
| Python < 3.13 | OWL requires 3.13; use `uv` or pyenv |

## Skills not found / skipped

| Symptom | Fix |
| --- | --- |
| `skipped … Missing YAML frontmatter` | the file must start with `---` on the first line |
| `Invalid YAML: mapping values are not allowed here` | quote values that contain `: ` (`description: "Use when: …"`) |
| `Invalid skill name` | lower case, digits, single hyphens; ≤ 64 chars |
| `No SKILL.md found` | the file must be named exactly `SKILL.md`; hidden dirs like `.git` are skipped |
| `owl: ignoring invalid skill …` (git backend) | a hand-edited `SKILL.md` in the working copy is invalid; fix it |
| `'x' is ambiguous` | use `author/name` |

## Installing

| Symptom | Fix |
| --- | --- |
| `already exists and was not installed by owl (use --force)` | you have a hand-made directory of that name; move it or use `--force` |
| `holds a/x, refusing to replace it with b/x` | another author's skill with the same name is installed; use `--force` or uninstall first |
| `N skills found (…); choose with --skill or use --all` | repositories with several skills need a choice |

## Remotes

| Symptom | Fix |
| --- | --- |
| `Remote 'x' is unreachable` | URL, DNS, firewall, TLS certificate; test with `curl URL/api/v1/health` |
| `HTTP 401 … check the token` | wrong/missing token (or `--private` server) |
| `HTTP 403 … read-only` | the server was started without `OWL_SERVER_TOKEN` |
| `HTTP 422 … does not match the URL` | internal inconsistency; re-add the skill |
| `HTTP 413` from the proxy | raise `client_max_body_size` / `max_size` |
| `skipped … diverged` | see {doc}`../guide/syncing`; use `owl diff` then `--force` |

## Git backend

| Symptom | Fix |
| --- | --- |
| `Merge conflict while syncing` | resolve in the working copy: `git pull --rebase`, then `owl sync` |
| `git push failed … rejected` | someone pushed meanwhile; run `owl sync` again |
| authentication errors | OWL never prompts; configure SSH keys or a credential helper |
| `git is not installed or not on PATH` | install git |

## Completion

| Symptom | Fix |
| --- | --- |
| nothing for remote skills | run `owl search -r NAME` once to fill the cache |
| not working at all | re-run `owl --install-completion` and restart the shell; zsh needs `compinit` |

## PostgreSQL

| Symptom | Fix |
| --- | --- |
| `permission denied for schema public` | grant `CREATE` on the schema or use a database you own (PG 15+) |
| `could not create extension pg_trgm` | harmless; ask a superuser to `CREATE EXTENSION pg_trgm` for faster search |
| connection errors | check `sslmode`, host, firewall; test with `psql "$OWL_DB_URL"` |

## Getting help

Open an issue with the output of `owl --version`, `owl doctor` and the failing command (redact tokens).
