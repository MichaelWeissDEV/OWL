# Client mode

A client keeps a **local library** and talks to any number of **remotes** (OWL servers).

## Set up

```console
$ owl init --mode client --author michael
$ owl remote add team https://skills.example.com --token-env OWL_TEAM_TOKEN
$ owl remote add public https://owl.example.org
$ owl remote list
* team     https://skills.example.com
  public   https://owl.example.org
$ owl remote ping team
```

`owl remote add NAME URL`:

| Option | Meaning |
| --- | --- |
| `--token T` | store the token in `config.json` (mode `0600`) |
| `--token-env VAR` | read the token from environment variable `VAR` at run time (preferred) |
| `--default` | make this the default remote (the first remote becomes default automatically) |

Reading never requires a token unless the server runs with `--private`. A token is needed for
`push` and for `remove -r`.

`owl remote remove NAME` forgets a remote (and moves the default if necessary);
`owl remote ping [NAME]` prints the server's `/info` (version, skill count, writable, private).

## Which store does a command use?

| Option | Uses |
| --- | --- |
| *(none)*, mode `standalone`/`server` | local library |
| *(none)*, mode `client` and a default remote | the **default remote** |
| `--local` | local library |
| `-r NAME` | that remote (repeatable for `list`/`search`/facets) |
| `--all` (`search` only) | local library **and** every remote |

Commands that read: `list`, `search`, `show`, `install`, `authors`, `tags`, `topics`, `stats`,
`export`. Commands that need exactly one store (`show`, `install`, `stats`, `export`, `remove`) reject
several `-r` options.

## Searching several servers

```console
$ owl search pdf --all
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Source ┃ Skill           ┃ Version ┃ Description  ┃ Tags    ┃
│ local  │ michael/pdf     │ 1.0.0   │ ...          │ pdf     │
│ team   │ alice/pdf-forms │ 0.3.0   │ ...          │ pdf     │
│ public │ acme/pdf-tools  │ 2.1.0   │ ...          │ pdf     │
```

An unreachable remote produces a warning and the others still answer. With a single store the
error is fatal instead.

## Installing straight from a remote

```console
$ owl install alice/pdf-forms -r team
```

No import into the library needed.

## Pull and push

```console
$ owl pull alice/pdf-forms -r team        # remote -> local library
$ owl pull --all -r team
$ owl push michael/release-notes -r team  # local library -> remote (needs a write token)
$ owl push --all -r team
$ owl diff alice/pdf-forms -r team        # compare local with remote
```

`-r` may be omitted when there is a default remote or exactly one remote. Details, conflict handling
and bookmarks: {doc}`syncing`.

## Cache for completion

Whenever `list`, `search` or `pull` talk to a remote, OWL records the skill references, authors,
tags and topics it saw in `state.json`. Shell completion uses that cache, so it can complete names of
remote skills without ever touching the network. See {doc}`completion`.
