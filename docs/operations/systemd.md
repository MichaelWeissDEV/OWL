# systemd

## Service user and installation

```console
# useradd --system --home /var/lib/owl --shell /usr/sbin/nologin owl
# python3.13 -m venv /opt/owl
# /opt/owl/bin/pip install "/path/to/OWL[server,postgres]"
# install -d -o owl -g owl /var/lib/owl
```

## Environment file (root-only)

`/etc/owl/owl.env`, mode `0600`, owner root:

```ini
OWL_SERVER_TOKEN=…
OWL_DB_URL=postgresql://owl:…@127.0.0.1/owl
OWL_HOME=/var/lib/owl
```

## Unit

`/etc/systemd/system/owl.service`:

```ini
[Unit]
Description=OWL skill server
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
User=owl
Group=owl
EnvironmentFile=/etc/owl/owl.env
ExecStart=/opt/owl/bin/owl serve --host 127.0.0.1 --port 8765
Restart=on-failure
RestartSec=3

# hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/owl
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

[Install]
WantedBy=multi-user.target
```

```console
# systemctl daemon-reload
# systemctl enable --now owl
# journalctl -u owl -f
```

## Mirror timer on a client

`owl-mirror.service` + `owl-mirror.timer` to keep a local library in sync:

```ini
# owl-mirror.service
[Service]
Type=oneshot
Environment=OWL_HOME=/var/lib/owl-client
ExecStart=/opt/owl/bin/owl pull --all -r public

# owl-mirror.timer
[Timer]
OnCalendar=hourly
Persistent=true
[Install]
WantedBy=timers.target
```
