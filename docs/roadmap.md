# Roadmap

Ideas, roughly in order of expected value. Nothing here is promised.

## Server

- **Per-user accounts and scoped tokens** (read / write / admin, per author namespace).
- **Hash-only endpoint** (`HEAD`/`GET …/sha`) so `pull --all` and `outdated` can skip downloads.
- **Version history** – keep previous versions of a skill with `pull author/name@1.2.0`.
- **Ranked full-text search** (PostgreSQL `tsvector`, SQLite FTS5).
- **Schema migrations** (Alembic) for future table changes.
- **Webhooks / events** when skills change.
- **Metrics** (`/metrics` in Prometheus format) and structured logs.

## Trust

- **Signed skills** (Sigstore / minisign) and verification on install.
- **Author ownership** – only the owner of a namespace may publish under it.
- **Lint rules** for risky patterns in bundled scripts (`owl audit`).

## Client

- **Lock file** for installed skills (`owl.lock`) and `owl sync-installed`.
- **Dependencies** between skills.
- **Interactive picker** when a repository contains several skills.
- **Server-to-server mirroring** (`owl mirror`).
- **Windows** in the CI matrix.

## Registries

- `owl registry search-all`: aggregate several registries' indexes into one searchable snapshot.
- Signed index (`index.json.sig`) and `sha256` verification on install.
- `owl registry submit`: open a pull request against a registry from the CLI.

## Packaging

- Publish to PyPI via trusted publishing; multi-arch container image on GHCR.
- Homebrew formula.

Suggestions and contributions are welcome – see {doc}`development/contributing`.
