# Releasing

1. Update the version in `pyproject.toml` and `src/owl/__init__.py` (they must match).
2. Move the "Unreleased" entries of {doc}`../changelog` under the new version heading with the date.
3. `uv lock` if dependencies changed; run the full quality gates ({doc}`contributing`).
4. Commit, then tag and push:

   ```console
   $ git tag -a v0.2.0 -m "OWL 0.2.0"
   $ git push origin main v0.2.0
   ```

5. `release.yml` builds and publishes a GitHub release with the wheel and sdist.
6. Read the Docs builds the `stable` documentation from the tag (activate the version in the project).

## Versioning

OWL follows semantic versioning once it reaches 1.0. While in 0.x, minor versions may contain
breaking changes; they are always called out in the changelog.

## Publishing to PyPI (optional)

Add a job using [trusted publishing](https://docs.pypi.org/trusted-publishers/) that runs
`uv publish` on tags. No API token needs to be stored in the repository.
