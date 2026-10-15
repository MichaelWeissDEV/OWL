# OWL Server

```{admonition} Alpha
:class: warning

OWL Server is a separate project (`owl-server`, next to this repository) and is in **alpha**: the API,
database schema and configuration may still change. It is optional – the OWL CLI works fully without it.
```

OWL Server is a self-hostable registry with a **PostgreSQL** database. It stores skills completely
(every version, every file), speaks the HTTP API the OWL CLI already uses, and adds registries with
access control, immutable versions, accounts, tokens, optional OpenID Connect and an audit log.

```{mermaid}
flowchart LR
    CLI[owl CLI<br/>search · pull · push · install] -- HTTPS --> RP[reverse proxy / TLS]
    DASH[web dashboard<br/>optional, separate] -- HTTPS --> RP
    RP --> API[OWL Server API<br/>FastAPI]
    API --> PG[(PostgreSQL)]
    API -. OIDC .-> IDP[Identity provider<br/>Keycloak, ...]
```

## When to use what

| Need | Use |
| --- | --- |
| publish skills publicly, review by pull request | a **git registry** ({doc}`../guide/registries`) |
| a central, access-controlled place for a team | **OWL Server** |
| just your machine | the local library ({doc}`../guide/local-library`) |

The server and git registries combine: `owl merge SERVER --into REGISTRY` publishes (parts of) a
server to a registry, `GET …/export` downloads a server registry in git-registry layout.

## Concepts

| Concept | Meaning |
| --- | --- |
| **Registry** | a named collection of skills with its own visibility (`public`/`private`) and members. The `default` registry is created automatically |
| **Skill version** | one immutable revision, addressed by its content hash. A changed upload becomes a *new* version and the current pointer moves; pushing an old, known version again is a rollback |
| **Mode** | `public`, `private` or `mixed` – see {doc}`auth` |
| **Roles** | `reader` < `publisher` < `admin`, evaluated **per registry** |
| **Principal** | who is calling: anonymous, bootstrap admin (environment token), a user (session or API token) or a service token |

## Pointing the OWL CLI at it

```console
$ owl remote add company https://skills.example.com --token-env OWL_TOKEN        # the default registry
$ owl remote add team    https://skills.example.com/r/team --token-env OWL_TOKEN  # another registry
$ owl push --all -r team
$ owl search security -r team
$ owl install secure-review -r team -t opencode
```

The URL of a non-default registry is `<server>/r/<slug>`; the OWL CLI appends `/api/v1/…` itself. The
unchanged CLI is tested against a running server (push, pull, search, facets, diff, install, versions).

## Pages

```{toctree}
:maxdepth: 1

deployment
configuration
auth
oidc
api
```
