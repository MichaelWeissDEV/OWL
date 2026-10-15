# A team server with PostgreSQL

**Result:** a shared skill server for your team with write protection, plus clients.

## 1. Database

```sql
CREATE ROLE owl LOGIN PASSWORD 'change-me';
CREATE DATABASE owl OWNER owl;
```

(Optionally as superuser: `\c owl` then `CREATE EXTENSION pg_trgm;` for fast search.)

## 2. Server host

```console
$ python3.13 -m venv /opt/owl && /opt/owl/bin/pip install "/src/OWL[server,postgres]"
$ export OWL_DB_URL='postgresql://owl:change-me@127.0.0.1/owl'
$ export OWL_SERVER_TOKEN="$(openssl rand -hex 32)"
$ /opt/owl/bin/owl serve --host 127.0.0.1 --port 8765
```

Put nginx/Caddy with TLS in front ({doc}`../operations/reverse-proxy`) and run it under systemd
({doc}`../operations/systemd`) or Docker ({doc}`../operations/docker`).

## 3. Seed it from an existing repository

On any machine with the skills:

```console
$ owl init --mode client --author team
$ owl remote add team https://skills.example.com --token-env OWL_TEAM_TOKEN
$ export OWL_TEAM_TOKEN=…            # the server's token
$ owl add https://github.com/acme/skills.git
$ owl push --all -r team
```

## 4. Team members

Readers need no token:

```console
$ owl init --mode client
$ owl remote add team https://skills.example.com
$ owl search review
$ owl install alice/review-pr
```

Authors that publish add the token (`--token-env`).

## 5. Govern writes

There is one shared write token. Ways to scale governance without per-user accounts:

- give the token only to a CI job and let people publish through pull requests
  ({doc}`publish-from-ci`),
- run `--private` and keep the token with a small group,
- run separate servers per audience ({doc}`multi-server`).

## 6. Operate

Back up the database ({doc}`../operations/backup`), monitor `GET /api/v1/health`, rotate the token by
restarting with a new `OWL_SERVER_TOKEN` and updating clients.
