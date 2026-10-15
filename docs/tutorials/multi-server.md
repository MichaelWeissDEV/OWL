# Several servers side by side

**Result:** a client that sees a public catalogue, the company server and a private personal server at
once.

```text
                    ┌── public.example.org   (read-only, community skills)
 owl client ────────┼── skills.corp.example  (team, PostgreSQL, write token)
                    └── localhost:8765       (personal, SQLite)
```

## Servers

Each server is independent – its own database, token and audience:

```console
# public mirror, read-only (no token configured)
$ owl serve --db-url /srv/public.sqlite3 --host 0.0.0.0 --port 8001

# team server, PostgreSQL, write token
$ OWL_DB_URL=postgresql://… OWL_SERVER_TOKEN=… owl serve --port 8002

# personal
$ owl serve --db-url ~/personal.sqlite3 --token dev
```

## Client

```console
$ owl init --mode client --author me
$ owl remote add public   https://public.example.org
$ owl remote add corp     https://skills.corp.example --token-env OWL_CORP_TOKEN
$ owl remote add personal http://localhost:8765 --token dev
$ owl config set default_remote corp
```

## Use them together

```console
$ owl search kubernetes --all              # local + public + corp + personal, labelled by source
$ owl search kubernetes -r public -r corp
$ owl install acme/k8s-debug -r public     # install straight from one
$ owl pull acme/k8s-debug -r public        # copy into the library
$ owl push me/k8s-debug -r corp            # promote to the team
$ owl push me/k8s-debug -r personal
```

## Promote between servers

There is no direct server-to-server transfer; the library is the hop:

```console
$ owl pull acme/k8s-debug -r public
$ owl push acme/k8s-debug -r corp
```

Bookmarks are kept **per remote**, so each server's divergence is tracked separately.

## Resilience

`search --all` warns about unreachable servers and continues with the rest, so one outage does not
break discovery.
