# Tools and install targets

All current coding agents read the same *Agent Skills* layout – `<skills dir>/<name>/SKILL.md` –
they only differ in **which directory** they scan. OWL calls such a directory pair a **target** and
installs to any number of them at once, globally or per project.

```console
$ owl targets
┏━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃   ┃ Target  ┃ Tool                        ┃ Global                   ┃ Project (-p)     ┃
│ * │ claude  │ Claude Code                 │ ~/.claude/skills         │ .claude/skills   │
│   │ opencode│ OpenCode                    │ ~/.config/opencode/skills│ .opencode/skills │
│   │ agents  │ Cross-tool .agents standard │ ~/.agents/skills         │ .agents/skills   │
│   │ codex   │ OpenAI Codex CLI            │ ~/.agents/skills         │ .agents/skills   │
│   │ gemini  │ Gemini CLI                  │ ~/.gemini/skills         │ .gemini/skills   │
│   │ copilot │ GitHub Copilot              │ ~/.copilot/skills        │ .github/skills   │
│   │ cursor  │ Cursor                      │ ~/.cursor/skills         │ .cursor/skills   │
```

```{note}
The directories follow each tool's public documentation at the time of writing. Tools change; if a
tool moves its directory, define a custom target (below) or pass `--dir`. Several tools also read the
neighbouring conventions (OpenCode, Cursor, Copilot and Gemini read `.agents/skills` and/or
`.claude/skills`), so installing to `agents` or `claude` is often enough.
```

## Installing for a tool

```console
$ owl install pdf-tools -t opencode                 # OpenCode, global (~/.config/opencode/skills)
$ owl install pdf-tools -t opencode -p              # OpenCode, this project (.opencode/skills)
$ owl install pdf-tools -t claude -t opencode -t gemini -p   # several tools at once
$ owl install --all -r owl -t all -p                # everything, for every known tool
```

- `--target/-t NAME` is repeatable; `all` means every known target. Targets that share a directory
  (`codex` and `agents`) are written once.
- `--project/-p` switches to the project directories, relative to the **current directory**.
- `--dir/-d PATH` bypasses targets and installs into that exact directory.

`installed`, `uninstall`, `outdated` and `update` take the same `-t/-p/-d` options, so you can manage
a tool's skills in isolation:

```console
$ owl installed -t opencode -p
$ owl update -t opencode
$ owl uninstall pdf-tools -t opencode -p
```

## Default targets

Without `-t` OWL uses the configured default targets (initially `claude`):

```console
$ owl config set targets claude,opencode      # every install goes to both
$ owl init --target opencode                  # at setup time
```

An optional `install_dir` in the config (`owl config set install_dir ~/my/skills`) replaces the
default targets for **global** installs with one custom directory; `-t` still overrides it.

## Custom targets

For a tool OWL does not know, add it to `config.json`:

```json
{
  "custom_targets": {
    "mytool": {
      "description": "My internal agent",
      "global": "~/.mytool/skills",
      "project": ".mytool/skills"
    }
  }
}
```

then `owl install pdf-tools -t mytool`. A custom target may also override a built-in name.

## Per-tool notes

| Tool | Notes |
| --- | --- |
| **Claude Code** | `~/.claude/skills` and `.claude/skills`. |
| **OpenCode** | Native skills support: `~/.config/opencode/skills` and `.opencode/skills`. OpenCode additionally reads `.claude/skills` and `.agents/skills`, so a Claude install is picked up too. The skill `name` must match its directory name – OWL always installs to `<name>/`, so this holds. |
| **Codex CLI** | Uses the cross-tool `.agents/skills` convention (`codex` and `agents` are the same directory). Older setups used `~/.codex/skills`: add a custom target if yours does. |
| **Gemini CLI** | `~/.gemini/skills`, `.gemini/skills` (also reads `.agents/skills`). |
| **GitHub Copilot** | `.github/skills` per project, `~/.copilot/skills` for the user (also reads `.claude/skills`, `.agents/skills`). |
| **Cursor** | `.cursor/skills`, `~/.cursor/skills` (also reads `.agents/skills`, `.claude/skills`). |

## Installing a whole registry quickly

```console
$ owl install --all -r owl -t opencode -t claude          # every skill of the default registry
$ owl install --all -r owl --tag git                      # only skills tagged git
$ owl install --all -r owl --author michaelweissdev -p    # one author, project scope
$ owl install a/x b/y c/z -r owl -t opencode              # a hand-picked set
```

Re-run `owl update` later to pick up newer versions; unchanged skills are detected by hash and left
alone. See {doc}`registries`.
