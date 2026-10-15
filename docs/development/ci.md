# Continuous integration

Workflows live in `.github/workflows/`.

## `ci.yml`

Runs on pushes to `main`/`master` and on pull requests; cancels superseded runs.

| Job | What it does |
| --- | --- |
| `lint` | `uv sync --locked --all-extras`, `ruff check`, `ruff format --check`, `mypy src` |
| `test` | `pytest` on `ubuntu-latest` and `macos-latest` |
| `postgres` | starts a `postgres:16` service container and runs the whole suite with `OWL_TEST_POSTGRES_URL` set |
| `docs` | builds this documentation with warnings as errors |
| `build` | `uv build` (needs lint + test + docs green) and uploads `dist/` |

`--locked` makes CI fail if `uv.lock` is out of date with `pyproject.toml` – run `uv lock` and commit
the result when you change dependencies.

## `release.yml`

Triggered by tags `v*`: runs the tests, builds the sdist/wheel and attaches them to a GitHub release
with generated notes. See {doc}`release`.

## Read the Docs

`.readthedocs.yaml` builds the documentation on every push with `fail_on_warning: true`; pull
requests get preview builds when enabled in the Read the Docs project settings.

## Running CI locally

```console
$ uv sync --locked --all-extras --group docs
$ uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
$ uv run sphinx-build -W --keep-going -b html docs docs/_build/html
```
