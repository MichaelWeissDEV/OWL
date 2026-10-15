# PostgreSQL backend

PostgreSQL is the recommended backend for a shared **server**. The database may run anywhere – OWL
only needs a connection URL – and several OWL servers can use different databases.

## Install the driver

```console
$ pip install "owl[postgres]"          # psycopg 3 with bundled libpq
```

## Create a database and role

```sql
CREATE ROLE owl LOGIN PASSWORD '…';
CREATE DATABASE owl OWNER owl;
```

OWL creates its tables on first use (`skills`, `skill_labels`, `skill_files`). The role needs
`CREATE` on the schema for that, plus – optionally – permission to run
`CREATE EXTENSION pg_trgm` (see below). On PostgreSQL 15+ the `public` schema no longer grants
`CREATE` to everyone; use a database you own or grant it explicitly.

## URLs

```text
postgresql://owl:secret@db.internal:5432/owl
postgres://owl:secret@db.internal/owl                # also accepted
postgresql+psycopg://owl:secret@db.internal/owl      # explicit driver
postgresql://owl@db.internal/owl?sslmode=require     # libpq options as query parameters
```

`postgres://` and `postgresql://` are rewritten to `postgresql+psycopg://` so the psycopg 3 driver is
used (SQLAlchemy would otherwise look for psycopg2).

## Using it

### As the server's database

Keep the password out of shell history and config files by using the environment:

```console
$ export OWL_DB_URL='postgresql://owl:secret@db.internal/owl'
$ export OWL_SERVER_TOKEN='long-random-token'
$ owl serve --host 0.0.0.0
```

### As the configured store of a machine

```console
$ owl init --backend postgres --location 'postgresql://owl:secret@db.internal/owl'
```

This writes the URL (including the password) to `~/.owl/config.json` (mode `0600`). To avoid that,
reference an environment variable instead:

```console
$ owl init --backend postgres --url-env OWL_DB_URL
```

Every command then reads the URL from `$OWL_DB_URL` at run time.

```{note}
Shell completion deliberately never connects to PostgreSQL. For a PostgreSQL-backed *local* store,
completion data comes from the cache that `list`, `search` and `pull` refresh.
```

## Search performance: `pg_trgm`

Substring search uses `lower(column) LIKE '%term%'`. On first connect OWL tries to run:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS ix_skills_name_trgm        ON skills USING gin (lower(name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_skills_description_trgm ON skills USING gin (lower(description) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_skills_content_trgm     ON skills USING gin (lower(content) gin_trgm_ops);
```

If the role may not create extensions, OWL silently continues without the indexes – search works,
using sequential scans, which is fine for thousands of skills. A DBA can create the extension once
(`CREATE EXTENSION pg_trgm;` as superuser, or via your cloud provider's console) and OWL will create
the indexes on its next start.

Tags, topics and authors are matched with ordinary indexed equality.

## Schema

See {doc}`../reference/database-schema`. OWL does not use migrations yet: the schema is created if
missing and never altered. Future incompatible changes will ship with documented migration steps.

## Backups

Use standard PostgreSQL tooling (`pg_dump`, WAL archiving). To move to a different backend, export
with `owl export --all --layout repo` or `owl pull --all` into another store – see
{doc}`../operations/backup`.
