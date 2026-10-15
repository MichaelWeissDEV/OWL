# The local library

OWL works fully offline. Your **local library** is a skill catalog (SQLite by default, or a git
working copy) *plus* a personal SQLite database for everything that is about **you** rather than
about the skills: favorites, collections, notes, install inventory, history and more.

```{mermaid}
flowchart LR
    subgraph "catalog (SkillStore)"
      C[(SQLite skills.sqlite3<br/>or PostgreSQL / git)]
    end
    subgraph "personal data - never published"
      L[(local.sqlite3<br/>favorites · collections · notes<br/>installations · history · drafts<br/>sources · trust · sync state)]
    end
    CLI[owl CLI] --> C
    CLI --> L
```

The personal data references skills by their `author/name` text, so it survives when you switch the
catalog backend. **None of it is ever uploaded** to a registry or server.

## Favorites, collections, notes

```console
$ owl favorite add conventional-commits
$ owl favorite list
$ owl collection create security --description "things I use for audits"
$ owl collection add security sql-tuner secure-review
$ owl collection show security
$ owl install --collection security -t opencode       # install the whole set
$ owl note set sql-tuner "Useful for code reviews"
$ owl note show sql-tuner
```

Search and listings show `★` (favorite), `✓` (installed) and `↑` (update available) and accept
`--favorites`, `--installed` and `--collection NAME` ({doc}`searching`).

## Skill metadata

```console
$ owl metadata show conventional-commits            # metadata + local overrides, favorite, note
$ owl metadata set conventional-commits version 1.1.0
$ owl metadata set conventional-commits tags "git, release"
$ owl metadata set conventional-commits license MIT   # any other key becomes extra metadata
$ owl metadata unset conventional-commits license
$ owl metadata set conventional-commits priority high --local   # local-only, not part of the skill
```

- Changes are **validated first**; a change that would make the skill invalid is refused and nothing
  changes.
- `SKILL.md` and the original source are never modified: the metadata lives in the catalog
  (and `skill.json` in a git library).
- The name is the skill's identity and cannot be changed; changing the author moves the skill to its
  new `author/name`.
- Previous content hashes are remembered in the catalog's revision history (below).

### Editing

```console
$ owl edit conventional-commits          # opens $VISUAL / $EDITOR on SKILL.md
```

The result is checked before it is stored. If it is invalid you can edit again, save it as a **draft**
or abort (`--on-invalid ask|draft|abort`); the valid skill is never replaced by an invalid one.

## Drafts

Incomplete material that could not be repaired automatically ({doc}`importing`) and invalid edits are
kept as local drafts:

```console
$ owl drafts list
$ owl drafts show 3
$ owl drafts edit 3          # fix it in your editor
$ owl drafts promote 3       # becomes a regular library skill once valid
$ owl drafts discard 3
$ owl validate --all         # validates the library *and* lists drafts as failing
```

## History and installation inventory

```console
$ owl history                      # installs, updates, imports, pulls/pushes (latest first)
$ owl history --json --limit 100
```

Every install records the skill, version, hash, target tool, directory, scope (global/project/custom),
source and time in the local database; uninstall removes the record. The directory itself remains the
source of truth (its `.owl-install.json` marker), the database is your inventory.

## Sources and trust

```console
$ owl source add work-skills ~/work/skills          # a directory or git URL to scan
$ owl scan                                          # discover in all registered sources (no import)
$ owl source list                                   # remotes, registries and registered sources
$ owl trust add owl --note "official registry"
$ owl trust list
```

Trust is a **label for you** (shown in `source list`); OWL does not verify publishers.

## Databases, migrations and backups

OWL's SQLite schemas are versioned. Pending migrations run automatically when a database is opened,
each step in its own transaction (SQLite DDL is made transactional, so a failing step leaves no
half-created tables).

- Before migrating an **existing** SQLite database OWL copies it to `$OWL_HOME/backups/db`
  (`<name>-<scope>-v<from>-<timestamp>.sqlite3`).
- A database written by a **newer** OWL is refused untouched.
- Databases from before migrations existed are adopted as version 1 (their data is kept).

```console
$ owl db status          # schema versions and pending migrations
$ owl db migrate         # apply explicitly
$ owl db backup          # copy the SQLite files into $OWL_HOME/backups/db
```

For PostgreSQL use `pg_dump` ({doc}`../operations/backup`); the schema version table
(`owl_migrations`) is the same.

### Schema versions

| Scope | Version | Content |
| --- | --- | --- |
| `catalog` | 1 | `skills`, `skill_labels`, `skill_files` |
| `catalog` | 2 | `skill_revisions`: every content hash a skill has had (back-filled from existing rows) |
| `local` | 1 | `favorites`, `collections`, `collection_skills`, `notes`, `metadata_overrides`, `sources`, `trusted_sources`, `installations`, `operation_history`, `sync_state`, `drafts`, `local_meta` |

Details: {doc}`../reference/database-schema`.

### Why plain `LIKE` search and not FTS5?

SQLite FTS5 was evaluated. A measurement on this project (5,000 skills of ~3 KB each, substring search
over name, description, author, tags and full text) takes **about 30–40 ms** with the current query,
which is below what a person notices. FTS5 would change the matching semantics from *substring* to
*token*, so results would differ between backends, and it needs index maintenance. It stays a candidate
for much larger libraries (the trigram tokenizer keeps substring semantics); PostgreSQL gets `pg_trgm`
indexes already.
