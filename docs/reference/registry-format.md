# Registry format

Version `1` of the registry layout.

## Repository layout

```text
registry.json
index.json            generated
INDEX.md              generated
README.md
skills/
  <author>/
    <name>/
      SKILL.md
      skill.json
      ...
.github/workflows/registry.yml
```

Only `skills/` matters to clients. Any layout below `skills/` is accepted when reading, but
`owl registry publish` writes `skills/<author>/<name>/`.

## `registry.json`

```json
{"format": 1, "name": "owl-registry", "description": "The default OWL skill registry"}
```

## `index.json`

```json
{
  "format": 1,
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
      "sha256": "48c1…",
      "path": "skills/michaelweissdev/conventional-commits",
      "files": 2,
      "updated_at": "2026-10-15T11:49:37+00:00"
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `format` | index format version (currently 1) |
| `generated_at` | newest `updated_at` among the skills (empty when there are none) – deterministic, not "now" |
| `count` | number of skills |
| `skills[].ref` | `author/name` |
| `skills[].sha256` | OWL content hash ({doc}`data-model`), used for change detection and verification |
| `skills[].path` | skill directory relative to the repository root (POSIX) |
| `skills[].files` | number of files in the skill including `SKILL.md` and `skill.json` |
| `skills[].updated_at` | UTC ISO-8601 time of the last change, see below |

Entries are sorted by `ref`. Duplicate refs make generation fail.

### How `updated_at` is determined

1. If the previous `index.json` has the same `ref` **and the same `sha256`**, its value is kept.
2. Otherwise the commit time of the last commit touching the skill directory, if the directory is
   committed and unmodified.
3. Otherwise the current time (an uncommitted change).

Together this makes the index stable: regenerating without changes yields byte-identical files.

## `INDEX.md`

A table of all skills (linked to their `SKILL.md`, with version, shortened description, tags and last
update date) followed by listings per topic and per tag. It is written for fast reading by humans
and language models; machines should use `index.json`.

## Reading a registry

1. Clone (or fetch) the repository.
2. Read `index.json`; search it.
3. For a chosen skill read the directory at `path` – verify `sha256` if you need integrity.

Paths in the index are treated as untrusted by OWL: they must stay inside the repository and contain
a `SKILL.md`.
