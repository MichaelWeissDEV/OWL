# Configuration file

Location: `$OWL_HOME/config.json` (default `~/.owl/config.json`), mode `0600`.

```json
{
  "mode": "standalone",
  "author": "local",
  "store": {
    "backend": "sqlite",
    "location": "/home/me/.owl/skills.sqlite3",
    "git_url": null,
    "url_env": null
  },
  "remotes": {
    "owl": {"url": "https://github.com/MichaelWeissDEV/owl-registry.git", "kind": "registry"},
    "team": {"url": "https://skills.example.com", "kind": "server", "token_env": "OWL_TEAM_TOKEN"}
  },
  "default_remote": "team",
  "targets": ["claude"],
  "custom_targets": {},
  "install_dir": null
}
```

Keys with `null` values are omitted when OWL writes the file.

## Top level

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `mode` | string | `standalone` | `standalone`, `client` or `server` |
| `author` | string | `local` | default author for skills without one (lower-cased) |
| `store` | object | sqlite in `$OWL_HOME` | where the local library lives |
| `remotes` | object | `{}` | named servers |
| `default_remote` | string \| null | `null` | remote used by `-r`-less commands in client mode, and by `pull`/`push`/`diff` |
| `targets` | list of strings | `["claude"]` | default install targets (built-in or custom names) |
| `custom_targets` | object | `{}` | `name → {global, project, description}` |
| `install_dir` | string \| null | `null` | optional directory that replaces the targets for global installs |

## `store`

| Key | Type | Description |
| --- | --- | --- |
| `backend` | `sqlite` \| `postgres` \| `git` | storage implementation |
| `location` | string | sqlite: file path (or `sqlite:///` URL); postgres: connection URL; git: working copy directory |
| `git_url` | string \| null | git: URL of `origin` (informational; `owl init` sets the remote) |
| `url_env` | string \| null | postgres: environment variable that holds the URL; overrides `location` |

## `remotes.<name>`

| Key | Type | Description |
| --- | --- | --- |
| `url` | string | server: base URL without `/api/v1`; registry: git URL or local directory |
| `kind` | `server` \| `registry` | default `server` |
| `ref` | string \| null | registry only: branch or tag to follow |
| `token` | string \| null | bearer token stored in the file |
| `token_env` | string \| null | environment variable holding the token (wins over `token`) |

## Resolution of the default remote

`pull`, `push`, `diff` and `remote ping` pick: `--remote` → `default_remote` → the only configured
remote → error "No remote selected".

## Validation

Malformed JSON or wrong value types stop OWL with `Invalid config file …`. Unknown keys inside
`store` or a remote are rejected; unknown top-level keys are ignored.

## State file

`$OWL_HOME/state.json` (not meant for editing):

```json
{
  "synced": {"team": {"alice/pdf-forms": "9f2c…"}},
  "completion": {"refs": ["alice/pdf-forms"], "authors": ["alice"], "tags": ["pdf"], "topics": []}
}
```

`synced` holds the sync bookmarks per remote; `completion` the shell completion cache.
