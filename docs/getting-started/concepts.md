# Concepts

## Skill

A *skill* is a directory with a `SKILL.md` file (YAML frontmatter followed by markdown
instructions) and optionally further files such as scripts or reference documents. OWL treats the
skill as one unit: text, metadata and bundled files are stored, hashed, transferred and installed
together. See {doc}`../guide/skill-format`.

## Identity: `author/name`

Every skill is identified by `author/name`, for example `michael/release-notes`. The *name* follows
the Agent Skills convention (lower case, digits and single hyphens, at most 64 characters), the
*author* is lower case letters, digits, `.`, `_` and `-`.

A bare name (`release-notes`) is accepted wherever a reference is expected, as long as exactly one
author provides that name. Otherwise OWL reports the ambiguity and lists the candidates:

```console
$ owl show shared
error: 'shared' is ambiguous, use one of: alice/shared, bob/shared
```

## Version and content hash

`version` is a free-form string from the frontmatter (default `0.0.0`) meant for humans. OWL's own
change detection uses the **SHA-256 content hash**, computed from `SKILL.md`, the metadata (author,
name, version, description, tags, topics, extras) and all bundled files. Timestamps are *not* part of
the hash, so the same skill hashes identically in every store.

## Store

A *store* is where skills live. OWL has three implementations behind one interface:

| Store | Backend | Notes |
| --- | --- | --- |
| `SqlStore` | SQLite or PostgreSQL | via SQLAlchemy |
| `DirectoryStore` | plain files, git friendly | `skills/<name>/` |
| `RemoteStore` | an `owl serve` instance | HTTP client |

Because `RemoteStore` implements the same interface, almost every command works the same on the
local library and on a server.

## Library

The *local library* is the store configured by `owl init`. In client mode it is the cache you pull
into and the staging area you push from.

## Modes

| Mode | Meaning |
| --- | --- |
| `standalone` | Only the local library is used. |
| `server` | A label for machines that run `owl serve`; the server serves the configured store. |
| `client` | Local library plus remotes. Read commands default to the default remote. |

The mode is a convenience default stored in the config; every behaviour can still be selected per
command with `--local` and `--remote`. See {doc}`../guide/configuration`.

## Registry

A *registry* is a git repository of skills with a generated `index.json` / `INDEX.md`. It is a
read-only remote: you search and install from it; contributions arrive as pull requests, and CI keeps
the index (including each skill's last update) current. OWL's default registry is `owl`. See
{doc}`../guide/registries`.

## Target

A *target* names where a tool (Claude Code, OpenCode, Codex, Gemini CLI, Copilot, Cursor, …) looks for
skills – a global and a project directory. One install can write to several targets. See
{doc}`../guide/tools`.

## Remote

A *remote* is a named source besides the local library: an OWL server (URL plus optional token) or a
registry. Several remotes can be configured and
queried at once – they are independent servers, perhaps run by different teams.

## Sync bookmark

For each remote and skill OWL remembers the hash at the last successful `pull`/`push`. Comparing
local hash, remote hash and bookmark tells OWL whether it can fast-forward safely or whether both
sides changed (*diverged*). See {doc}`../guide/syncing`.

## Install directory and marker

Installing copies a skill to `<target dir>/<name>/` and writes `.owl-install.json` into it. The
marker lets OWL recognise its own installations: it will update or remove those, and refuse to
touch directories you created by hand unless you pass `--force`.
