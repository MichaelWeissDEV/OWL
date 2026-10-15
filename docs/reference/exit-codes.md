# Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | an error occurred; or a check command found something: `validate` (invalid skills), `diff` (different), `outdated` (outdated skills), `pull`/`push` (diverged or unresolvable skills), `doctor` (hard failure) |
| 2 | wrong usage: unknown option, missing argument |
| 130 | interrupted or confirmation declined |

Errors are printed to stderr as `error: <message>`; no Python traceback is shown for expected
failures (`OwlError`). Unexpected exceptions do produce a traceback – please report them.
