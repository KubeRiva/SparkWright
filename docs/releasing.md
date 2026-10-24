# Releasing SparkWright

One-time setup (a maintainer with PyPI and GitHub admin rights):

1. On PyPI, add a trusted publisher for project `sparkwright`:
   owner `kuberiva`, repository `sparkwright`, workflow `release.yml`,
   environment `pypi`.
2. In the GitHub repository settings, create the environment `pypi`
   (optionally with required reviewers, so a person approves each upload).

Each release:

1. Set `__version__` in `src/sparkwright/__init__.py` (for example `0.1.0`)
   and move the CHANGELOG entry out of "unreleased".
2. Run the tests, `sparkwright check`, and regenerate adapters
   (`sparkwright adapt claude-code --marketplace`, `adapt codex --out adapters/codex`,
   `adapt gemini`); commit.
3. Tag and push: `git tag v0.1.0 && git push origin v0.1.0`.
4. The `release` workflow checks the tag matches the version, builds,
   runs `twine check` and a smoke test, then publishes with trusted
   publishing (no API token is stored anywhere).
