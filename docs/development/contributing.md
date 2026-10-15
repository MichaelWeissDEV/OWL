# Contributing

## Set up

```console
$ git clone https://github.com/MichaelWeissDEV/OWL.git && cd OWL
$ uv sync --all-extras --group docs
$ uv run pytest
```

Python 3.13 is required (`uv` fetches it automatically).

## Quality gates

These are exactly the commands CI runs:

```console
$ uv run ruff check .
$ uv run ruff format --check .
$ uv run mypy src
$ uv run pytest
```

Format with `uv run ruff format .` and auto-fix lint with `uv run ruff check --fix .`.

## Conventions

- Type hints everywhere in `src/`; `from __future__ import annotations` at the top of modules.
- Public functions and classes have docstrings (Google style; rendered into the Python API reference).
- User-facing failures raise `OwlError` (or a subclass) – the CLI prints them without a traceback.
- CLI output: data to stdout, decoration and warnings to stderr; add `--json` to new listing commands.
- Anything that touches paths from skills, git or HTTP must go through `fsutil.safe_relpath`.
- Tests must never touch the real `~/.owl` or `~/.claude`: the `owl_home` fixture sets `OWL_HOME` to a
  temporary directory automatically.
- Commit messages: [Conventional Commits](https://www.conventionalcommits.org/).

## Pull requests

1. Open an issue for larger features first.
2. Add tests (a new store feature needs a contract test in `tests/test_stores.py`).
3. Update the docs (`docs/`) and the changelog.
4. Make sure the quality gates pass.

## Project layout

```text
src/owl/        the package
tests/          pytest suite
docs/           this documentation (Sphinx + MyST)
demo/           sample skill used in examples
.github/        CI and release workflows
```
