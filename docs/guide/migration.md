# Migration

OWL migrates instead of discarding. This page lists what changed between versions and how to move.

## Registry layout: `skills/<author>/<name>/` → `skills/<name>/`

The author is metadata now, not a directory. Convert a registry (or a git-backend library):

```console
$ owl registry migrate ./my-registry --dry-run
$ owl registry migrate ./my-registry
$ owl registry upgrade ./my-registry --overwrite     # also refresh workflow, README, CONTRIBUTING
```

Details, conflict handling and guarantees: {doc}`registries`. Registries you only *consume* need no
migration – OWL reads both layouts.

## Registry index format 1 → 2

Format 2 adds `license`, `compatibility`, `size`, `revision` and the generated `stats.json` /
`STATS.md`. Clients read both formats; regenerate with `owl registry index` (or let CI do it).

## Configuration

| Before | Now |
| --- | --- |
| `install_dir` (default `~/.claude/skills`) | `targets` (default `["claude"]`); `install_dir` is an optional override. A legacy value equal to the old default is ignored on load |
| `owl init --install-dir` | `owl init --target` |
| remotes were always servers | remotes have a `kind`: `server` or `registry` (existing entries are servers) |

Existing `config.json` files keep working; OWL writes the new keys when it next saves the file.

## Installations

Installations made before per-file hashes were recorded have no baseline: OWL cannot tell whether
you edited them, so it treats them as unmodified. They gain a baseline the next time they are
reinstalled or updated.

## Data safety changes

- `install`, `update` and `uninstall` now **refuse locally modified skills** unless `--force`
  (the old copy is saved under `$OWL_HOME/backups/installs`).
- `export` no longer deletes an existing target directory; it requires `--force`.
- `owl init --git-url` never changes the `origin` of an existing repository.
