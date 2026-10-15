# Licensing

OWL, OWL Server and the OWL Registry are licensed under the **Apache License 2.0**
(`LICENSE` and `NOTICE` in each repository). The copyright stays with the author, Michael Weiss; the
license allows everyone to use, modify, fork and redistribute the code, including commercially, as long
as the copyright and license notices are kept and changes are marked.

## Why Apache-2.0

- permissive: forks and further development are welcome;
- an explicit patent grant protects users and contributors;
- the `NOTICE` file keeps the attribution to the original author visible in derived works.

## Contributions

Contributions are accepted under the same license (Apache-2.0, section 5: "inbound = outbound"). No
CLA is required.

## Skills in a registry

Skills carry their own `license` frontmatter or `skill.json` field, which OWL records in the registry
index. Skills without one are covered by the license of the registry repository they live in.

## Dependencies

All runtime dependencies are permissively or weakly-copyleft licensed open-source packages; check
`uv.lock` and run a license scanner of your choice before redistributing a bundled build.
