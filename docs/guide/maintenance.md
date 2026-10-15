# Maintenance and inspection

## `owl doctor`

Checks the whole setup and prints a table of `OK` / `WARN` / `FAIL`:

```console
$ owl doctor
┏━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃      ┃ Check             ┃ Detail                              ┃
│ OK   │ owl version       │ 0.1.0                               │
│ OK   │ config file       │ /home/me/.owl/config.json           │
│ OK   │ mode              │ client                              │
│ OK   │ store (sqlite)    │ 42 skills                           │
│ OK   │ git               │ available                           │
│ WARN │ extra [server]    │ not installed (pip install 'owl[server]') │
│ OK   │ install dir       │ /home/me/.claude/skills             │
│ OK   │ remote team       │ https://skills.example.com - 120 skills │
```

Exit status is 1 only for hard failures (broken config, store cannot be opened, git backend without
a repository). Unreachable remotes and missing extras are warnings.

## `owl stats`

Counts skills, authors, tags and topics and lists the most used ones. `--json` for scripts.

## `owl outdated` / `owl update`

See {doc}`installing`.

## `owl diff`

See {doc}`syncing`.

## `owl config`

```console
$ owl config show             # full config, tokens masked
$ owl config path             # file location
$ owl config get author
$ owl config set mode client
$ owl config set default_remote team
$ owl config set install_dir ~/.claude/skills
$ owl config set default_remote ""      # unset
```

Settable keys: `mode`, `author`, `install_dir`, `default_remote`. Remotes are managed with
`owl remote …`, the store with `owl init`. See {doc}`configuration`.

## `owl export`

See {doc}`standalone` – writes skills as plain files, handy for backups and for converting a database
to a git repository.

## Housekeeping

- `owl remove REF` deletes from the library (confirmation unless `-y`); with `-r` it deletes on the
  server (token required).
- `~/.owl/state.json` is safe to delete: it only contains bookmarks (the next sync will then treat
  differing skills as diverged rather than fast-forwarding) and the completion cache.
