# Licensing

```{important}
OWL currently has **no license file**. Without a license all rights remain with the author, which
means others may not legally use, modify or redistribute the code. Adding a license is a decision
only the repository owner can make - nothing has been added on their behalf.
```

## Options to consider

| License | Character | Notes |
| --- | --- | --- |
| MIT | permissive, very short | maximum adoption; no patent grant |
| Apache-2.0 | permissive with explicit patent grant | common for developer tools; requires NOTICE handling |
| MPL-2.0 | weak copyleft (file level) | modifications to OWL files stay open, can be combined with proprietary code |
| GPL-3.0 / AGPL-3.0 | strong copyleft | AGPL also covers network use - relevant for the OWL server |

Questions to answer first: should companies be able to embed OWL in closed products? Should
modifications to a hosted OWL server have to be published? Are third-party contributions accepted
(consider a DCO or CLA)?

## Applying a decision

1. Add `LICENSE` with the full text, set `license` in `pyproject.toml`
   (`license = "Apache-2.0"`, SPDX expression) and the matching classifier.
2. Add the license badge to the README and mention it in `CONTRIBUTING.md`.
3. Use the same license (or a deliberately chosen one) for `owl-registry`'s *tooling*; skills in a
   registry carry their own `license` frontmatter, which OWL records in the index.
