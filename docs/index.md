# OWL

**OWL is a skill manager.** It stores *skills* – a `SKILL.md` with YAML frontmatter plus optional
bundled files, as used by Claude Code and other agent frameworks – in a SQLite database, a
PostgreSQL database or a plain git repository. It lets you search them by text, author, tag and
topic, install them into an agent's skills directory, and synchronise them between machines
through one or more **OWL servers**.

```{mermaid}
flowchart LR
    subgraph Standalone
      A[owl CLI] --> B[(SQLite)]
      A --> C[git working copy]
    end
    subgraph Server mode
      S[owl serve] --> P[(PostgreSQL)]
      S2[owl serve] --> L[(SQLite)]
    end
    subgraph Client mode
      K[owl CLI + local library] -- HTTP --> S
      K -- HTTP --> S2
    end
    C -- git push/pull --> R[(git remote)]
```

::::{grid} 1 2 2 3
:gutter: 3

:::{grid-item-card} Getting started
:link: getting-started/index
:link-type: doc
Install OWL, create your first library and install a skill in five minutes.
:::

:::{grid-item-card} User guide
:link: guide/index
:link-type: doc
Every feature explained: formats, backends, server, client, search, sync, completion.
:::

:::{grid-item-card} Tutorials
:link: tutorials/index
:link-type: doc
Step-by-step recipes: team server, git-based library, multi-server setups, CI publishing.
:::

:::{grid-item-card} Reference
:link: reference/index
:link-type: doc
CLI, HTTP API, configuration file, data model, database schema, Python API.
:::

:::{grid-item-card} Operations
:link: operations/index
:link-type: doc
Deploy behind TLS, run in Docker or systemd, back up, secure and troubleshoot.
:::

:::{grid-item-card} Development
:link: development/index
:link-type: doc
Architecture, testing, CI, releasing and how to add a storage backend.
:::
::::

## Feature overview

- **Three modes** – *standalone* (local library), *server* (HTTP API in front of a database or git
  repository) and *client* (local library plus any number of servers).
- **Registries** – git repositories with a generated index; the default registry `owl` is built in, and
  `owl registry init` creates your own with CI that keeps the index (and last-update times) current.
- **Native tool support** – install for Claude Code, OpenCode, Codex CLI, Gemini CLI, GitHub Copilot and
  Cursor, globally or per project, one skill or a whole registry.
- **Three storage backends** – SQLite, PostgreSQL and a git/plain-file layout (`SKILL.md` +
  `skill.json`).
- **Search** by free text, author, tags and topics – locally, on one server, or across all of them
  with results labelled by source.
- **Install** from the library, from any git repository (one skill, several, or all) or from a
  directory; update and uninstall; project-local or global.
- **Safe synchronisation** – content hashes and a per-remote bookmark detect when a skill changed on
  both sides; nothing is overwritten silently.
- **Shell completion** for bash, zsh, fish and PowerShell, including skill names, authors, tags,
  topics and remote names.
- **Tooling** – `validate`, `new`, `diff`, `outdated`/`update`, `export`, `stats`, `doctor`, JSON
  output for scripting.
- **Production minded** – token auth, read-only default, `pg_trgm` indexes, Docker image, CI with a
  PostgreSQL service container.

```{toctree}
:maxdepth: 2
:caption: Documentation
:hidden:

getting-started/index
guide/index
tutorials/index
reference/index
operations/index
development/index
faq
changelog
roadmap
```
