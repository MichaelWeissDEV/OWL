# Scripting and automation

## JSON output

`list`, `search`, `show`, `authors`, `tags`, `topics`, `stats`, `installed`, `outdated` accept
`--json`. Human-oriented decoration goes to **stderr**, data to **stdout**:

```console
$ owl search -t sql --json | jq -r '.[] | "\(.author)/\(.name) \(.version)"'
$ owl stats --json | jq '.skills'
$ owl show alice/pdf --raw > SKILL.md        # exact SKILL.md text
```

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | error (message on stderr), `validate` found invalid skills, `pull`/`push` skipped a diverged or unknown skill, `diff` found differences, `outdated` found outdated skills, `doctor` found a hard failure |
| 2 | invalid command-line usage (Typer/Click) |
| 130 | aborted (Ctrl-C / declined confirmation) |

## Non-interactive use

- `remove` asks for confirmation; pass `--yes/-y` in scripts.
- No command ever prompts for credentials. Tokens come from `--token-env` / environment variables.
- Git operations run with `GIT_TERMINAL_PROMPT=0`, so a missing credential fails instead of hanging.

## Recipes

**Nightly mirror of a public server**

```console
$ owl pull --all -r public || echo "some skills diverged" >&2
```

**Fail CI when skills in a repository are invalid**

```console
$ owl validate ./skills
```

**Keep a project's skills current**

```console
$ owl outdated -p || owl update -p
```

**Publish every changed skill from CI**

```console
$ owl add ./skills && owl push --all -r team
```

**Use from Python** – the building blocks are importable, see {doc}`../reference/python-api`.
