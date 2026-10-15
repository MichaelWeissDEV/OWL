# Installing skills

```console
$ owl install SOURCE [--skill NAME]... [--all] [--dir DIR | --project] [--ref REF] [--subdir PATH] [-r REMOTE] [--local] [--force]
```

## Sources

`SOURCE` is interpreted in this order:

1. a **git URL** (`https://…`, `ssh://…`, `git://…`, `file://…`, `git@host:path`),
2. an existing **local path** (unless `-r` is given),
3. otherwise a **reference** (`author/name` or `name`) resolved in the library, or on the remote
   when `-r` is given / the default remote applies (client mode).

```console
$ owl install review-pr                                   # from the library
$ owl install review-pr -t opencode -t claude -p          # for two tools, this project
$ owl install alice/pdf-forms -r team                     # from a server
$ owl install https://github.com/acme/skills.git --all    # from git: everything
$ owl install https://github.com/acme/skills.git -s pdf -s docx --ref v2
$ owl install ./local-skills --subdir office --all        # from a directory
```

For repositories (git URL or directory) with several skills you must choose: `--skill/-s NAME`
(repeatable) or `--all`. A repository with exactly one skill needs neither. Several sources may be
given at once (`owl install a/x b/y https://…`).

### Everything from a registry or server

Without a source, `--all` installs every skill of the selected `--remote` (a registry or a server),
optionally filtered:

```console
$ owl install --all -r owl
$ owl install --all -r owl --tag git --topic devtools --author michaelweissdev
```

## Where skills are installed

| Option | Target |
| --- | --- |
| *(default)* | the configured targets (initially `claude`: `~/.claude/skills`) |
| `--target/-t NAME` | a tool: `claude`, `opencode`, `codex`, `gemini`, `copilot`, `cursor`, `agents`, `all`, or a custom target; repeatable |
| `--project/-p` | the tool's project directory relative to the current directory (`.claude/skills`, `.opencode/skills`, …) |
| `--dir/-d DIR` | an explicit directory (bypasses targets) |

See {doc}`tools` for the full list of tools and directories.

Each skill goes to `<target>/<name>/`: `SKILL.md`, all bundled files and `.owl-install.json`:

```json
{
  "ref": "alice/pdf-forms",
  "version": "0.3.0",
  "sha256": "…",
  "source": "team"
}
```

`source` is the remote name, `local`, or the git URL/path – used by `outdated` and `update`.

## Safety rules

- OWL replaces a directory only if it contains an OWL marker **from the same `author/name`**.
- A directory without marker (you created it) or with another author's skill of the same name is
  refused. `--force` overrides.
- Installation writes into a temporary sibling directory first and swaps it in, so an interrupted
  install does not leave a half-written skill.
- Bundled file paths are validated again before writing (no absolute paths, no `..`).
- Skills fetched from git are cloned shallowly into a temporary directory that is removed afterwards;
  symlinks in the repository are ignored.
- OWL **never executes** anything from a skill – it only copies files.

## Listing, updating, removing

```console
$ owl installed                       # skills installed by OWL (ref, version, path)
$ owl outdated                        # which have a newer version at their source? (exit 1 if any)
$ owl update                          # re-install all outdated ones
$ owl update pdf-forms --dry-run
$ owl uninstall pdf-forms
```

`outdated`/`update` ask the original source: the remote (or `local` library) by name, or the git
URL/directory again. A comparison uses the content hash, so edits without a version bump are
found too. `update` only touches skills OWL installed. An unreachable source is reported as
*unavailable* and skipped.

All of them (and `installed`) accept `--target`, `--project` and `--dir` to select which install locations to look at.
