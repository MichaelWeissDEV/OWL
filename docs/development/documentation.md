# Writing the documentation

The documentation uses [Sphinx](https://www.sphinx-doc.org/) with the
[MyST](https://myst-parser.readthedocs.io/) Markdown parser, the [Furo](https://pradyunsg.me/furo/)
theme, a small in-repo extension (`docs/_ext/owl_cli_docs.py`) that generates the CLI reference from the Typer app, `sphinx-design` (cards), `sphinxcontrib-mermaid` (diagrams)
and `sphinx-copybutton`.

## Build

```console
$ uv sync --all-extras --group docs
$ cd docs && make html            # warnings are errors (-W)
$ open _build/html/index.html
$ make livehtml                   # auto-rebuilding server (needs sphinx-autobuild)
```

## Structure

| Directory | Audience |
| --- | --- |
| `getting-started/` | newcomers |
| `guide/` | feature explanations |
| `tutorials/` | end-to-end scenarios |
| `reference/` | exact facts: CLI (generated), API, config, schema |
| `operations/` | running a server |
| `development/` | contributors |

## Conventions

- Use `console` blocks for shell sessions (`$ ` prompts are not copied by the copy button).
- Cross-reference with `{doc}` and `{ref}`; never hard-code paths of other pages.
- Examples must be true: run them. Prefer `OWL_HOME=$(mktemp -d)` in examples that write.
- The CLI reference is generated – change help texts in the code, not in the docs.
- Mermaid diagrams for architecture and flows; keep them small.

## Read the Docs

Import the repository at readthedocs.org; `.readthedocs.yaml` does the rest (installs with `uv sync
--frozen --all-extras --group docs`, builds HTML, PDF and ePub, fails on warnings).
