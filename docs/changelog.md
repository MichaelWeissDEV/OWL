# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/); versions follow
[Semantic Versioning](https://semver.org/) from 1.0.

## Unreleased

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
