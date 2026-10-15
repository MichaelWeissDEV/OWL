## What and why

<!-- What does this change, and why? Link related issues. -->

## How I tested it

<!-- Commands you ran; new tests you added. -->

## Checklist

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy src`
- [ ] `uv run pytest` (and the PostgreSQL tests if stores/migrations changed)
- [ ] Docs updated (`docs/`) and changelog entry added
- [ ] No data-loss paths: writes stage, back up and can roll back
- [ ] Untrusted input (paths, symlinks, sizes) validated where relevant
