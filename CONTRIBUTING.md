# Contributing to OWL

Thanks for helping! OWL is **alpha** software; contributions of all kinds are welcome:

- bug reports and feature requests (use the issue templates),
- new or improved **registries**, skill formats and adapters,
- tests, documentation and examples,
- fixes and features via pull requests.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems:
[`SECURITY.md`](SECURITY.md), not a public issue.

## Set up

Requirements: Python 3.13+, [uv](https://docs.astral.sh/uv/), git. (PostgreSQL only for the
PostgreSQL tests.)

```bash
git clone https://github.com/MichaelWeissDEV/OWL.git && cd OWL
uv sync --all-extras --group docs
```

## Quality gates

Exactly what CI runs - all must pass before a pull request is merged:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
uv run sphinx-build -W --keep-going -b html docs docs/_build/html
uv build
```

Auto-fix: `uv run ruff format .` and `uv run ruff check --fix .`.

### PostgreSQL tests

They run when `OWL_TEST_POSTGRES_URL` points at a *dedicated, disposable* database:

```bash
docker run -d --rm --name owl-pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=owl_test -p 55432:5432 postgres:16
OWL_TEST_POSTGRES_URL=postgresql://postgres:pw@localhost:55432/owl_test uv run pytest
```

CI always runs them in a service container.

## Conventions

- Type hints in `src/`; docstrings on public functions and classes.
- Expected failures raise `OwlError` (shown without a traceback). Data goes to stdout, decoration and
  warnings to stderr; listings get `--json`.
- **Data safety first:** anything that writes user files must stage, back up and be able to roll
  back; never delete before the replacement exists. Skill content is untrusted input: validate paths
  (`fsutil.safe_relpath`), never follow symlinks, never execute it.
- Tests never touch the real `~/.owl` or `~/.claude`; the autouse `owl_home` fixture isolates
  `OWL_HOME`, and install tests pass `--dir` into `tmp_path`.
- New store backends must pass the shared contract suite (`tests/test_stores.py`).
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/).

## Proposing a feature

1. Open a *feature request* issue describing the use case (not just the solution).
2. For larger changes agree on the approach before writing much code.
3. Include tests and documentation (`docs/`) in the pull request; update the changelog.
4. Keep pull requests focused - one logical change each.

## Pull requests

Fill in the pull request template, make sure the quality gates pass, and describe how you tested the
change. Maintainers may ask for changes; please be patient, this is a small project.

## Project layout

```text
src/owl/     the package (models, stores, registry, installer, CLI, server)
tests/       pytest suite
docs/        Sphinx documentation (Read the Docs)
assets/      logo and icon variants
.github/     CI, release workflow, issue and PR templates
```

More: [Developer documentation](https://owl-skills.readthedocs.io/en/latest/development/index.html).
