# FAQ

**Does OWL work with agents other than Claude Code?**
OWL manages `SKILL.md` directories and installs them into any directory you point `--dir` (or
`install_dir`) at. Anything that reads Agent Skills-style folders can use them.

**Where are skills installed by default?** `~/.claude/skills/<name>/`. Use `-p` for `./.claude/skills`.

**Do I need a server?** No. Standalone mode (SQLite or git) has no server at all. A server is only for
sharing.

**Do I need PostgreSQL?** No. SQLite is the default. PostgreSQL is for shared servers with many
users/skills.

**Can I use a git repository as my only storage?** Yes – `owl init --backend git`.
See {doc}`guide/git-backend`.

**Can I install from a GitHub repository without importing it?**
Yes: `owl install https://github.com/org/repo.git --skill NAME` (or `--all`).

**Can two skills have the same name?** Yes, from different authors (`alice/x`, `bob/x`). Installing
both into one directory is not possible because the install directory is named after the skill; OWL
refuses to replace one with the other without `--force`.

**What happens if I edit an installed skill?** Nothing – OWL does not watch. `owl update` replaces the
directory (only when the source changed); local edits in an installed directory are overwritten by an
update, so edit the source and reinstall instead.

**How do I see what changed on the server?** `owl diff REF -r NAME`, or `owl outdated` for installed
skills.

**Does `pull --all` overwrite my changes?** Not silently: diverged skills are skipped with exit
status 1 unless you pass `--force`.

**Is there version history?** Not inside OWL (one current version per `author/name`). Use the git
backend, or keep your skills in git and `owl add` from there.

**How do I delete a skill from a server?** `owl remove author/name -r NAME -y` with a write token.

**Can I run OWL without internet?** Yes; only `git` clones and remotes need the network.

**Is the author verified?** No. See {doc}`operations/security`.

**Why is my skill "skipped"?** Run `owl validate PATH`; the message names the problem.

**Windows?** OWL is pure Python and should work, but is currently tested on Linux and macOS only.

**How do I move from SQLite to PostgreSQL?** {doc}`tutorials/migrate-existing-skills`.
