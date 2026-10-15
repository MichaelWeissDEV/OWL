# Architecture

## Layers

```{mermaid}
flowchart TD
    CLI[cli.py / cli_tools.py<br/>Typer commands] --> ST
    SRV[server.py<br/>FastAPI app] --> ST
    CLI --> INS[installer.py]
    CLI --> SRC[sources.py<br/>git URL / directory loader]
    CLI --> SYN[sync.py<br/>pull/push planning]
    SRC --> PAR[parsing.py]
    ST{{SkillStore interface<br/>stores/base.py}}
    ST --> SQL[SqlStore<br/>SQLite / PostgreSQL]
    ST --> DIR[DirectoryStore<br/>files + git]
    ST --> REM[RemoteStore<br/>httpx -> server]
    REM -. HTTP .-> SRV
    PAR --> MOD[models.py<br/>Skill, hash, validation]
    SQL --> MOD
    DIR --> MOD
    DIR --> PAR
```

## Modules

| Module | Responsibility |
| --- | --- |
| `models.py` | `Skill`, `SkillSummary`, `SearchQuery`, hashing, validation, error types |
| `fsutil.py` | untrusted-path handling: `safe_relpath`, tree reading/writing, atomic directory replace |
| `parsing.py` | frontmatter, `skill.json` overlay, directory loading, skill discovery |
| `stores/base.py` | the `SkillStore` ABC, reference resolution, paging helpers |
| `stores/sql.py` | SQLAlchemy Core implementation, URL normalisation, `pg_trgm` setup |
| `stores/directory.py` | `skills/<author>/<name>` layout with an in-memory cache |
| `stores/remote.py` | HTTP client implementing the same interface |
| `stores/__init__.py` | `open_store` / `open_remote` factories |
| `server.py` | FastAPI application factory |
| `installer.py` | install/uninstall/list with markers |
| `sync.py` | pure decision functions for pull/push |
| `sources.py` | load skills from git URLs or directories |
| `gitutil.py` | thin `git` CLI wrapper |
| `config.py`, `paths.py` | configuration, state, bookmarks, completion cache |
| `completion.py` | shell completion callbacks |
| `cli.py`, `cli_tools.py` | the command line |

## Design decisions

**One interface, three stores.** Every feature (`search`, `show`, `install`, `pull`, …) is written
against `SkillStore`. A client talking to a server and a local SQLite file are interchangeable.

**Content hashing instead of timestamps.** Change detection and sync decisions use a SHA-256 over
content, metadata and files – never timestamps or version strings – so identical skills compare
equal everywhere (this is what makes round-trips and safe sync possible).

**SQLAlchemy Core.** Simple tables, explicit queries, identical behaviour on SQLite and PostgreSQL.

**Store the original `SKILL.md`.** The text is kept verbatim; metadata is *derived* from it plus the
optional `skill.json`. No information in frontmatter is ever lost.

**Pure planning functions.** `sync.plan_pull/plan_push` take three hashes and return an action; the
CLI performs the I/O. This keeps the conflict logic exhaustively unit-testable.

**Untrusted input everywhere.** Paths are validated at every boundary (disk read, HTTP upload, disk
write); symlinks are never followed.

**Best-effort side channels.** Completion cache, trigram indexes and the completion callbacks swallow
errors on purpose: they must never break the main function.

**Lazy imports.** FastAPI, uvicorn, the PostgreSQL driver and git are imported only when needed so
`owl <TAB>` and simple commands start fast, and missing extras produce an instructive message.

**State separate from config.** `config.json` is edited by humans; `state.json` is machine-managed.

## Request flow: `owl push alice/x -r team`

1. `cli._transfer` loads the config, opens the local store and a `RemoteStore`.
2. `source.resolve(ref)` → `(author, name)`.
3. Both stores `get` the skill; hashes plus the bookmark go into `sync.plan_push`.
4. On `copy`: `remote.upsert(local_skill)` → `PUT /api/v1/skills/alice/x` → server validates →
   `store.upsert` (transaction) → response.
5. The bookmark is updated; the result is printed; exit status reflects conflicts.

## Threading

The FastAPI app runs sync endpoints in a thread pool. `SqlStore` relies on SQLAlchemy's pooling;
`DirectoryStore` guards its cache and writes with a re-entrant lock.
