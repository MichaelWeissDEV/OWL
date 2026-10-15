# Server configuration

All settings are environment variables with the prefix `OWL_SERVER_`. Each can also be given as
`OWL_SERVER_<NAME>_FILE` (path of a file containing the value). The configuration is validated at start;
`owl-server check-config` validates without starting.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | **required** | `postgresql://user:password@host/db` (mapped to psycopg 3). SQLite paths work for tests |
| `MODE` | `mixed` | `public`, `private` or `mixed` ({doc}`auth`) |
| `DEFAULT_REGISTRY` | `default` | slug of the registry served at `/api/v1/…` (created automatically) |
| `OPEN` | automatic | `true` = always open (no login), `false` = always secured, unset = open until secured ({doc}`identity`) |
| `ADMIN_TOKEN` | – | optional bootstrap administrator token, **at least 24 characters**; setting it secures the server |
| `LOCAL_ACCOUNTS` | `true` | password logins and user management in the dashboard |
| `AUTO_MIGRATE` | `true` | apply Alembic migrations at start |
| `MAX_BODY_MB` | `40` | request body limit (a skill may be 20 MiB; uploads are base64) |
| `SESSION_TTL_HOURS` | `12` | lifetime of login sessions |
| `LOGIN_RATE_PER_MINUTE` | `10` | attempts per minute and client for login endpoints |
| `CORS_ORIGINS` | – | comma separated origins allowed to call the API from a browser (for the dashboard) |
| `PUBLIC_URL` | – | the external URL (informational) |
| `OIDC_*` | – | OpenID Connect, see {doc}`oidc` |
| `OAUTH_*` | – | OAuth 2.0 / GitHub, see {doc}`identity` |
| `LDAP_*` | – | LDAP / Active Directory, see {doc}`identity` |
| `PROXY_*` | – | proxy authentication (Kerberos/SAML), see {doc}`identity` |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | proxies whose `X-Forwarded-*` headers are trusted (uvicorn) |

The CLI: `owl-server serve|migrate|check-config|create-admin|create-token`.

## Choosing the mode

The mode applies to a **secured** server; while the server is open everybody has full access
({doc}`identity`).

| Mode | Effect |
| --- | --- |
| `public` | every registry is public: anyone can read; writes still need rights |
| `private` | every registry is private: nothing is readable without authentication |
| `mixed` | each registry has its own visibility (default for new registries: `private`) |

The mode is enforced when registries are created or changed and when they are read, so a registry cannot
be made more open than the mode allows.
