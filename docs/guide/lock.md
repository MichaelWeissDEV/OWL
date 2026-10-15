# Reproducible installs: `owl.lock`

A lock file pins the skills installed in a **project** to the exact revision they came from, plus their
content hash, so that a teammate or CI job gets *the same* skills later – even after the registry has
moved on.

```console
$ owl install conventional-commits -r owl -t claude -t opencode -p     # install into the project
$ owl lock create                       # writes ./owl.lock
$ git add owl.lock && git commit -m "chore: lock skills"

# somewhere else, later:
$ owl lock install                      # fetches the pinned commits, verifies hashes, installs
$ owl lock verify                       # does the project still match the lock? (exit 1 if not)
```

All three take `--project-root DIR` (default: the current directory) and an explicit lock file path.

## What is recorded

```json
{
  "format": 1,
  "skills": [
    {
      "ref": "michaelweissdev/conventional-commits",
      "name": "conventional-commits",
      "version": "1.0.0",
      "sha256": "f43b…",
      "targets": ["claude", "opencode"],
      "source": {
        "kind": "registry",
        "registry": "owl",
        "url": "https://github.com/MichaelWeissDEV/owl-registry.git",
        "commit": "5339aa4…",
        "path": "skills/conventional-commits"
      }
    }
  ]
}
```

The file has no timestamps and is sorted, so `owl lock create` on an unchanged project produces an
identical file (no diff noise in git).

### Where the revision comes from (provenance)

OWL records the origin of a skill when it is imported or installed:

| How the skill arrived | Recorded |
| --- | --- |
| `owl add <git URL>` / local git repository | URL, requested ref, commit SHA, path inside the repository |
| `owl install … -r <registry>` | registry alias and URL, the commit that last changed the skill (from the index) or the registry's HEAD, path |
| `owl add <directory>` | directory path (and its commit if it is a repository) |

Provenance is stored in the install marker (`.owl-install.json`), in the install inventory and – for
imports – in the local database. It is **not** part of the skill's content hash.

Skills installed before provenance existed have no commit; `lock create` warns and locks them by hash
only. Reinstall them from their source to pin the revision.

## What `lock install` does

For every entry:

1. fetch exactly the locked **commit** of the source (shallow when the server allows it);
2. load the skill at the locked path;
3. compare its content hash with the locked hash – **a mismatch aborts that skill** and nothing is
   installed;
4. install it into the locked targets of the project (`--target` overrides).

Servers (`kind: server`) are fetched by alias from your configuration; directory sources by path.
The command exits with status 1 if any skill failed.

## What `lock verify` reports

`ok`, `missing` (not installed), `changed` (another version/hash is installed) or `modified`
(the installed files were edited locally).

## What the hash does and does not protect

```{important}
A SHA-256 hash detects that content changed. It is **not a signature**: it does not authenticate who
published the skill. Someone who controls the source can change the content *and* the hash. The lock
protects you from accidental drift and from content changing underneath a commit you pinned; it does
not protect you from a malicious publisher. Review skills you do not trust before installing them.
```
