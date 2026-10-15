# Environment variables

| Variable | Read by | Description |
| --- | --- | --- |
| `OWL_HOME` | every command | base directory (default `~/.owl`) |
| `OWL_DEFAULT_REGISTRY` | first config creation | registry URL added as `owl` on fresh installs (empty = none) |
| `OWL_DB_URL` | `owl serve` | database to serve (`--db-url`) |
| `OWL_SERVER_TOKEN` | `owl serve` | write token (`--token`) |
| *`token_env` of a remote* | remote access | bearer token for that remote |
| *`url_env` of the store* | postgres store | database URL |
| `OWL_TEST_POSTGRES_URL` | test suite | PostgreSQL URL for the integration tests |
| `GIT_TERMINAL_PROMPT` | set to `0` by OWL for its git calls | prevents credential prompts |
| `_OWL_COMPLETE` | shell integration | used internally by Click/Typer to drive completion |

Standard variables honoured by dependencies: `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY`/`SSL_CERT_FILE`
(httpx), `PGSSLMODE`/`PGSSLROOTCERT` etc. (libpq), the usual git variables (`GIT_SSH_COMMAND`, …).
