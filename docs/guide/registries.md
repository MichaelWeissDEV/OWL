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
| `skills/<name>/` | the skills (`SKILL.md`, `skill.json`, bundled files); **flat** - the author is metadata |
| `index.json`, `stats.json` | generated index and statistics (machine readable) |
| `INDEX.md`, `STATS.md` | the same data, quick to read |
| `.github/workflows/registry.yml` | CI that validates pull requests and keeps the generated files current |
| `README.md`, `CONTRIBUTING.md`, `assets/owl.png`, `.gitignore` | usage notes, contribution rules, logo |

`owl registry publish` copies skills (from directories, trees or git URLs) into the checkout,
validates them and rewrites the generated files. Re-publishing an unchanged skill changes nothing.
A skill whose **name is already used by a different author** is refused – names are unique per
registry because the directory is `skills/<name>/`.

### Maintaining a registry

| Command | Purpose |
| --- | --- |
| `owl registry check [DIR] [--fresh]` | validate everything read-only: structure, names, frontmatter, paths, symlinks, sizes, collisions, index consistency (`--fresh`: generated files must be current). Exit 1 on problems; this is what CI runs on pull requests |
| `owl registry index [DIR] [--check]` | regenerate (or verify) `index.json`, `stats.json`, `INDEX.md`, `STATS.md`. Nothing is written if validation fails, so the last valid state survives |
| `owl registry migrate [DIR] [--dry-run]` | convert the old `skills/<author>/<name>/` layout to `skills/<name>/` |
| `owl registry upgrade [DIR] [--overwrite]` | migrate, add missing scaffold files and regenerate; `--overwrite` also refreshes the OWL-managed workflow, README and CONTRIBUTING |

### Migrating a registry from the old layout

Older registries stored skills in `skills/<author>/<name>/`. The flat layout has priority;
migrate with:

```console
$ owl registry migrate ~/work/my-registry --dry-run      # preview
$ owl registry migrate ~/work/my-registry
$ git -C ~/work/my-registry status                       # review, then commit
```

- Every skill is **copied**, verified (identical content hash; the author the old path implied is
  written to `skill.json` if it was not declared) and only then removed from the old place.
- Conflicts (two authors with the same skill name, a target directory that already exists, invalid
  skills) **abort the whole migration before anything is touched**.
- Running it again after success reports "nothing to migrate".
- Old registries of other people stay *readable* by OWL clients without migration; only writing
  requires the flat layout.

### The generated files

The formats are documented in {doc}`../reference/registry-format`. Highlights:

- `index.json` – every skill with `ref`, author, version, description, tags, topics, license,
  compatibility, `sha256`, `path`, file count, size, **`updated_at`** and git **`revision`**;
  top-level `count` and `generated_at` (the newest `updated_at`).
- `stats.json` – totals, skills per author, tag, topic, compatibility and license. Only facts that
  derive from the registry itself – **no usage or download counts**.
- `INDEX.md` / `STATS.md` – the same data as readable tables with links to every skill.
- Deterministic: running the generator twice produces identical files, so CI commits only real
  changes.

### CI: validate pull requests, update after merge

The generated workflow (`.github/workflows/registry.yml`) has two clearly separated jobs and starts
with **no permissions at all**:

| Job | Runs on | Permissions | What it does |
| --- | --- | --- | --- |
| `validate` | pull requests *and* pushes | `contents: read` | `owl registry check .` – only reads files |
| `index` | pushes to `main`, after `validate` succeeded | `contents: write` | `owl registry index .`, commits `index.json`, `stats.json`, `INDEX.md`, `STATS.md` as `github-actions[bot]` with `[skip ci]` – only when they changed |

Security properties: pull requests (including forks) never see a write token (`pull_request`, never
`pull_request_target`); the privileged job runs only for code that is already on `main`; skill
scripts are never executed (the registry is passive data); if validation fails the old generated
files stay in place.

`index` checks out the full history (`fetch-depth: 0`) because `updated_at` and `revision` come from
git: for a new or changed skill they are the last commit touching the skill directory; while a
skill's hash is unchanged the previous values are kept. No manual index maintenance is needed –
never edit the generated files.

```{note}
The workflow installs OWL with `uv tool install "git+https://github.com/MichaelWeissDEV/OWL"`. If you
fork OWL or pin a version, change that line (for example to `…OWL@v0.2.0`).
```

For the push step to work, repository settings must allow workflow write access
(*Settings → Actions → General → Workflow permissions: Read and write*). Other CI systems (GitLab CI,
Forgejo Actions, …) only need to run the same two commands: `owl registry check .` for merge
requests and `owl registry index .` plus a commit on the default branch.

### Contributing to a registry

1. Fork, add `skills/<skill-name>/SKILL.md` (+ optional files; `author:` goes into the metadata).
2. `owl registry check .` locally.
3. Open a pull request; CI validates; after merge the index updates itself.

## Registry or server?

| | Registry (git) | Server (`owl serve`) |
| --- | --- | --- |
| Hosting | any git host | a process + database |
| Write access | pull requests | token |
| Search | index (names, description, tags) | full text incl. skill body |
| Audience | public / curated | team / internal |
| Setup effort | minimal | moderate |
