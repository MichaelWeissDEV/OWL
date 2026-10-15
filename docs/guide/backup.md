# Backup and restore

```console
$ owl backup create                         # -> $OWL_HOME/backups/archives/owl-backup-<time>.zip
$ owl backup create --include-registries    # also the cached registry clones
$ owl backup list
$ owl backup verify owl-backup-….zip        # exit 1 if anything is wrong
$ owl backup restore owl-backup-….zip --dry-run
$ owl backup restore owl-backup-….zip
```

## What is in a backup

| Content | Archive path |
| --- | --- |
| configuration (remotes, targets, tokens!) | `config.json` |
| personal database: favorites, collections, notes, installation inventory, history, drafts, trust, provenance, sync state | `local.sqlite3` (a consistent snapshot, taken with SQLite's backup API) |
| catalog (SQLite backend) | `catalog.sqlite3` |
| catalog (git backend) | `catalog-git/skills/…` – the skill files, **not** the `.git` history (push the repository for that) |
| completion cache / state | `state.json` |
| custom format templates | `formats/…` |
| cached registries (optional) | `registries/<alias>/…` |
| `manifest.json` | format version, OWL version, creation time, backend, schema versions, size and SHA-256 of every file |

Backups carry a **format version**. The archive file is created with mode `0600` because
`config.json` may contain access tokens.

```{note}
For a **PostgreSQL** catalog the archive does not contain the database – the manifest says so. Use
`pg_dump` for the server ({doc}`../operations/backup`).
```

## Verifying

`owl backup verify` checks: the zip is readable, the manifest is valid and has a known format, every file
listed is present and its hash matches, nothing unlisted is in the archive, SQLite files pass
`PRAGMA integrity_check`, and the schema versions are not newer than this OWL understands (a backup
from a newer OWL is refused – upgrade first).

## Restoring

`owl backup restore`:

1. **verifies** the archive – if anything is wrong, *nothing* is restored;
2. makes a **pre-restore backup** of the current state (`owl-backup-pre-restore-….zip`);
3. restores each file atomically (written next to the target, then renamed);
4. only restores to a fixed whitelist of locations – an archive cannot write anywhere else, and unsafe
   member names are refused.

It asks for confirmation unless `--yes`; `--dry-run` lists the files that would be replaced.
