# Quickstart

Five minutes from nothing to an installed skill. All commands are safe to run: use a scratch
`OWL_HOME` if you want to keep your real setup untouched.

```console
$ export OWL_HOME=$(mktemp -d)        # optional: experiment without touching ~/.owl
```

## 1. Initialise a library

```console
$ owl init --author michael
OWL initialised (standalone, sqlite) - config: /.../config.json
```

This creates `config.json` and a SQLite database. `--author` is the author name given to skills that
do not declare one.

## 2. Create or import skills

Scaffold a new skill:

```console
$ owl new release-notes --dir ./my-skills -t writing -t git
Created my-skills/release-notes/SKILL.md
$ owl validate ./my-skills
OK   michael/release-notes  (/.../my-skills/release-notes)
```

Import everything below a directory – or from a git repository:

```console
$ owl add ./my-skills
added michael/release-notes 0.1.0
$ owl add https://github.com/acme/skills.git --skill pdf
```

## 3. Find skills

```console
$ owl list
$ owl search release                       # free text
$ owl search -t git -T writing              # tag and topic filters
$ owl search --author michael "notes"       # author + text
$ owl show release-notes                    # metadata + rendered markdown
$ owl tags                                  # all tags with counts
```

## 4. Install a skill

```console
$ owl install release-notes                 # -> ~/.claude/skills/release-notes
$ owl install release-notes -p              # -> ./.claude/skills (this project only)
$ owl installed
$ owl uninstall release-notes
```

You can also install straight from a git repository without importing it first:

```console
$ owl install https://github.com/acme/skills.git --all
```

## 5. Share with others

Run a server (read-only unless you set a token):

```console
$ pip install ".[server]"
$ OWL_SERVER_TOKEN=change-me owl serve --port 8765
```

On another machine:

```console
$ owl init --mode client
$ owl remote add team http://server:8765 --token change-me
$ owl search pdf -r team
$ owl pull michael/release-notes -r team
$ owl push my-skill -r team
```

## Where to go next

- {doc}`concepts` – the vocabulary used throughout the docs.
- {doc}`../guide/index` – every feature in depth.
- {doc}`../tutorials/index` – complete scenarios.
