# Python

Recognised by `.py` sources, `pyproject.toml` or `setup.py`.

## `tests-run`

`test_*.py` / `*_test.py` files run by pytest or unittest (directly, as `python -m` or `coverage run -m`, or in the
tox environments CI runs), or by nox, whose sessions are not read.

## `coverage`

coverage.py (`coverage run --branch`, or `branch = true` in the configuration it reads: `.coveragerc`, else the first of
setup.cfg, tox.ini and pyproject.toml with coverage settings) or pytest-cov (`--cov --cov-branch`, also from pytest's
`addopts`), run directly, as `python -m`, or through uv, Poetry, Pipenv, PDM, Hatch or pipx.

## `platform-matrix`

The toolchains are Python versions.

## `compiler-warnings`

Warnings are errors: `-W error`, `PYTHONWARNINGS=error`, or pytest `filterwarnings = error`.

## `type-checking`

mypy (or dmypy), pyright or basedpyright, pyrefly, or ty, in CI or a pre-commit hook CI runs. Strict mode is a
bonus: `strict = true` in `[tool.mypy]` or a `[mypy]` section, `mypy --strict`, or pyright's `typeCheckingMode`
`strict` (basedpyright's `all`).

## `mutation-testing`

mutmut (`mutmut run`; settings in `[tool.mutmut]` of pyproject.toml or `[mutmut]` of setup.cfg), cosmic-ray
(`cosmic-ray exec`) or mutatest. `mutmut run` given mutant names (`mutmut run 'pkg.module.*'`) counts as running on the
changes only.

## `code-formatting`

ruff format (`ruff format --check`, `--diff` or `--exit-non-zero-on-format`; settings in `[tool.ruff]` of
pyproject.toml, ruff.toml or .ruff.toml) or black (`--check` or `--diff`; settings in `[tool.black]`), run directly,
through a launcher or tox, as the `psf/black` or `astral-sh/ruff-action` action, or as a pre-commit hook CI runs
(`ruff-format`, `black`). Both have a default style, so CI enforcement alone passes; `black .` alone only rewrites
files.

## `function-limits`

lizard runs in CI with a length limit.

## `static-analysis`

`ruff check`, pylint or flake8, in CI or a pre-commit hook CI runs (pre-commit.ci, or `pre-commit run` in a
job).

## `security-scanning`

bandit, or `ruff check` with its `S` rules selected (on its command line or in its settings). In CI, where the tool runs
(a setting alone, which nothing CI runs reads, does not count); CodeQL, GitLab SAST or semgrep count too.

## `dependency-management`

Dependencies declared in `pyproject.toml`, `setup.py` or requirements files are locked by a committed `uv.lock`,
`poetry.lock`, `pdm.lock`, `Pipfile.lock` or `pylock.toml`, or by requirements pinned with `--hash`. Requirements files
in `.github` are CI's own: pinned by hash, they lock what CI installs, but they declare nothing. Those of the docs and
tooling (`docs/requirements.txt`) are theirs, not the product's.

## `dependency-audit`

pip-audit (or `pypa/gh-action-pip-audit`) or `safety scan`.

## `license`

`[project] license` in `pyproject.toml`.

## `committed-artifacts`

`__pycache__/`, `*.py[co]`, `*.egg-info/`, a top-level `dist/` or `build/`.

## `vcs-ignore`

`__pycache__/` or `*.py[cod]`.
