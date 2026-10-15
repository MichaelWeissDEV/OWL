"""OWL - a skill manager.

OWL manages *skills* (``SKILL.md`` files plus optional bundled files) and can run
as a standalone tool (SQLite or a plain git repository), as a server (SQLite or
PostgreSQL behind an HTTP API) or as a client that pulls from / pushes to one or
more such servers.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
