# Testing

```console
$ uv run pytest                     # everything that does not need PostgreSQL
$ uv run pytest -k search -v
$ uv run pytest tests/test_stores.py
```

## Layout

| File | Content |
| --- | --- |
| `tests/test_stores.py` | the **contract suite**: one set of tests run against every store |
| `tests/test_core.py` | parsing, hashing, path safety, installer, sync planning, server auth, web page |
| `tests/test_cli.py` | end-to-end CLI tests through Typer's `CliRunner` |
| `tests/test_postgres.py` | PostgreSQL specific checks |
| `tests/conftest.py` | fixtures: isolated `OWL_HOME`, sample skills, stores, in-process server |

## The contract suite

The `any_store` fixture is parametrised over `sql`, `dir`, `remote` and `postgres`:

- `remote` talks to the real FastAPI app through `fastapi.testclient.TestClient` injected into
  `RemoteStore` – no sockets.
- `postgres` is skipped unless `OWL_TEST_POSTGRES_URL` is set.

It checks round trips (content, files, extras, tags, hash), idempotent upserts, deletes, validation,
search semantics (text, author, tags, topics, case, escaping of `%`, paging, ranking), facets,
reference resolution (including ambiguity) and a cross-store chain SQL → directory → remote → SQL
that must keep the hash.

## Running PostgreSQL tests

```console
$ docker run -d --rm --name owl-pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=owl_test -p 55432:5432 postgres:16
$ OWL_TEST_POSTGRES_URL=postgresql://postgres:pw@localhost:55432/owl_test uv run pytest
$ docker stop owl-pg
```

The fixture empties OWL's tables before each test, so use a dedicated database.

## Isolation

`conftest.py` has an autouse fixture setting `OWL_HOME` to a temporary directory. CLI tests that
install skills always pass `--dir` pointing into `tmp_path`. Never write tests that use the default
install directory.

## Writing a test for a new command

```python
def test_my_command(lib, tmp_path):  # `lib` = initialised OWL with two skills
    result = owl("my-command", "--json")  # asserts exit code 0 unless ok=False
    assert json.loads(result.stdout)[0]["name"] == "git-helper"
```

## Manual smoke test of server and client

```console
$ export OWL_HOME=$(mktemp -d)
$ OWL_SERVER_TOKEN=tok owl serve --port 18701 --db-url $OWL_HOME/s.sqlite3 &
$ owl init --mode client && owl remote add a http://127.0.0.1:18701 --token tok
$ owl add demo && owl push --all -r a && owl search commit -r a
$ kill %1
```
