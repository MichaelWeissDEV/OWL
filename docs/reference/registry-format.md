# Registry format

Version `2` of the registry layout and index (clients also read version `1`).

## Repository layout

```text
registry.json
index.json            generated
stats.json            generated
INDEX.md              generated
STATS.md              generated
README.md
CONTRIBUTING.md
assets/owl.png
skills/
  <name>/             flat: the directory name equals the skill name
    SKILL.md
    skill.json
    ...
.github/workflows/registry.yml
```

The author is **metadata** (`author` in `skill.json` or the frontmatter), not a directory. The
logical reference of a skill is still `author/name`; the physical path is `skills/<name>`. Names are
unique per registry. Version 1 registries used `skills/<author>/<name>/`; OWL reads them and
converts them with `owl registry migrate`.

## `registry.json`

```json
{"format": 2, "name": "owl-registry", "description": "The default OWL skill registry"}
```

## `index.json`

```json
{
  "format": 2,
  "name": "owl-registry",
  "description": "…",
  "generated_at": "2026-10-15T11:49:37+00:00",
  "count": 1,
  "skills": [
    {
      "ref": "michaelweissdev/conventional-commits",
      "author": "michaelweissdev",
      "name": "conventional-commits",
      "version": "1.0.0",
      "description": "…",
      "tags": ["commits", "git"],
      "topics": ["devtools"],
      "license": null,
      "compatibility": "Works with Claude Code …",
      "sha256": "f43b…",
      "path": "skills/conventional-commits",
      "files": 1,
      "size": 19597,
      "updated_at": "2026-10-15T11:49:37+00:00",
      "revision": "5339aa4…"
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `format` | index format version (2) |
| `generated_at` | newest `updated_at` among the skills (empty when there are none) – deterministic, not "now" |
| `count` | number of skills |
| `skills[].ref` | `author/name` – the logical identity |
| `skills[].sha256` | OWL content hash ({doc}`data-model`) for change detection and verification. It detects changes; it is **not** a signature |
| `skills[].path` | skill directory relative to the repository root (POSIX), `skills/<name>` |
| `skills[].license`, `compatibility` | from `skill.json` or the frontmatter, `null` when absent |
| `skills[].files` | number of files including `SKILL.md` and `skill.json` |
| `skills[].size` | total bytes of content and bundled files |
| `skills[].updated_at` | UTC ISO-8601 time of the last change |
| `skills[].revision` | git commit that last changed the skill directory, `null` if not committed yet |

Entries are sorted by `ref`. Duplicates make generation fail.

### How `updated_at` and `revision` are determined

1. If the previous index has the same `ref` and `sha256` **and** a revision, both are kept.
2. Otherwise the last commit touching the skill directory (time and SHA), if the directory is
   committed and unmodified.
3. Otherwise – an uncommitted change – the current time and no revision.

Regenerating without changes yields byte-identical files.

## `stats.json`

```json
{
  "format": 2,
  "registry": "owl-registry",
  "generated_at": "…",
  "totals": {"skills": 1, "files": 1, "size_bytes": 19597, "invalid_entries": 0},
  "by_author": {"michaelweissdev": 1},
  "by_tag": {"git": 1},
  "by_topic": {"devtools": 1},
  "by_compatibility": {"Works with Claude Code …": 1},
  "by_license": {}
}
```

Only data derivable from the registry is reported. There are no download or install counts – those
would need real telemetry, which OWL does not collect. `invalid_entries` is always `0` in a written
file: an index is only produced when every skill validates.

## `INDEX.md` and `STATS.md`

Readable tables of the same data (linked skills, listings by topic and tag; statistic tables).

## Validation rules (`owl registry check`)

- `registry.json` present; `skills/` exists; no symlinks below `skills/`.
- Skills are direct children of `skills/` and the directory name equals `name`.
- Valid frontmatter, `name` format, `description` 1–1024 characters, valid `skill.json`.
- No duplicate names or refs; no file over 5 MiB; no skill over 20 MiB.
- `index.json`, if present, is well-formed and its paths exist (`--fresh`: also up to date).
- Warnings: no author declared.

## Reading a registry

1. Clone (or fetch) the repository.
2. Read `index.json`; search it.
3. For a chosen skill read the directory at `path` – verify `sha256` if you need integrity.

Paths in the index are untrusted: OWL requires them to stay inside the repository and to contain a
`SKILL.md`.
