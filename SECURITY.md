# Security policy

OWL is alpha software. Skills are text and files that AI agents may act on, so please treat
third-party skills like third-party code and review them before installing.

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** - use GitHub's *Security → Report a
vulnerability* feature on this repository (private vulnerability reporting), or contact the
maintainer through the GitHub profile. Do not open a public issue for security problems.

Include the affected version/commit, steps to reproduce and the impact. You will get an answer as
soon as practical; there is no formal SLA in the alpha phase.

## Supported versions

Only the latest commit on the default branch is supported during alpha.

## Scope notes

In scope: path traversal, symlink escapes, unintended overwrites or data loss, authentication or
authorisation bypass in the server, unsafe handling of untrusted skill content.

Known limitations (see the documentation): a SHA-256 hash detects changes but does not
authenticate a publisher; the server's single shared write token is not an account system.
