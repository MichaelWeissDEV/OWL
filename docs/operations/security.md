# Security

## Threat model

OWL stores and distributes text and files that **agents will read and may act on**. A malicious skill
is therefore dangerous in the way a malicious script is. OWL's job is to move skills safely and to
keep servers from being abused; reviewing skill *content* is up to you.

## What OWL does

| Area | Measure |
| --- | --- |
| Execution | OWL never executes skill content. It copies files. |
| Paths | every bundled path is validated (relative, POSIX, no `..`, no empty parts, no backslashes, not under `.git`) when read from disk, received over HTTP and again before writing |
| Symlinks | never followed when reading directories or cloned repositories, so a repository cannot make OWL read local files |
| Installs | only directories with an OWL marker of the same `author/name` are replaced; `--force` is explicit; installs go through a temp directory and rename |
| Git | commands run non-interactively (`GIT_TERMINAL_PROMPT=0`); clones are shallow and temporary |
| Server defaults | bind to `127.0.0.1`; read-only unless a token is configured |
| Tokens | compared with `secrets.compare_digest`; config file written `0600`; `--token-env` / `url_env` keep secrets out of files; `config show` masks tokens |
| HTML | the server's HTML page escapes all values; the API returns JSON only |
| Input | uploads are validated like local skills (name/author format, size ≤ 20 MiB, reserved names) |

## What OWL does not do

- **No per-user authentication or authorisation.** One shared write token. Anyone holding it can
  overwrite or delete any skill.
- **No signing or provenance.** `author` is a self-declared label; the server does not verify it.
  A writer can publish under any author name.
- **No content scanning.** Prompt injection or malicious scripts inside skills are not detected.
- **No TLS.** Use a reverse proxy.
- **No audit log.** Use proxy/database logs.
- **No rate limiting.** Use the proxy.

## Recommendations

1. Only install skills from sources you trust; read them (`owl show REF`, `owl diff REF`) before
   installing, especially bundled scripts.
2. Run servers behind TLS; use `--private` for internal-only catalogues.
3. Keep the write token in a secret store and rotate it when people leave.
4. Prefer pull requests + CI publishing ({doc}`../tutorials/publish-from-ci`) so every published
   skill is reviewed.
5. Give the database role of the server only the privileges it needs on its own database.
6. Pin git sources to tags/commits you reviewed: `owl install URL --ref v1.2.0`.

## Reporting vulnerabilities

Please report suspected vulnerabilities privately to the maintainer (see the repository's security
policy) instead of opening a public issue.
