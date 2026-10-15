"""Sphinx configuration for the OWL documentation."""

from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "_ext"))

project = "OWL"
author = "Michael Weiss"
copyright = "2026, Michael Weiss"  # noqa: A001
release = importlib.metadata.version("owl")
version = ".".join(release.split(".")[:2])

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx_copybutton",
    "owl_cli_docs",
    "sphinx_design",
    "sphinxcontrib.mermaid",
]

myst_enable_extensions = ["colon_fence", "deflist", "fieldlist", "attrs_inline", "tasklist"]
myst_heading_anchors = 3

source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
master_doc = "index"
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "sqlalchemy": ("https://docs.sqlalchemy.org/en/20/", None),
    "fastapi": ("https://fastapi.tiangolo.com", None),
}

autodoc_member_order = "bysource"
autodoc_typehints = "description"
napoleon_google_docstring = True

html_theme = "furo"
html_title = f"OWL {release}"
html_static_path = ["_static"]
html_theme_options = {
    "source_repository": "https://github.com/MichaelWeissDEV/OWL/",
    "source_branch": "main",
    "source_directory": "docs/",
}
copybutton_prompt_text = r"^\$ |^>>> "
copybutton_prompt_is_regexp = True
nitpicky = False
