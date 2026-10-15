# Minimal makefile for Sphinx documentation (run from the docs/ directory)
SPHINXBUILD ?= uv run sphinx-build
SOURCEDIR   = .
BUILDDIR    = _build

.PHONY: help html livehtml clean

help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)"

html:
	@$(SPHINXBUILD) -W --keep-going -b html "$(SOURCEDIR)" "$(BUILDDIR)/html"

livehtml:
	uv run sphinx-autobuild "$(SOURCEDIR)" "$(BUILDDIR)/html"

clean:
	rm -rf "$(BUILDDIR)"
