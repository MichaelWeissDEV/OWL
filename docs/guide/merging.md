# Merging and transferring between stores

There are two different kinds of "merge":

| | What it merges | Tool |
| --- | --- | --- |
| **Git merge** | commits and files of a repository | `git merge`, pull requests |
| **Skill merge** | the *skills* of one store into another, understanding names, versions and metadata | `owl merge` |

`owl merge` works on skills, not on lines of text, and it never overwrites blindly.

```console
$ owl merge team --into mine --dry-run          # what would happen?
$ owl merge team --into mine                    # copy what is safe, report the rest
$ owl merge team --into mine --interactive      # decide each conflict
$ owl registry merge team --into mine           # same command
```

`SOURCE` and `--into` can each be `local` (your library), a configured server or registry alias, or a
directory (a registry checkout or git library).

## What is compared

| Result | Meaning |
| --- | --- |
| `only-source` | exists only in the source → **copied** |
| `only-dest` | exists only in the destination → left alone |
| `identical` | same content hash → nothing to do |
| `content-conflict` | same `author/name`, different content; the note says which version is newer |
| `metadata-conflict` | identical `SKILL.md` and files, but version/description/tags/… differ |
| `name-collision` | the destination keeps names unique (registries, git libraries) and another author already owns the name |

## Conflict handling

Without options, conflicts are **not applied**: OWL copies the safe skills, writes a JSON report (default
`$OWL_HOME/merge-reports/`, or `--report FILE`) and exits with status 1. The destination's conflicting
skills are untouched.

| Option | Effect |
| --- | --- |
| `--on-conflict fail` (default) | leave conflicts unresolved and report them |
| `--on-conflict source` | the source wins for content/metadata conflicts (name collisions stay unresolved) |
| `--on-conflict dest` | the destination wins everywhere |
| `--interactive` | ask for each conflict |

Interactive choices: **s**ource wins · **d**estination stays · **r**ename the source copy (the name is
validated, the frontmatter is updated consistently) · **c**ompare (unified diff of `SKILL.md` and
`skill.json`) · s**k**ip · **m**anual (recorded in the report for you to fix by hand) · **q**uit
(nothing is merged). A name collision cannot be "source wins" – rename it or keep the destination.

## Destinations must be writable

| Destination | Writable? |
| --- | --- |
| `local` library | yes |
| directory / checkout of a registry | yes; index files are regenerated, `--commit` commits locally |
| registry alias with a **local directory** URL | yes (that directory) |
| registry alias with a **git URL** | through a working checkout in `$OWL_HOME/checkouts/<alias>` – the read-only cache is never modified; nothing is pushed |
| server alias | yes with a write token |

A read-only registry is never changed by a merge or any other transfer. To contribute to someone
else's registry use `owl registry publish --to ALIAS --branch … --push --pr`
({doc}`registries`).

## Transfer matrix

| From → To | Command |
| --- | --- |
| local → local | – |
| local → git registry | `owl registry publish` or `owl merge local --into REG` |
| git registry → local | `owl pull -r REG`, `owl add <registry URL>` or `owl merge REG --into local` |
| git registry → git registry | `owl merge A --into B` |
| local → server | `owl push -r SRV` or `owl merge local --into SRV` |
| server → local | `owl pull -r SRV` or `owl merge SRV --into local` |
| server → git registry | `owl merge SRV --into REG` |

`pull`/`push` additionally use sync bookmarks to detect divergence of single skills
({doc}`syncing`); `merge` compares the two current states.
