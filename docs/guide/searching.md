# Searching

```console
$ owl search [QUERY] [-a AUTHOR] [-t TAG]... [-T TOPIC]... [-r REMOTE]... [--local] [--all] [--limit N] [--json]
```

## Semantics

- `QUERY` is split into words. **Every word must match** (logical AND), case-insensitively, as a
  substring of at least one of: name, description, author, `SKILL.md` text, any tag or topic.
- `--author/-a NAME` – exact match (case-insensitive).
- `--tag/-t TAG` – the skill must have the tag; repeat for several (all must match).
- `--topic/-T TOPIC` – same for topics.
- Filters combine with AND.
- `%` and `_` in the query are plain characters, not wildcards.
- No query and no filter lists everything (same as `owl list`).

## Ordering

1. skills whose **name** contains the first query word,
2. skills whose **description** contains it,
3. everything else,

then alphabetically by author and name. Without a query: by author and name.

## Examples

```console
$ owl search "commit message"                 # both words, anywhere
$ owl search -a alice                         # everything by alice
$ owl search -t git -t review                 # tagged git AND review
$ owl search sql -T databases -a bob          # text + topic + author
$ owl search pdf --all --limit 5              # top 5 per store, local + all remotes
$ owl search pdf -r team -r public            # two specific remotes
$ owl search "" -t docs --json | jq -r '.[].name'
```

## Listing facets

```console
$ owl authors              # author<TAB>count
$ owl tags -r team
$ owl topics --json
```

Facets honour `--local`, `-r` and the client-mode default like any read command; with several
remotes the counts are summed.

## Output

Human output is a table (`Source` column appears when several stores are queried). `--json` prints
an array of objects:

```json
[
  {
    "author": "alice", "name": "pdf-forms", "version": "0.3.0",
    "description": "Fill PDF forms", "tags": ["pdf"], "topics": ["office"],
    "sha256": "…", "updated_at": "2026-10-15T09:12:00+00:00", "source": "team"
  }
]
```

## How it is implemented

| Store | Strategy |
| --- | --- |
| SQLite / PostgreSQL | one SQL query with `lower(col) LIKE '%word%' ESCAPE` per word and column, `EXISTS` sub-queries for labels, `ORDER BY` relevance bucket; PostgreSQL gets `pg_trgm` GIN indexes |
| directory (git) | in-memory scan of the loaded skills with identical semantics |
| remote | the same query sent to `GET /api/v1/skills`, paged at 500 |

A shared contract test suite runs the same search expectations against every implementation, so
results are consistent across backends.
