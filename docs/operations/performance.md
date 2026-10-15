# Performance

## Where time goes

| Operation | Cost |
| --- | --- |
| `search` on SQLite/PostgreSQL | one SQL query + one for labels of the returned page; substring search scans rows unless `pg_trgm` indexes apply |
| `list` | pages of 500 |
| `pull --all` / `push --all` | per skill: one `get` on each side (hash comparison happens on the full objects), so cost grows with library size and skill size |
| git backend | the whole directory is loaded into memory per process start |
| CLI start-up | ~100–200 ms, dominated by imports (SQLAlchemy, Typer); server-only modules are imported lazily |

## Tips

- PostgreSQL: let OWL create the `pg_trgm` indexes (or create the extension as superuser). Run
  `ANALYZE skills;` after bulk imports.
- Limit result sizes with `--limit`; the server caps pages at 500.
- For very large libraries prefer the database backend over git; git is excellent for history,
  not for substring search over thousands of skills.
- Keep skills small. Large binary assets are better referenced than bundled; the hard limit is 20 MiB.
- Put the proxy's gzip on for JSON responses.

## Known scaling limits

- `pull --all` fetches complete skills even when unchanged (there is no hash-only endpoint yet; see
  {doc}`../roadmap`).
- Text search is substring based, not ranked full-text.
