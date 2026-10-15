# Python API

OWL is also a library. The public building blocks:

```python
from owl.stores.sql import SqlStore
from owl.parsing import load_skills
from owl.models import SearchQuery

store = SqlStore("skills.sqlite3")  # or "postgresql://user:pw@host/db"
for result in load_skills(Path("./skills"), default_author="me"):
    if result.valid:
        store.upsert(result.skill)

for s in store.search(SearchQuery(text="pdf", tags=["office"])):
    print(s.ref, s.version)
```

Talk to a server:

```python
from owl.stores.remote import RemoteStore

with RemoteStore("https://skills.example.com", token="…", label="team") as remote:
    skill = remote.get_ref("alice/pdf-forms")
    local.upsert(skill)
```

Embed the server in your own ASGI app:

```python
from owl.server import create_app

app = create_app(store, token="…", private=False)  # a FastAPI application
```

## Models

```{eval-rst}
.. automodule:: owl.models
   :members: Skill, SkillSummary, SearchQuery, validate_skill, normalize_labels, split_ref, OwlError, NotFound, AmbiguousRef, InvalidSkill
```

## Parsing

```{eval-rst}
.. automodule:: owl.parsing
   :members:
```

## Stores

```{eval-rst}
.. automodule:: owl.stores.base
   :members:

.. automodule:: owl.stores.sql
   :members: SqlStore, normalize_db_url

.. automodule:: owl.stores.directory
   :members: DirectoryStore

.. automodule:: owl.stores.remote
   :members: RemoteStore

.. autofunction:: owl.stores.open_store

.. autofunction:: owl.stores.open_remote
```

## Server

```{eval-rst}
.. autofunction:: owl.server.create_app
```

## Installer and sync planning

```{eval-rst}
.. automodule:: owl.installer
   :members:

.. automodule:: owl.sync
   :members:
```

## Sources and git

```{eval-rst}
.. autofunction:: owl.sources.load_source

.. automodule:: owl.gitutil
   :members: is_git_url, clone, commit_all, pull, push
```

## Configuration

```{eval-rst}
.. automodule:: owl.config
   :members: Config, StoreConfig, Remote, load_config, save_config
```

```{note}
The Python API is not yet covered by a stability promise; it follows the CLI's 0.x version.
```
