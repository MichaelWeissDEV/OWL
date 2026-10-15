# Data model

## Skill

| Field | Type | Notes |
| --- | --- | --- |
| `author` | string | lower-case; part of the identity |
| `name` | string | part of the identity; `[a-z0-9]+(-[a-z0-9]+)*`, ≤ 64 chars |
| `version` | string | default `0.0.0`; informational |
| `description` | string | required |
| `tags`, `topics` | list of strings | lower-cased, unique, sorted |
| `content` | string | complete `SKILL.md` text including frontmatter, stored verbatim |
| `extra` | object | additional `skill.json` keys |
| `files` | map path → bytes | bundled files, validated relative POSIX paths |
| `created_at`, `updated_at` | ISO-8601 string | maintained by the store; **not hashed** |
| `sha256` | string | derived, see below |

## Content hash

```text
sha256(
  "meta\0"  + canonical_json({author,name,version,description,tags,topics, **extra})
  "\0skill\0" + content
  for each file sorted by path:
      "\0file\0" + path + "\0" + hex(sha256(file bytes))
)
```

Canonical JSON: sorted keys, separators `(",", ":")`, UTF-8, non-ASCII kept. Because timestamps are
excluded and tags/topics are normalised, a skill hashes identically after any round trip through
SQLite, PostgreSQL, the directory store or the HTTP API – this is covered by the test suite.

## Skill summary

Same fields without `content`, `extra`, `files`, `created_at` – used by listings. Remote results
additionally carry a `source` label (store or remote name) in the CLI.

## Search query

| Field | Meaning |
| --- | --- |
| `text` | words ANDed, substring, case-insensitive over name/description/author/content/tags/topics |
| `author` | exact, case-insensitive |
| `tags`, `topics` | all must be present |
| `limit`, `offset` | paging |

## Installed marker

`<target dir>/<name>/.owl-install.json`: `ref`, `version`, `sha256`, `source`.

## Limits

| Limit | Value |
| --- | --- |
| skill name | 64 characters |
| total skill size (content + files) | 20 MiB |
| page size for `GET /skills` | 500 |
