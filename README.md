# project_validator

[![ci](https://github.com/cpp-best-practices/project_validator/actions/workflows/ci.yml/badge.svg)](https://github.com/cpp-best-practices/project_validator/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/cpp-best-practices/project_validator/graph/badge.svg)](https://codecov.io/gh/cpp-best-practices/project_validator)

A tool to validate a project's build, CI and tooling against best practices.

It recognises a project's languages and build systems, and judges each language by its own
ecosystem's tools: a C++ project needs branch coverage from gcovr or llvm-cov, a Python project from coverage.py, a
Rust project from cargo-llvm-cov. [docs/ecosystems](docs/ecosystems) has a page for each supported ecosystem, saying
how it is recognised and what each check accepts for it; `project-validator --list` shows which checks apply to which
ecosystems, and `--format markdown` lays a project's results out as a grid of checks against ecosystems, each
cell naming the tools that ran. The grid for project_validator itself is in the job summary of every
[CI run](https://github.com/cpp-best-practices/project_validator/actions/workflows/ci.yml?query=branch%3Amain).
Checks that do not apply to any of the project's languages are reported as `SKIP`. A project using several languages
is judged for each of them and gets the worst result. In a project of no recognised language, only the checks that
apply to every project run.
More ecosystems can be added with plugins (see [Adding an ecosystem](#adding-an-ecosystem)).

The validator itself is pure Python and has no build step; it only inspects
(and, with `--build`, configures and builds) the project it is pointed at.

## Requirements

- Python 3.14+ (the system Python on Ubuntu 26.04 LTS; no installation step,
  run with `python3 -m project_validator <path>`)
- [PyYAML](https://pyyaml.org/) 6.0+ (`python3-yaml` on Ubuntu, or `python3 -m pip install PyYAML`)
- Optionally [rich](https://github.com/Textualize/rich) 13.0+ for colored output
- CMake / CTest, only for `--build` (already required by any CMake project being validated)

On a machine without Python 3.14, `uv run` or a distro backport will work.
In CI, use `actions/setup-python` with `python-version: "3.14"`.

## Usage

```sh
python3 -m project_validator path/to/project
python3 -m project_validator --list
python3 -m project_validator --map path/to/project
python3 -m project_validator --facts path/to/project
python3 -m project_validator --answers path/to/project
python3 -m project_validator --only coverage,platform-matrix --format json path/to/project
```

| Option | Meaning |
|---|---|
| `--list` | list the available checks; with `--format json`, also the ecosystems each one applies to |
| `--support-matrix` | print what each check recognises for each ecosystem, as the committed [docs/support-matrix.md](docs/support-matrix.md) (markdown; JSON with `--format json`) |
| `--map` | print the detected project structure as JSON: languages, build systems, the signals that recognised each ecosystem, the file suffixes no ecosystem recognises, vendored files (other projects' code and minified bundles, which add no language), the units the project is judged in (one for most projects; each package of a monorepo and each build root of a mixed-language project), and the CI providers, jobs and toolchains |
| `--facts` | print the facts found about the project as JSON, each with where it was found: the source and build files with their languages, the settings the configuration files hold (per tool), the CI jobs (one per matrix combination), the commands and actions each runs, the commands those run in turn (package scripts, Deno tasks, Composer scripts, Make targets, pre-commit hooks), what the coverage tools CI runs measure, and what could not be read (see [docs/architecture.md](docs/architecture.md)) |
| `--answers` | print the answers to the questions about the project as JSON, per language in each unit of the project: for now, what coverage CI reports at each granularity (line, statement, region, branch, path), each `yes`, `no`, `unknown` (something that could report it was not read) or `impossible` (no known tool measures it for the language), with the tools that report it and how the known tools would |
| `--only CHECKS` / `--skip CHECKS` | comma separated check names to run / not run |
| `--format text\|json\|markdown` | output format; `markdown` is a grid of checks against the ecosystems in each unit of the project, each cell its status and the tools that ran, for a CI job summary |
| `--color auto\|always\|never` | color the text output (needs rich); `auto` colors only on a terminal when `NO_COLOR` is unset |
| `--exclude DIR` | leave `DIR`, relative to the project, out of the validation (e.g. test fixtures); may be repeated |
| `--build` | configure and build the project in a temporary directory and ask `ctest` for its tests; a build that cannot run makes whether there are tests unknown |
| `--strict` | treat warnings as failures |
| `--max-file-size MIB` | committed files larger than this belong in Git LFS or DVC (default: 5) |
| `--allow-official-tags` | let the actions GitHub publishes (`actions/`, `github/`) be pinned to tags |
| `--allow-unknown` | judge by what could be read when an answer depends on CI configuration that could not be (a provider scanned heuristically, a matrix computed by an expression, a reusable workflow in another repository). Without it, such an answer is an `ERROR`: a gap in the validator's tooling, not a finding about the project |
| `--cmake PATH` / `--ctest PATH` | the executables used by `--build` |
| `--plugin-dir DIR` | load extra checks and CI providers from `DIR/*.py` |

Exit codes: `0` everything passed, `1` a check failed or raised an error, `2` usage error.

## Checks

What each check accepts for a language is on that ecosystem's page in [docs/ecosystems](docs/ecosystems); [docs/support-matrix.md](docs/support-matrix.md) is the generated grid of every check against every ecosystem, with the tools each recognises (regenerated with `UPDATE_SNAPSHOTS=1 python -m unittest tests.test_documentation`).

| Check | Passes when |
|---|---|
| `ci-present` | at least one CI configuration is found |
| `tests-run` | each language's tests exist in each unit (a separate test project's count for all of them) and CI runs them (`ctest-runs` is accepted as an old name). Warns when CI never runs the tests |
| `fuzz-testing` | each language with a fuzzer has fuzz targets in each unit (libFuzzer, cargo-fuzz, atheris, Go fuzzing, ...) and CI runs them (a ClusterFuzzLite action, or a CTest registration that passes a libFuzzer option, counts). Warns when CI never runs the targets, when CI runs a fuzzer but no targets are recognised, or when only property-based tests exist |
| `coverage` | A coverage tool CI runs reports branch coverage, or the finest coverage any known tool can measure for the language when none measures branches. Path or MC/DC coverage is a bonus. A setting counts when CI runs the tool that reads it |
| `platform-matrix` | CI covers at least 2 operating systems, 2 toolchains (compilers, or the ecosystem's language versions) and 3 OS/toolchain combinations |
| `ci-build-types` | every OS/toolchain combination in CI builds Debug and Release, each with and without sanitizers |
| `compiler-warnings` | a strict warning set is enabled. Warns listing what is missing |
| `warnings-as-errors` | warnings fail the build, the lint or the tests |
| `cxx-extensions` | compiler extensions to the language standard are turned off, so `-std=c++NN` is used rather than `-std=gnu++NN` (for Fortran, `-std=f2018` rather than the GNU dialect) |
| `hardening` | binary hardening is enabled: exploit mitigations that the build inserts into the binary (static analysis and dependency audits are judged by `security-scanning` and `dependency-audit`). Ecosystems that build no native binary are not judged. Warns listing what is missing |
| `code-formatting` | CI enforces each language's formatting in each unit: a formatter run that fails on unformatted code, or one that rewrites it where the job fails on the change or commits it (a pre-commit hook, `git diff --exit-code`). Its style is defined (e.g. `.clang-format`) or the tool's own. Warns when the style is defined but CI does not enforce it |
| `function-limits` | function length is limited: lizard runs with a length limit (`lizard --length 30`), or one of the ecosystem's own tools limits it |
| `static-analysis` | CI runs a static analyzer on each language in each unit (and every analyzer a language requires: clang-tidy and cppcheck for C/C++), with its checks defined where it has no defaults worth running. Warns when an analyzer is configured but does not run, or runs short; fails when none runs |
| `type-checking` | CI (or a pre-commit hook CI runs) runs a static type checker on each dynamically typed language in each unit. Strict mode is a bonus; without it the result suggests it. Warns when a type checker is configured but does not run; fails when none runs. Compiled languages, whose compilers check types, are not judged |
| `mutation-testing` | CI runs a mutation testing tool on each language in each unit (mutmut, cosmic-ray, Mull, cargo-mutants, gremlins, StrykerJS, PIT, Stryker.NET, Infection, mutant, Muter); running it on a pull request's changes only is a bonus (heuristic: the mutant names are taken as the pull request's changes). Warns when a tool is configured but does not run, or when none is found |
| `action-pinning` | every action and reusable workflow CI uses from another repository is pinned to a full commit SHA (`actions/checkout@<SHA> # v4.2.2`), and every `docker://` image to a digest. Fails when one is pinned to a branch or not at all; warns when one is pinned to a tag or an abbreviated commit (`--allow-official-tags` accepts tags for `actions/` and `github/`). Skipped without GitHub Actions |
| `ci-lint` | CI (or a pre-commit hook) lints the configuration of each CI provider it uses: GitHub Actions with actionlint or zizmor, GitLab CI with `glab ci lint` or `gitlab-ci-local --preview`, CircleCI with `circleci config validate`. Warns otherwise; skipped without CI, or when no linter is known for the providers used |
| `copy-paste-detection` | CI runs a duplicate code detector (PMD CPD, jscpd, Duplo, Simian, CCFinderX or SonarQube); warns otherwise |
| `security-scanning` | CI scans each language's code in each unit for security problems: CodeQL, GitLab SAST or semgrep, or the language's security lints where CI runs them. Warns otherwise |
| `secret-scanning` | CI or a pre-commit hook runs a secret scanner: gitleaks, TruffleHog, detect-secrets, ggshield or Nosey Parker. Warns otherwise, and says so when a scanner is configured (`.gitleaks.toml`, `.secrets.baseline`, `.gitguardian.yaml`) but nothing runs it. GitHub's own secret scanning is a repository setting, which cannot be seen from a checkout |
| `dependency-management` | dependencies come from a package manager and are locked (where the ecosystem expects a lock), in each unit (a lockfile locks its directory and those below it). Passes with a note when no dependencies are declared. Warns when they are not locked, or when third-party code is committed (`third_party/`, `external/`, `extern/`, `vendor/` other than `go mod vendor` output, or git submodules) |
| `dependency-audit` | CI checks each language's dependencies in each unit against known vulnerabilities. osv-scanner, `trivy fs` and `snyk test` (and their actions) count for every ecosystem. Warns otherwise |
| `data-wellformed` | every JSON, TOML, YAML and XML file parses, including the configuration in `.github/`, `.gitlab/`, `.circleci/`, `.buildkite/`, `.devcontainer/` and `.vscode/`. JSON that tools read with comments (`*.jsonc`, `tsconfig*.json`, `jsconfig.json`, `devcontainer.json`, `.vscode/*.json`) may have comments and trailing commas; YAML tags of any tool (GitLab's `!reference`) are accepted; XML external entities are never read. Files over 5 MiB are not parsed. Fails listing each file that does not parse, with the line and column. Data files under test directories (`tests/`, `spec/`, `fixtures/`, …) are read but only reported, not judged: a parser's test data is malformed on purpose |
| `large-files` | no committed file is larger than 5 MiB (`--max-file-size`) unless Git LFS stores it (`filter=lfs` in a `.gitattributes`) or DVC tracks it (a `.dvc` file beside it). In a git checkout only the files git tracks are judged. Warns listing the largest files |
| `security-policy` | a `SECURITY.md` (or `.rst`, `.txt`, ...) at the root, in `.github/` or in `docs/` says how to report a vulnerability: an email address, a link, or the forge's private vulnerability reporting. Warns otherwise |
| `license` | a license file (`LICENSE`, `LICENSE.md`, `LICENSE-MIT`, `COPYING`, `UNLICENSE`, ... or REUSE's `LICENSES/` directory) holds a recognised license: an `SPDX-License-Identifier` line, or the standard text of AGPL, LGPL, GPL, Apache-2.0, MPL-2.0, EPL-2.0, BSL-1.0, Unlicense, CC0-1.0, MIT, BSD, ISC, 0BSD or Zlib. Warns when the license is not recognised, or when a manifest declares another one. Fails without a license file |
| `dependency-updates` | Dependabot or Renovate is configured; warns otherwise |
| `status-badges` | the README (at the root, in `.github/` or in `docs/`) shows a CI status badge of any supported CI provider (GitHub Actions `badge.svg`, GitLab pipeline, CircleCI, ... or their shields.io badges) and a quality badge (Codecov, Coveralls, SonarCloud, Codacy, Code Climate, DeepSource, Coverity Scan, OpenSSF Scorecard or Best Practices). Warns when only one kind is shown; fails when there is no README or no badge |
| `committed-artifacts` | no build output is committed. In a git checkout only the files git tracks are judged; `--exclude` keeps fixtures out. Fails listing the outputs |
| `vcs-ignore` | a `.gitignore`, `.hgignore`, `.bzrignore` or `.fossil-settings/ignore-glob` ignores the build outputs of each ecosystem in the project. Warns when an ignore file misses them |

CI detection is pluggable too. GitHub Actions workflows (including `strategy.matrix`
with `include`/`exclude`) and GitLab CI pipelines (including `parallel: matrix:`, local `include:` files, `extends:`
and `!reference`)
are parsed as YAML. A job is judged by what it runs: its commands (and the commands those run in turn), its image,
environment and actions. A GitHub step or job whose `if:` is false for a matrix combination does not run in it
(`runner.os`, `matrix.*`, `env.*` and `contains`/`startsWith`/`endsWith` are evaluated; conditions on anything else
are kept), and expressions whose values are known are evaluated the way GitHub evaluates them before a step runs.
Each build system reads the build types from its own commands (`-DCMAKE_BUILD_TYPE`, `--config`, `ctest -C`,
`meson setup --buildtype`, `cargo --release`, `swift build -c`, `xcodebuild -configuration`). Azure Pipelines,
AppVeyor, CircleCI, Travis CI, Jenkins, Buildkite, Drone, Cirrus CI, Bitbucket Pipelines and Woodpecker are detected
and scanned heuristically. pre-commit.ci is the CI of a `.pre-commit-config.yaml` with a `ci:` section: it runs the
hooks (but `ci.skip`), and builds nothing, so it is no platform or build configuration. A pre-commit hook counts only
where CI runs it (pre-commit.ci, `pre-commit run` or `pre-commit/action`). A job that names no compiler is counted with its runner's default compiler (gcc on Linux,
AppleClang on macOS, MSVC on Windows).

Known limitations:

- A GitLab `include:` from another project, a URL or a template is not read.
- A GitHub matrix computed by an expression (`fromJSON(...)`) cannot be expanded; those jobs run with their matrix
  values unknown.
- Evidence is found by scanning text, so every file under the project is considered;
  use `--exclude` to leave out test fixtures or vendored code.
- A CI job that names no compiler counts as a C/C++ build with its runner's default compiler,
  unless it only runs another ecosystem's tools (e.g. pytest, but no CMake, Meson or compiler).

## Writing a Plugin

Any module-level `Check`, `CiProvider` or `Ecosystem` in a file passed with `--plugin-dir` is picked up, and so is
any component: a `Tool` (a formatter, a coverage tool), a `SettingsReader`, a `CommandExpander` or an `Action`
(see [docs/architecture.md](docs/architecture.md)):

```python
from project_validator.ci import CiProvider
from project_validator.core import Context, Result, check

EXAMPLE_CI = CiProvider(name="Example CI", files=("example-ci.yml",))


@check(name="has-readme", description="The project has a README")
def has_readme(context: Context) -> Result:
    if context.project.exists("README.md"):
        return Result.passed("README.md found")
    return Result.failed("no README.md")
```

### Adding an ecosystem

Everything the validator knows about a language lives in its profile under `project_validator/ecosystems/`:
how it is recognised (build systems, source suffixes, how CI names its toolchain versions), the tools it uses
(formatters and coverage tools, which say how CI runs them), the settings its practices ask for, and what varies
between its CI jobs (compilers, toolchain versions). The checks are generic: each one judges every language some
component handles, and does not apply to the others. A plugin can add an ecosystem and its components the same way,
without changing the validator.

A built-in profile is found by its module or package, `project_validator/ecosystems/<name>.py` or `<name>/`; it comes
with its own `tests/layouts/<name>.py`, fixtures `tests/fixtures/well_configured_<name>` and
`tests/fixtures/bare_<name>`, and page `docs/ecosystems/<name>.md`, and no shared list names it.
`python -m project_validator.scaffold <name> <Label> <suffix>...` writes them: a package recognising the language by
its suffixes and its CI toolchain (guessed from the name, to be checked), with a module each for its tools and its
practices, and the fixtures' files that are not about the language; what is left is the language's own knowledge.

A project is recognised as an ecosystem by any of:

- `BuildSystem.files`: exact names (`build.zig`), file name patterns (`*.csproj`) or directory patterns
  ending in `/` (`*.xcodeproj/`), matched anywhere in the project;
- `source_suffixes`: suffixes only this ecosystem uses;
- `detect`: a probe that reads the project (e.g. `project.read_head(path)`) and returns the languages it found,
  for ecosystems that file names cannot show;
- `ambiguous_suffixes`: suffixes other ecosystems may share (`.h`, `.pl`), counted only once the ecosystem
  was recognised another way. A suffix mapped to `None` is accounted for without adding a language.

Registering an ecosystem that claims another one's build file or source suffix is an error.
`--map` lists the suffixes no ecosystem recognises, so the gaps are visible.


```python
from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts.axes import versions_axis
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.tools import defined_by

ZIG = Ecosystem(
    label="Zig",
    languages=frozenset({"Zig"}),
    build_systems=(BuildSystem(name="Zig build", files=("build.zig",), languages=frozenset({"Zig"})),),
    source_suffixes={".zig": "Zig"},
    # How CI names the toolchain: `zig-version: 0.13.0` to a setup action, or `setup-zig` / `zig build` without one.
    toolchain=toolchain_patterns(
        "Zig", version=r"([\d.x]+)", inputs=("zig-version",), commands=r"\bzig\s+build\b", setup=("zig",)
    ),
)
# platform-matrix: OS x Zig version.
ZIG_VERSIONS = versions_axis("Zig version", "Zig", frozenset({"Zig"}))
# code-formatting: zig fmt has one style; `zig fmt --check` fails on unformatted files, `zig fmt` rewrites them.
ZIG_FMT = format_tool(
    name="zig fmt",
    languages=frozenset({"Zig"}),
    can={Enforcement.CHECK: "zig fmt --check .", Enforcement.APPLY: "zig fmt ."},
    formats=flagged(("zig", "fmt"), checks=("--check",)),
    style=defined_by(),
)
```

`--list --format json` shows which ecosystems each check applies to, including those added by plugins.

## Development

[docs/architecture.md](docs/architecture.md) describes how the validator is put together, and what each step of its
rearchitecture changed.

```sh
python3 -W error -m unittest
```

The project validates itself; CI runs the same command:

```sh
python3 -m project_validator --strict --exclude tests/fixtures .
```

CI also appends `--format markdown` output to the job summary, a grid of every check against the ecosystems in the
project: open the latest [CI run on main](https://github.com/cpp-best-practices/project_validator/actions/workflows/ci.yml?query=branch%3Amain) to see it.

Each quality gate is its own CI job, so a pull request shows which one failed.
To run them locally:

| CI job | Command |
|---|---|
| `lint` | `ruff check .` |
| `formatting` | `ruff format --check --diff .` |
| `typing` | `mypy` |
| `copy-paste-detection` | `npx --yes jscpd@4.3.0` (settings in `.jscpd.json`) |
| `function-limits` | `lizard --length 30 --warnings_only project_validator tests` |
| `mutation testing` | `mutmut run <module>.*` for the modules a pull request changes (settings in `[tool.mutmut]`); `mutmut results` lists survivors |
| `fuzzing` | `python tests/fuzz/fuzz_<parser>.py tests/fuzz/corpus/<parser> -max_total_time=60` for each of the six parsers (atheris); locally, write new corpus entries to a temp directory first: `python tests/fuzz/fuzz_<parser>.py "$(mktemp -d)" tests/fuzz/corpus/<parser> -max_total_time=60` |

Branch coverage is measured with [coverage.py](https://coverage.readthedocs.io/)
(configured in `pyproject.toml`, which fails the report below 95%):

```sh
python3 -m pip install "coverage>=7.10"
coverage run --branch -m unittest
coverage report
```

CI uploads the coverage report to [Codecov](https://codecov.io/gh/cpp-best-practices/project_validator)
and fails if branch coverage drops below the threshold.

## Dependency Policy

The validator is meant to run anywhere a project can be built,
with as little setup as possible. To keep it that way:

- **The standard library comes first.** If something can reasonably be
  done with the Python standard library, do it that way.
- **External dependencies are allowed, but must be carefully weighed.**
  A PR that adds one must explain:
  - what problem it solves that the standard library can't reasonably solve
  - how mature it is, how well it's maintained, and its license
  - its transitive dependencies (fewer is better; pure-Python is preferred)
  - whether it can be **optional**, with the validator degrading gracefully
    (and saying so in its output) when it's missing
- **Required dependencies** are listed in `pyproject.toml` with a lower bound
  and justified in this section. **Optional dependencies** go in an
  `[project.optional-dependencies]` extra.
- Plugins (checks) must not add dependencies that the rest of the validator
  doesn't already have.

### Current Dependencies

| Dependency | Kind | Why |
|---|---|
| [PyYAML](https://pyyaml.org/) `>=6.0` | required | The standard library has no YAML parser, and CI configuration is YAML. PyYAML is mature, MIT licensed, has no dependencies, and is packaged by every major distro (`python3-yaml` on Ubuntu). It is required rather than optional because scanning CI files as text cannot tell which compiler runs on which OS, nor apply a matrix's `include`/`exclude`, so it over-counts platform combinations and can pass `platform-matrix` for a project that should fail. Without PyYAML the validator exits with an error that says how to install it. |
| [rich](https://github.com/Textualize/rich) `>=13.0` | optional (`pretty` extra) | Colored, aligned text output with a per-status summary. MIT licensed and widely used. Without it the validator prints plain text and says so. |
| [coverage.py](https://coverage.readthedocs.io/) `>=7.10` | development only (`coverage` extra) | Measures the branch coverage of the test suite; the standard library's `trace` module does not measure branches. coverage.py is the de facto Python coverage tool, Apache 2.0 licensed and has no required dependencies. The validator itself never imports it. |
| [ruff](https://docs.astral.sh/ruff/), [mypy](https://mypy-lang.org/), [lizard](https://github.com/terryyin/lizard), [jscpd](https://github.com/kucherenko/jscpd), [mutmut](https://mutmut.readthedocs.io/), [pytest](https://docs.pytest.org/), [atheris](https://github.com/google/atheris) | CI only | The lint, typing, function-limits and copy-paste-detection quality gates, the mutation-testing gate (mutmut needs pytest to run the suite) and atheris, the fuzz-testing gate. They are installed by their CI jobs and are never imported by the validator. |

PyYAML is the only required dependency.

The tools CI installs are locked with hashes: each `.github/requirements/<job>.in` names a job's tools,
and `<job>.txt` pins them and everything they depend on, by version and hash. CI installs them with
`--require-hashes`, so a tampered package fails the install. Dependabot updates both files; to change
a tool by hand, edit its `.in` file and recompile the lock with pip-tools:

```sh
cd .github/requirements
pip-compile --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url --output-file=<job>.txt <job>.in
```
