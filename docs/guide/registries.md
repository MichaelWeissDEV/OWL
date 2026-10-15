# Registries

A **registry** is a git repository of skills with a generated index. It is the simplest way to
publish and consume skills: hosting is just GitHub (or any git server), updates are pull requests,
and clients need nothing but `git`.

OWL ships with a **default registry**, `owl`, pointing at
`https://github.com/MichaelWeissDEV/owl-registry.git` (configured on fresh installs; disable with
`OWL_DEFAULT_REGISTRY=` empty or remove it with `owl registry remove owl`).

```{mermaid}
flowchart LR
    PR[pull request<br/>adds skills/…] --> CI[CI: validate]
    CI --> M[merge to main]
    M --> IDX[CI: owl registry index<br/>index.json + INDEX.md<br/>+ last update]
    IDX --> G[(git repo)]
    G -- shallow clone,<br/>refresh hourly --> C[owl client<br/>search · install · pull]
```

## Using registries

```console
$ owl registry list
* owl     https://github.com/MichaelWeissDEV/owl-registry.git
$ owl search commit -r owl              # searches the index – no need to read every skill
$ owl show conventional-commits -r owl
$ owl install michaelweissdev/conventional-commits -r owl -t opencode
$ owl install --all -r owl              # everything, see the tools page
$ owl pull michaelweissdev/conventional-commits -r owl     # copy into your own library
```

A registry is simply a *remote* of kind `registry`, so **every read command works with `-r NAME`**
(`list`, `search`, `show`, `install`, `pull`, `authors`, `tags`, `topics`, `stats`, `export`,
`diff`) and `search --all` includes registries next to servers and the local library. Registries
are **read-only**: `push` is refused with a hint (contribute by pull request).

### Add another registry

```console
$ owl registry add team https://github.com/acme/skill-registry.git
$ owl registry add pinned https://github.com/acme/skill-registry.git --ref v2
$ owl registry add local ~/work/my-registry          # a directory works too
$ owl registry update                                # refresh now
$ owl registry remove team
```

Any repository containing `SKILL.md` files works as a registry. With an `index.json` OWL searches the
index (fast, no skill is read until you `show`/`install` it); without one it scans the repository
(slower, but then it can also search the skill *text*).

### Caching and offline use

Git registries are cloned shallowly (`--depth 1`) into `$OWL_HOME/registries/<name>` on first use and
refreshed at most once an hour (`owl registry update` forces it). If the network is down the cached
copy is used. Searching never downloads individual skills; installing reads only the chosen skills
from the clone.

### Registries *and* servers

Registries and PostgreSQL-backed servers can be combined freely:

```console
$ owl remote add corp https://skills.corp.example --token-env CORP_TOKEN
$ owl search kubernetes --all           # local + owl registry + corp server
```

## Creating your own registry

```console
$ owl registry init ~/work/my-registry --name my-registry \
      --git-url git@github.com:me/my-registry.git
$ owl registry publish ./skills/pdf-tools --dir ~/work/my-registry
$ cd ~/work/my-registry && git add -A && git commit -m "feat: add pdf-tools" && git push -u origin main
```

`init` creates a git repository (branch `main`) with:

| File | Purpose |
| --- | --- |
| `registry.json` | marks the directory as a registry; name and description |
| `skills/<author>/<name>/` | the skills (`SKILL.md`, `skill.json`, bundled files) |
| `index.json`, `INDEX.md` | generated index and overview |
| `.github/workflows/registry.yml` | CI that validates and keeps the index current |
| `README.md`, `.gitignore` | usage notes for contributors |

`owl registry publish` copies skills (from directories, trees or git URLs) into the checkout,
validates them and rewrites the index. Re-publishing an unchanged skill changes nothing.

### The index

`owl registry index [DIR]` regenerates both generated files; `--check` verifies they are current
(exit 1 otherwise). The format is documented in {doc}`../reference/registry-format`. Highlights:

- `index.json` – every skill with `ref`, version, description, tags, topics, `sha256`, `path`,
  `files` and **`updated_at`**; top-level `count` and `generated_at` (the newest `updated_at`).
- `INDEX.md` – a compact table with links to each skill plus listings by topic and tag, meant to be
  read quickly by people and by agents.
- Deterministic: running the generator twice produces identical files, so CI commits only real
  changes.

### CI keeps the index up to date

The generated workflow (`.github/workflows/registry.yml`)

1. on **pull requests** that touch `skills/**`: validates all skills (`owl validate skills`);
2. on **pushes to `main`**: validates, runs `owl registry index .`, and commits `index.json` and
   `INDEX.md` back as `github-actions[bot]` with `[skip ci]`.

It checks out the full history (`fetch-depth: 0`) because `updated_at` comes from git: for a new or
changed skill it is the commit time of the skill directory; while a skill's hash is unchanged its
previous value is kept, so unrelated commits never touch it. No manual index maintenance is needed –
never edit the generated files.

```{note}
The workflow installs OWL with `uv tool install "git+https://github.com/MichaelWeissDEV/OWL"`. If you
fork OWL or pin a version, change that line (for example to `…OWL@v0.2.0`).
```

For the push step to work, repository settings must allow workflow write access
(*Settings → Actions → General → Workflow permissions: Read and write*).

### Contributing to a registry

1. Fork, add `skills/<your-author>/<skill-name>/SKILL.md` (+ optional files).
2. `owl validate skills` locally.
3. Open a pull request; CI validates; after merge the index updates itself.

## Registry or server?

| | Registry (git) | Server (`owl serve`) |
| --- | --- | --- |
| Hosting | any git host | a process + database |
| Write access | pull requests | token |
| Search | index (names, description, tags) | full text incl. skill body |
| Audience | public / curated | team / internal |
| Setup effort | minimal | moderate |
