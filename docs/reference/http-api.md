# HTTP API

Base path `/api/v1`. All bodies are JSON. The server also publishes an interactive description at
`/docs` (Swagger UI) and `/openapi.json`.

```{note}
This page describes the API of `owl serve` (single registry, one write token). **OWL Server** is a
superset: the same skill endpoints plus registries, versions, ETags, roles and administration - see
[the OWL Server documentation](https://owl-server.readthedocs.io/en/latest/reference/http-api.html).
```

## Authentication

Send `Authorization: Bearer <token>` where required:

| Server configuration | `GET` | `PUT` / `DELETE` |
| --- | --- | --- |
| no token | open | `403` "read-only" |
| token | open | token |
| token + `--private` | token | token |

`GET /api/v1/health` and the HTML page at `GET /` follow the same read rule except that `health` is
always open. Missing/invalid credentials: `401`.

## Endpoints

### `GET /api/v1/health`

```json
{"status": "ok"}
```

### `GET /api/v1/info`

```json
{"name": "owl", "version": "0.1.0", "skills": 120, "writable": true, "private": false}
```

### `GET /api/v1/skills`

Search; returns an array of skill **summaries**.

| Query parameter | Meaning |
| --- | --- |
| `q` | text; words are ANDed, case-insensitive substring match |
| `author` | exact author |
| `tag` | repeatable; all must be present |
| `topic` | repeatable; all must be present |
| `limit` | 1–500, default 50 |
| `offset` | default 0 |

```console
$ curl 'https://skills.example.com/api/v1/skills?q=pdf&tag=office&limit=10'
```

```json
[
  {
    "author": "alice", "name": "pdf-forms", "version": "0.3.0",
    "description": "Fill PDF forms", "tags": ["office", "pdf"], "topics": [],
    "sha256": "9f2c…", "updated_at": "2026-10-15T09:12:00+00:00"
  }
]
```

### `GET /api/v1/skills/{author}/{name}`

The full skill:

```json
{
  "author": "alice", "name": "pdf-forms", "version": "0.3.0",
  "description": "Fill PDF forms", "tags": ["pdf"], "topics": [],
  "sha256": "9f2c…", "updated_at": "…", "created_at": "…",
  "content": "---\nname: pdf-forms\n…",
  "extra": {"license": "MIT"},
  "files": {"scripts/fill.py": "<base64>"}
}
```

`404` if absent.

### `PUT /api/v1/skills/{author}/{name}` (write)

Body: the full skill object as above (`sha256`, `created_at`, `updated_at` are ignored/recomputed).
Creates or replaces. Returns the stored skill. Errors:

| Status | Reason |
| --- | --- |
| 401 | missing/invalid token |
| 403 | server has no write token (read-only) |
| 422 | malformed body, URL and body disagree on author/name, validation failed (name format, description, reserved file names, unsafe path, size > 20 MiB) |

Uploading an identical skill is a no-op and returns the existing record (timestamps unchanged).

### `DELETE /api/v1/skills/{author}/{name}` (write)

`{"deleted": true}` or `404`.

### `GET /api/v1/facets/{kind}`

`kind` is `author`, `tag` or `topic`:

```json
[{"value": "git", "count": 4}, {"value": "sql", "count": 3}]
```

Sorted by count descending, then value. Unknown kind: `404`.

### `GET /`

Small HTML page (search form + table); all values are HTML-escaped.

## Errors

Errors carry `{"detail": "…"}`. Validation errors from the OWL layer use `422`.

## Writing a client

The Python client (`owl.stores.remote.RemoteStore`) is ~100 lines and a good reference
implementation. Page through results with `limit`/`offset` (page size ≤ 500); compare `sha256` to
detect changes; treat `files` values as base64.
