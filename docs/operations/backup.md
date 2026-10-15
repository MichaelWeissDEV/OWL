# Backup and restore

## What to back up

| Backend | Data |
| --- | --- |
| PostgreSQL | the database (`skills`, `skill_labels`, `skill_files`) |
| SQLite | the `.sqlite3` file |
| git | the repository (it *is* the backup if pushed) |
| client | optional: `config.json` (remotes, tokens) |

`state.json` is rebuildable.

## PostgreSQL

```console
$ pg_dump --format=custom --file=owl-$(date +%F).dump "$OWL_DB_URL"
$ pg_restore --clean --dbname=owl_new owl-2026-10-15.dump
```

## SQLite

Use the online backup API rather than copying a file that may be mid-write:

```console
$ sqlite3 skills.sqlite3 ".backup 'skills-backup.sqlite3'"
```

## OWL's own backup command

`owl backup create` archives the *local* state (config, personal database, SQLite or git catalog, formats,
optionally cached registries) with a verified manifest – see {doc}`../guide/backup`. It does not replace
`pg_dump` for a PostgreSQL server.

## Portable backup through OWL

Independent of the backend, this produces plain files that any OWL (or git) can read:

```console
$ owl export --all -r team -o ./backup --layout repo     # from a server
$ owl export --all --local -o ./backup --layout repo     # from the local library
```

Restore into any store:

```console
$ owl add ./backup
```

(`add` reads `skill.json`, so authors, versions, tags and extras are restored exactly; the content hash
of each skill is identical to the original.)

## Disaster recovery for a server

1. Provision a database, restore the dump (or `owl add ./backup` into the new store).
2. Start `owl serve` with the same token.
3. Clients' sync bookmarks remain valid because hashes are preserved.
