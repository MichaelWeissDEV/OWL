# Publishing skills from CI

**Result:** a repository of skills that is validated on every pull request and published to an OWL
server on merge.

## Repository

```text
skills/
  pdf-tools/SKILL.md
  review-pr/SKILL.md
.github/workflows/skills.yml
```

## Workflow

```yaml
name: skills
on:
  pull_request:
  push:
    branches: [main]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv tool install "git+https://github.com/MichaelWeissDEV/OWL"
      - run: owl validate ./skills

  publish:
    if: github.ref == 'refs/heads/main'
    needs: validate
    runs-on: ubuntu-latest
    env:
      OWL_HOME: ${{ runner.temp }}/owl
      OWL_SKILLS_TOKEN: ${{ secrets.OWL_SKILLS_TOKEN }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv tool install "git+https://github.com/MichaelWeissDEV/OWL"
      - run: |
          owl init --mode client --author acme
          owl remote add prod https://skills.example.com --token-env OWL_SKILLS_TOKEN
          owl add ./skills
          owl push --all -r prod
```

`owl push` exits with status 1 if a skill diverged on the server (somebody pushed a different
version from elsewhere) – the job fails visibly instead of overwriting. Use `--force` only if CI is
the single source of truth.

## Notes

- Use a scratch `OWL_HOME` on CI runners so nothing leaks between jobs.
- Store the write token as a secret; the workflow passes it via an environment variable
  (`--token-env`), never on the command line.
- Add `owl outdated`-style checks to downstream projects to keep installed skills current.
