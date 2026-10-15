# Docker

The repository ships a `Dockerfile`:

```dockerfile
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[server,postgres]"
ENV OWL_HOME=/data
VOLUME /data
EXPOSE 8765
CMD ["owl", "serve", "--host", "0.0.0.0", "--port", "8765"]
```

## Build and run

```console
$ docker build -t owl .
$ docker run -d --name owl -p 127.0.0.1:8765:8765 \
    -e OWL_SERVER_TOKEN="$(openssl rand -hex 32)" \
    -e OWL_DB_URL='postgresql://owl:secret@db.internal/owl' \
    owl
```

Without `OWL_DB_URL` the container serves the SQLite database in the `/data` volume:

```console
$ docker run -d -p 127.0.0.1:8765:8765 -v owl-data:/data -e OWL_SERVER_TOKEN=… owl
```

Publish the port to `127.0.0.1` (as above) and let a reverse proxy expose it, rather than `-p 8765:8765`
which listens on all host interfaces.

## docker compose

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: secret
      POSTGRES_USER: owl
      POSTGRES_DB: owl
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U owl"]
      interval: 5s
      retries: 10

  owl:
    build: .
    depends_on:
      db: {condition: service_healthy}
    environment:
      OWL_DB_URL: postgresql://owl:secret@db/owl
      OWL_SERVER_TOKEN: ${OWL_SERVER_TOKEN:?set a token}
    ports: ["127.0.0.1:8765:8765"]
    restart: unless-stopped

volumes:
  pgdata:
```

```{note}
The Dockerfile has been written for the repository but is not built in CI yet; treat the first build
in your environment as a test.
```

## Health check

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8765/api/v1/health')"]
  interval: 30s
```
