# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/); versions follow
[Semantic Versioning](https://semver.org/) from 1.0.

## Unreleased

### Added (Phase C – local skill management)

- Versioned migrations with automatic SQLite backups and transactional DDL; catalog schema v2
  (revision history); local personal SQLite database.
- `favorite`, `collection`, `note`, `metadata`, `edit`, `drafts`, `history`, `source`, `trust`, `db`,
  `scan`, `format`, `import`; `install --collection`; `validate REF|--all`.
- Discovery in directories, monorepos, git, zip archives and markdown files; `add` with strict,
  `--allow-incomplete`, `--interactive` and `--dry-run`.
- Export as directory, zip, markdown, command-md and safe declarative templates.
- Search: sort, offset, favorite/installed/collection filters, status flags in table and JSON.

### Fixed

- A markdown frontmatter closing delimiter must now start at column 0 (an indented `---` inside a
  YAML block scalar used to end the frontmatter early).

### Security / data safety

- `replace_dir` stages new content, renames the old directory aside and restores it on any failure
  (it used to delete the old directory first).
- Installations record per-file hashes; reinstall, `update` and `uninstall` refuse locally modified
  skills unless `--force` (old copies go to `$OWL_HOME/backups/installs`).
- `DirectoryStore.upsert` is atomic; `export` no longer deletes existing directories.
- `owl installed --json` no longer crashes (slotted dataclass serialisation).

### Changed (registries)

- **Flat registry layout** `skills/<name>/` (author is metadata); name collisions between authors are
  refused. `owl registry migrate` / `upgrade` convert old registries; old layouts remain readable.
- Index format 2 (license, compatibility, size, revision), `stats.json`, `STATS.md`.
- Registry CI split into a read-only `validate` job and a separate `index` job with write access.
- New `owl registry check`, `migrate`, `upgrade`.

### Branding

- OWL logo, new README with badges and an alpha notice, `CONTRIBUTING.md`, code of conduct,
  security policy, issue and pull request templates.

### Added

- **Registries**: git repositories with a generated `index.json` / `INDEX.md` (with per-skill last update), a CI workflow template and the commands `owl registry init|publish|index|add|list|remove|update`. The default registry `owl` (`MichaelWeissDEV/owl-registry`) is configured on fresh installs.
- **Install targets**: native support for Claude Code, OpenCode, Codex CLI, Gemini CLI, GitHub Copilot and Cursor (`owl targets`, `--target`, `--project`), custom targets, several targets per install, `install --all -r REMOTE` with filters, multiple sources per `install`.

- Three storage backends: SQLite, PostgreSQL (with `pg_trgm` indexes) and a git/plain-file layout.
- Server mode (`owl serve`) with token-protected writes, optional private reads, OpenAPI docs and a
  small HTML page.
- Client mode with multiple named remotes, `search --all`, `pull`, `push`, `diff`.
- Divergence-safe synchronisation using content hashes and per-remote bookmarks.
- Installation from the library, remotes, git URLs and directories; `installed`, `outdated`,
  `update`, `uninstall`.
- Search by text, author, tags and topics; `authors`, `tags`, `topics`, `stats`.
- `new`, `validate`, `export`, `doctor`, `config show|get|set|path`.
- Shell completion for commands, skills, authors, tags, topics, remotes and installed skills.
- Documentation (Sphinx, Read the Docs ready), CI with a PostgreSQL service, Dockerfile.

### Changed

- `install_dir` is now an optional override; the default is the `targets` list (initially `claude`). `owl init --install-dir` became `--target`.
- `outdated`, `update`, `installed`, `uninstall` operate on all selected targets.

- The project was rewritten from a minimal SQLite scanner into a full skill manager; the previous
  `scan`/`parse` commands were replaced by `add`/`validate`.

## 0.1.0

- Initial prototype: scan directories for `SKILL.md` files into a SQLite database.
