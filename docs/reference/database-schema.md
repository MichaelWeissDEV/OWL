# Database schema

Created automatically on first use (SQLAlchemy `create_all`), identical for SQLite and PostgreSQL.

## `skills`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `author` | varchar(128) | |
| `name` | varchar(64) | **unique together with `author`** |
| `version` | varchar(64) | |
| `description` | text | |
| `content` | text | complete `SKILL.md` |
| `extra_json` | text | JSON object, sorted keys |
| `sha256` | varchar(64) | content hash |
| `created_at`, `updated_at` | varchar(40) | ISO-8601 UTC |

Index `ix_skills_name (name)`. PostgreSQL additionally: `pg_trgm` GIN indexes
`ix_skills_name_trgm`, `ix_skills_description_trgm`, `ix_skills_content_trgm` on `lower(column)`.

## `skill_labels`

| Column | Type |
| --- | --- |
| `skill_id` | integer FK → `skills.id` |
| `kind` | varchar(8): `tag` or `topic` |
| `value` | varchar(128) |

Primary key `(skill_id, kind, value)`, index `ix_skill_labels_value (kind, value)`.

## `skill_files`

| Column | Type |
| --- | --- |
| `skill_id` | integer FK → `skills.id` |
| `path` | varchar(512) |
| `data` | bytea / blob |

Primary key `(skill_id, path)`.

## Migrations

Applied versions are stored per scope in `owl_migrations(scope, version, name, applied_at)`.

| Scope | Version | Changes |
| --- | --- | --- |
| `catalog` | 1 | the three tables above |
| `catalog` | 2 | `skill_revisions` |
| `local` | 1 | the personal tables below |

### `skill_revisions` (catalog v2)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `author`, `name` | varchar | the skill |
| `sha256` | varchar(64) | a content hash the skill has had; unique with author and name |
| `version` | varchar(64) | the version at that time |
| `recorded_at` | varchar(40) | ISO-8601 UTC |

Deleting a skill keeps its revision history.

### Local database (`$OWL_HOME/local.sqlite3`, scope `local`)

| Table | Purpose |
| --- | --- |
| `favorites(ref, added_at)` | favorites |
| `collections(id, name, description, created_at)`, `collection_skills(collection_id, ref, added_at)` | user collections |
| `notes(ref, text, updated_at)` | private notes |
| `metadata_overrides(ref, key, value)` | local-only metadata |
| `sources(name, kind, location, added_at)` | extra scan sources |
| `trusted_sources(source, note, added_at)` | your trust labels |
| `installations(id, ref, name, target, directory, scope, project_root, version, sha256, source, registry, revision, installed_at)` | install inventory (unique per directory) |
| `operation_history(id, at, operation, ref, status, detail)` | log of installs, updates, imports, syncs |
| `sync_state(remote, ref, sha256, updated_at)` | pull/push bookmarks (moved here from `state.json` once) |
| `drafts(id, name, origin, content, problems_json, created_at)` | incomplete imports and invalid edits |
| `local_meta(key, value)` | internal flags |

## Behaviour

- `upsert` runs in one transaction: unchanged hash → nothing written; otherwise the row is updated
  and its labels and files are replaced.
- `delete` removes labels, files and the skill in one transaction (no cascades required).
- There are no migrations yet; the schema is only created when missing.

## Useful queries

```sql
SELECT author, count(*) FROM skills GROUP BY author ORDER BY 2 DESC;
SELECT value, count(*) FROM skill_labels WHERE kind = 'tag' GROUP BY value ORDER BY 2 DESC;
SELECT author, name, pg_column_size(content) FROM skills ORDER BY 3 DESC LIMIT 10;   -- PostgreSQL
```
