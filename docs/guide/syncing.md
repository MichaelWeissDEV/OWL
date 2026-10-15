# Synchronising: pull, push, diff

Synchronisation copies skills between the local library and a remote server.

```console
$ owl pull [REF...] [--all] [-r REMOTE] [--force]
$ owl push [REF...] [--all] [-r REMOTE] [--force]
$ owl diff REF [-r REMOTE]
```

`-r` defaults to the default remote, or the only remote if there is just one.

## The three hashes

For each skill OWL knows three content hashes:

- **L** – the local library's version (absent if missing),
- **R** – the remote's version,
- **B** – the *bookmark*: the hash both sides had at the last successful `pull`/`push` (stored in
  `state.json`).

## Decision table

### `pull` (remote → local)

| Situation | Result |
| --- | --- |
| R missing | skipped: not found on remote |
| L = R | ok, up to date |
| L missing | **copy** (new) |
| L ≠ R, `--force` | **copy** (forced) |
| L ≠ R, R = B | skipped: local is ahead (push it, or `pull --force`) |
| L ≠ R, L = B | **copy** (fast-forward: only the remote changed) |
| otherwise | skipped: **diverged** – changed on both sides |

### `push` (local → remote)

| Situation | Result |
| --- | --- |
| L missing | skipped: not found locally |
| L = R | ok, up to date |
| R missing | **copy** (new) |
| L ≠ R, `--force` | **copy** (forced) |
| L ≠ R, L = B | skipped: remote is ahead (pull it, or `push --force`) |
| L ≠ R, R = B | **copy** (only local changed) |
| otherwise | skipped: **diverged** |

After each successful copy or "up to date" result the bookmark is updated.

```{important}
OWL never overwrites a diverged skill without `--force`. The command exits with status **1** if any
skill was skipped as diverged or could not be resolved, so scripts and CI notice.
```

## Resolving a divergence

1. Look at the difference: `owl diff alice/pdf-forms -r team` (unified diff of `SKILL.md`,
   `skill.json` and text files; binary files are summarised; exit status 1 when different).
2. Decide:
   - keep the remote version: `owl pull alice/pdf-forms -r team --force`
   - keep yours: `owl push alice/pdf-forms -r team --force`
   - merge by hand: export, edit, `owl add`, then `push --force`.

## References and `--all`

- `REF` may be `author/name` or a bare name; a bare name is resolved on the *source* side of the
  transfer (remote for pull, library for push). Ambiguous or unknown names are reported per skill
  and the rest continues.
- `--all` transfers every skill from the source.

## First sync of a new server

```console
$ owl push --all -r team          # needs the write token
```

## Mirroring a server

```console
$ owl pull --all -r public        # periodic: cron / systemd timer
```

Re-running is cheap: unchanged skills are detected by hash and nothing is transferred or rewritten.

## Git backend sync

`owl sync` is a different mechanism (git commit/rebase/push) – see {doc}`git-backend`. The two
compose: a git-backed library can be a client of a server too.
