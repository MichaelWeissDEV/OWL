# Extending OWL

## Adding a storage backend

1. Implement `SkillStore` (`owl/stores/base.py`):

   ```python
   class MyStore(SkillStore):
       def upsert(self, skill: Skill) -> Skill: ...
       def get(self, author: str, name: str) -> Skill | None: ...
       def delete(self, author: str, name: str) -> bool: ...
       def search(self, query: SearchQuery) -> list[SkillSummary]: ...
       def facets(self, kind: str) -> list[tuple[str, int]]: ...
   ```

   Rules the contract tests enforce:

   - `upsert` validates (`validate_skill`) and raises `InvalidSkill`; an unchanged `sha256` is a no-op
     returning the stored skill (timestamps untouched).
   - Returned skills must have **the same `sha256`** as stored: persist all of content, extras, files,
     tags and topics exactly.
   - `search` semantics: AND of words over name/description/author/content/tags/topics,
     case-insensitive substring, exact author, all tags/topics, ordering by `rank()` then author, name.
   - `facets` returns `(value, count)` sorted by count desc then value.
   - `author` is case-insensitive on input (store lower-case).

2. Register it in `owl.stores.open_store` and the `BACKENDS` tuple in `owl/config.py`.
3. Add it as a parameter of the `any_store` fixture in `tests/conftest.py` – the whole contract suite
   then runs against it.
4. Document it under {doc}`../guide/index`.

## Adding a CLI command

Put it in `cli_tools.py` (or `cli.py` for core commands) using the helpers `_one`, `_stores`,
`RemoteOpt`, `LocalOpt`, `JsonOpt`. Use completion callbacks from `owl.completion` for arguments.
Add a CLI test and the command appears in the generated {doc}`../reference/cli` automatically.

## Adding an API endpoint

Add it to `create_app` in `server.py` with the right dependency (`read` or `write`), extend
`RemoteStore` if clients need it, and document it in {doc}`../reference/http-api`.

## Ideas that fit the architecture

See {doc}`../roadmap`.
