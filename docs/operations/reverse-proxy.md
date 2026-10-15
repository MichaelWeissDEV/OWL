# Reverse proxy and TLS

OWL speaks plain HTTP; terminate TLS in front of it. Uploads can be up to 20 MiB of skill content
(base64 inflates this by one third), so allow request bodies of about 30 MB.

## Caddy (automatic certificates)

```text
skills.example.com {
    request_body {
        max_size 30MB
    }
    reverse_proxy 127.0.0.1:8765
}
```

## nginx

```nginx
server {
    listen 443 ssl http2;
    server_name skills.example.com;
    ssl_certificate     /etc/letsencrypt/live/skills.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/skills.example.com/privkey.pem;

    client_max_body_size 30m;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
```

## Extra hardening at the proxy

- Rate-limit `PUT`/`DELETE` and failed authentications.
- Restrict `PUT`/`DELETE` to your office/VPN network if the audience is internal, while leaving `GET`
  open: `limit_except GET { allow 10.0.0.0/8; deny all; }` in nginx.
- For a fully private server use `owl serve --private` *and* network restrictions.

## Client trust

Clients verify certificates via httpx and the system trust store. For a private CA export
`SSL_CERT_FILE=/path/to/ca.pem` in the client's environment.
