# Your own skill registry

**Result:** a GitHub repository that collects skills, indexes itself via CI, and that you and others
can install from with one command.

## 1. Create it locally

```console
$ owl registry init ~/work/acme-registry --name acme-registry \
      --description "Skills of the Acme platform team" \
      --git-url git@github.com:acme/skill-registry.git
registry created at /home/me/work/acme-registry
```

## 2. Add skills

```console
$ owl registry publish ~/.claude/skills/pdf-tools ./review-pr --dir ~/work/acme-registry --author acme
published acme/pdf-tools 1.2.0
published acme/review-pr 0.3.0
index updated: 2 skills (commit and push to share it)
$ cat ~/work/acme-registry/INDEX.md
```

Add `tags:` and `topics:` to the skills' frontmatter before publishing – they drive search and the
tag/topic listings in `INDEX.md`.

## 3. Push

Create the empty repository `acme/skill-registry` on GitHub, enable *Settings → Actions → General →
Workflow permissions → Read and write*, then:

```console
$ cd ~/work/acme-registry
$ git add -A && git commit -m "feat: first skills"
$ git push -u origin main
```

## 4. Let CI take over

From now on, contributors only add or change directories below `skills/`. The workflow validates pull
requests and regenerates `index.json` / `INDEX.md` after every merge, including each skill's
`updated_at`. You never maintain the index by hand.

## 5. Consume it

```console
$ owl registry add acme git@github.com:acme/skill-registry.git
$ owl search review -r acme
$ owl install --all -r acme -t claude -t opencode          # everything, for both tools
$ owl install acme/review-pr -r acme -p -t opencode        # one skill, project scope
```

Keep installed skills current:

```console
$ owl update
```

## 6. Combine with a server

Large organisations often run both: the registry is the reviewed, curated source; a PostgreSQL
backed server holds team-internal work in progress.

```console
$ owl search terraform --all
```

See {doc}`../guide/registries` for details and {doc}`../reference/registry-format` for the format.
