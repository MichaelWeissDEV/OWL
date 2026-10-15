# Configuration

OWL's configuration is a JSON file at `$OWL_HOME/config.json` (default `~/.owl/config.json`),
created by `owl init`, written with mode `0600`. If it does not exist, defaults apply: standalone
mode, SQLite database `$OWL_HOME/skills.sqlite3`.

```json
{
  "mode": "client",
  "author": "michael",
  "store": {
    "backend": "sqlite",
    "location": "/home/michael/.owl/skills.sqlite3"
  },
  "remotes": {
    "owl":    { "url": "https://github.com/MichaelWeissDEV/owl-registry.git", "kind": "registry" },
    "team":   { "url": "https://skills.example.com", "token_env": "OWL_TEAM_TOKEN" },
    "public": { "url": "https://owl.example.org" }
  },
  "default_remote": "team",
  "targets": ["claude", "opencode"],
  "custom_targets": {}
}
```

The complete field list is in {doc}`../reference/config-file`.

## How to change it

| What | Command |
| --- | --- |
| mode, author, targets, install dir, default remote | `owl config set KEY VALUE` |
| store backend and location | `owl init --backend … --location …` |
| remotes | `owl remote add/remove` |
| anything else | edit the JSON (it is validated on load) |

## Secrets

Do not put secrets into the config if you can avoid it:

| Secret | Safer alternative |
| --- | --- |
| remote write token | `owl remote add NAME URL --token-env VAR` |
| PostgreSQL password | `owl init --backend postgres --url-env VAR` |
| server token | `OWL_SERVER_TOKEN` environment variable |
| server database URL | `OWL_DB_URL` environment variable |

If a secret is stored, the file is `0600` and `owl config show` masks tokens (`***`). Database URLs
containing a password are shown as stored – prefer `--url-env`.

## Environment variables

| Variable | Used by | Meaning |
| --- | --- | --- |
| `OWL_HOME` | all | directory for config, state and default data (default `~/.owl`) |
| `OWL_DEFAULT_REGISTRY` | first config creation | URL of the registry added as `owl` on a fresh install; set to an empty string for none |
| `OWL_DB_URL` | `owl serve` | database to serve |
| `OWL_SERVER_TOKEN` | `owl serve` | write token |
| *(any name)* | remotes / store | referenced by `token_env` / `url_env` |
| `OWL_TEST_POSTGRES_URL` | tests | enables the PostgreSQL test suite |

## Multiple profiles

`OWL_HOME` doubles as a profile switch:

```console
$ OWL_HOME=~/.owl-work owl init --mode client
$ alias owl-work='OWL_HOME=~/.owl-work owl'
```
