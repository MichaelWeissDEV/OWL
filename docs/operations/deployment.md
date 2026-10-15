# Deployment overview

An OWL server is a single stateless process in front of a database (or a git working copy). That
makes deployment simple:

```text
clients ──HTTPS──► reverse proxy (TLS, rate limits) ──HTTP──► owl serve (127.0.0.1:8765) ──► PostgreSQL
```

## Checklist

1. **Database** – PostgreSQL for shared servers ({doc}`../guide/postgres`); SQLite is fine for a
   small private server with one process.
2. **Installation** – virtualenv or container with `owl[server,postgres]`.
3. **Secrets** – `OWL_SERVER_TOKEN` and `OWL_DB_URL` via environment / secret manager, never on the
   command line.
4. **Bind address** – keep `127.0.0.1` and publish through a reverse proxy; use `0.0.0.0` only inside
   a container or a trusted network.
5. **TLS** – terminate at the proxy ({doc}`reverse-proxy`). Tokens travel in headers: never expose
   the server over plain HTTP on untrusted networks.
6. **Process supervision** – systemd ({doc}`systemd`) or Docker restart policy ({doc}`docker`).
7. **Backups** – {doc}`backup`.
8. **Monitoring** – poll `GET /api/v1/health` (always unauthenticated) and, for functional checks,
   `GET /api/v1/info`.

## Sizing

A server answers each request with one or two SQL queries. The process is I/O bound; a single worker
serves hundreds of requests per second on small hardware. Memory use is dominated by uploads
(a skill is held in memory while being processed; the limit is 20 MiB per skill). See
{doc}`performance`.

## Single process

`owl serve` runs one uvicorn worker. For the scale OWL targets (teams, communities) this is
sufficient; if you need more throughput, run several instances behind the proxy – instances are
stateless when backed by PostgreSQL. (A git-backed server caches the directory in memory and is meant
to run as a single instance.)

## Upgrades

1. Back up the database.
2. Install the new version.
3. Restart the service. The schema is created if missing and never altered in 0.x; check the
   {doc}`../changelog` for notes about future migrations.
4. `owl remote ping` from a client to confirm the version.

Zero-downtime is possible with two instances behind the proxy and a rolling restart.
