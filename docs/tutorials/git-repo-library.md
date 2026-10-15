# A library in a git repository

**Result:** your skills live in a git repository (GitHub, GitLab, …); every machine keeps a clone;
`owl sync` shares changes.

## 1. Create an empty repository

On your git host create `my-skills` (private or public).

## 2. Initialise OWL against it

```console
$ owl init --backend git --git-url git@github.com:me/my-skills.git --author me
```

OWL clones into `~/.owl/repo` (or creates an empty repository there).

## 3. Add skills and publish

```console
$ owl add ~/.claude/skills
$ owl sync -m "import my skills"
committed local changes
synced with origin
```

The repository now looks like:

```text
skills/me/pdf-tools/SKILL.md
skills/me/pdf-tools/skill.json
skills/me/pdf-tools/scripts/extract.py
...
```

## 4. A second machine

```console
$ owl init --backend git --git-url git@github.com:me/my-skills.git
$ owl list
$ owl install pdf-tools
```

## 5. Daily use

```console
$ owl add ./new-skill        # or edit files in ~/.owl/repo/skills/... directly
$ owl sync                   # commit, rebase on origin, push
```

If two machines edited the same skill, the second `owl sync` stops with a conflict message and leaves
the repository clean (rebase aborted). Resolve it with plain git in `~/.owl/repo`:

```console
$ cd ~/.owl/repo && git pull --rebase       # fix conflicts, git rebase --continue
$ owl sync
```

## 6. Let others install from it without OWL's git backend

```console
$ owl install https://github.com/me/my-skills.git --skill pdf-tools
```

Works because the repository contains ordinary `SKILL.md` files.
