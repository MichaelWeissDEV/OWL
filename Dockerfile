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
# Binds all interfaces inside the container: publish the port deliberately and set
# OWL_SERVER_TOKEN (and OWL_DB_URL for PostgreSQL).
CMD ["owl", "serve", "--host", "0.0.0.0", "--port", "8765"]
