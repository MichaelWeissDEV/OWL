# Shell completion

## Install

```console
$ owl --install-completion          # modifies your shell's startup file
$ owl --show-completion             # print the script instead of installing
```

Supported shells: bash, zsh, fish, PowerShell (detected automatically). Restart the shell afterwards.
Under zsh, make sure `compinit` is loaded.

## What is completed

| Position | Candidates |
| --- | --- |
| commands, sub-commands, options | all of them |
| skill `REF` arguments (`show`, `install`, `remove`, `pull`, `push`, `diff`, `export`) | `author/name` and bare `name` |
| `--author/-a` | known authors |
| `--tag/-t` | known tags |
| `--topic/-T` | known topics |
| `--remote/-r`, `remote remove/ping`, `registry remove/update` | configured remote and registry names |
| `--target/-t` | built-in and custom install targets |
| `uninstall`, `update` | skills installed by OWL in the default targets |

## Where candidates come from

Completion runs on every `<TAB>`, so it follows strict rules:

1. **Local data only – never the network.** No server is contacted while you type.
2. Sources: the local library (when it is a SQLite file or a git working copy that exists) plus a
   **cache** in `state.json` that is refreshed whenever `list`, `search`, `pull` or `add` ran. That is
   how names from remote servers become completable: search them once.
3. A PostgreSQL-backed local library is *not* queried; the cache is used.
4. It never creates files or directories and never raises – any problem simply yields no suggestions.
5. Heavy imports (FastAPI, uvicorn, httpx clients) are not loaded.

```console
$ owl search pdf -r team          # fills the cache with the team server's skills
$ owl show al<TAB>                # -> alice/pdf-forms
```

## Troubleshooting

- *Nothing is completed for remote skills* – run a `list`/`search` against the remote once.
- *Stale suggestions* – delete `~/.owl/state.json` (cache is rebuilt) or accept that removed skills
  stay in the cache until then.
- *Slow completion* – check that the local library is on a local disk; completion opens the SQLite
  file on each press.
