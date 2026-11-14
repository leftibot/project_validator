"""Expected failures for GitHub Actions reading bugs the corpus audit found (upstream #216 to #218, #220 to #222).
Each test asserts the correct behaviour; it starts passing (an "unexpected success") when the bug is fixed, and its
decorator goes."""

from __future__ import annotations

import json
import unittest
from collections.abc import Mapping

from project_validator.checks.action_pinning import action_pinning
from project_validator.checks.ci_lint import ci_lint
from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.core import Check, Result, Status
from tests.support import GITHUB_WORKFLOW, ci_jobs, make_context, temp_project

SHA = "17d859ba0a6af9ffcaac5c70608fed36ed33e32a"
LINUX = "ubuntu-latest"
SETUP_JAVA = "actions/setup-java@v4"
PYTHON_PROJECT = {"pyproject.toml": "[project]\nname = 'x'\n", "x.py": ""}
RUFF_HOOKS = (
    "repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.12.0\n"
    "    hooks:\n      - id: ruff-format\n      - id: ruff\n"
)
PRE_COMMIT_CI_BADGE = (
    "# x\n\n[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/o/r/main.svg)]"
    "(https://results.pre-commit.ci/latest/github/o/r/main)\n"
)


def _workflow(jobs: Mapping[str, object], path: str = GITHUB_WORKFLOW, **top: object) -> dict[str, str]:
    """A workflow at `path` of `jobs` (each its mapping), with `top`-level keys (`env`)."""
    return {path: json.dumps({"jobs": jobs, **top})}


def _job(
    *steps: Mapping[str, object],
    runs_on: str = LINUX,
    name: str | None = None,
    matrix: Mapping[str, list[object]] | None = None,
) -> dict[str, object]:
    """A job running `steps` on `runs_on`, with a `name` and a `matrix` when given."""
    job: dict[str, object] = {"runs-on": runs_on, "steps": list(steps)}
    if name is not None:
        job["name"] = name
    if matrix is not None:
        job["strategy"] = {"matrix": dict(matrix)}
    return job


def _setup(action: str, inputs: Mapping[str, str]) -> dict[str, object]:
    return {"uses": action, "with": dict(inputs)}


def _versioned_jobs(action: str, name: str, run: str, *versions: str | None) -> dict[str, object]:
    """One job per version, each setting up `action` with `name: version` (none when None) and running `run`."""
    return {
        f"j{index}": _job(*([_setup(action, {name: version})] if version else []), {"run": run})
        for index, version in enumerate(versions)
    }


def _versions(files: Mapping[str, str], language: str) -> set[str]:
    """The versions of `language`'s toolchain the CI jobs of `files` run with, over every job."""
    return {found.version for job in ci_jobs(files) for found in job.toolchains if found.language == language}


def _labels(files: Mapping[str, str]) -> set[str]:
    """Every toolchain (`Rust 9.14.1`) and compiler (`gcc`) the CI jobs of `files` are seen running."""
    jobs = ci_jobs(files)
    return {str(found) for job in jobs for found in job.toolchains} | {name for job in jobs for name in job.compilers}


def _run(check: Check, files: Mapping[str, str]) -> Result:
    """The result of `check` in a throw-away project of `files`, judged strictly (unknown is an error)."""
    with temp_project(files) as root:
        return check.run(make_context(root))


# Label -> (files, toolchain language, the version sets a correct reading may give).
SETUP_INPUTS: dict[str, tuple[dict[str, str], str, tuple[set[str], ...]]] = {
    "setup-dotnet with a dotnet-version block scalar": (
        _workflow({"b": _job(_setup("actions/setup-dotnet@v4", {"dotnet-version": "8.0.x\n9.0.x\n"}))}),
        ".NET SDK",
        ({"8.0.x", "9.0.x"},),
    ),
    "setup-java with a java-version block scalar": (
        _workflow({"b": _job(_setup(SETUP_JAVA, {"java-version": "11\n17\n21\n", "distribution": "temurin"}))}),
        "JDK",
        ({"11", "17", "21"},),
    ),
    "setup-node reading node-version-file: .tool-versions": (
        {
            **_workflow({"b": _job(_setup("actions/setup-node@v4", {"node-version-file": ".tool-versions"}))}),
            ".tool-versions": "nodejs 24.18.0\n",
        },
        "JavaScript runtime",
        ({"24.18.0"}, {"24"}),
    ),
    "pnpm/setup with runtime: node@<matrix version>": (
        _workflow(
            {
                "b": _job(
                    _setup("pnpm/setup@v3", {"runtime": "node@${{ matrix.node_version }}"}),
                    matrix={"node_version": [20, 22]},
                )
            }
        ),
        "JavaScript runtime",
        ({"20", "22"},),
    ),
}

# Label -> (files, a toolchain or compiler no job of the files runs).
FREE_TEXT_MATCHES: dict[str, tuple[dict[str, str], str]] = {
    "hledger: a cache key naming the GHC version": (
        _workflow(
            {"b": _job(_setup("actions/cache@v6", {"key": "${{ runner.os }}-hx-toolchain-${{ env.ghc }}"}))},
            env={"ghc": "9.14.1"},
        ),
        "Rust 9.14.1",
    ),
    "pydantic: the commit SHA of a check-python-version action": (
        _workflow({"b": _job({"uses": f"samuelcolvin/check-python-version@{SHA}"})}),
        "Python 17",
    ),
    "cowboy: setup-beam's 'latest' spec otp-version: '> 0'": (
        _workflow({"b": _job(_setup("erlef/setup-beam@v1", {"otp-version": "> 0"}), {"run": "make tests"})}),
        "BEAM OTP 0",
    ),
    "tinymist: a cross-linker variable is not a Nix system": (
        _workflow(
            {"b": _job({"run": "cargo test"}, runs_on="windows-latest")},
            env={"CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER": "aarch64-linux-gnu-gcc"},
        ),
        "Nix aarch64-linux",
    ),
    "tinymist: a cross-linker variable is not a gcc compiler": (
        _workflow(
            {"b": _job({"run": "cargo test"}, runs_on="windows-latest")},
            env={"CARGO_TARGET_ARM_UNKNOWN_LINUX_GNUEABIHF_LINKER": "arm-linux-gnueabihf-gcc"},
        ),
        "gcc",
    ),
    "ripgrep, bat: a cross-compiler package is not a Nix system": (
        _workflow({"b": _job({"run": "sudo apt-get -y install gcc-aarch64-linux-gnu"}, {"run": "cargo test"})}),
        "Nix aarch64-linux",
    ),
}
ECTO_TAG = _workflow(
    {
        "b": _job(
            {"run": "earthly -P --ci --build-arg ELIXIR_BASE=${{ matrix.elixirbase }} +integration-test"},
            matrix={"elixirbase": ["1.17.3-erlang-27.1-alpine-3.17.9"]},
        )
    }
)

# Label -> a workflow whose job names GitHub would render on one line without `${{ ... }}`.
RENDERED_NAMES: dict[str, dict[str, str]] = {
    "serde: a ternary on the matrix OS": _workflow(
        {
            "b": _job(
                {"run": "cargo test"},
                runs_on="${{ matrix.os }}-latest",
                name="Rust nightly${{matrix.os == 'windows' && ' (windows)' || ''}}",
                matrix={"os": ["ubuntu", "windows"]},
            )
        }
    ),
    "prettier: a ternary on an absent matrix key": _workflow(
        {
            "b": _job(
                {"run": "yarn test"},
                name="${{ matrix.FULL_TEST && '[Full Test] ' || '' }} Node.js ${{ matrix.node }}",
                matrix={"node": [24, 26]},
            )
        }
    ),
    "sinatra: a block scalar name": _workflow(
        {
            "b": _job(
                {"run": "bundle exec rake"},
                name="${{ matrix.ruby }}\n(Rack stable, Puma stable)\n",
                matrix={"ruby": ["3.3", "3.4"]},
            )
        }
    ),
}
MAGIT_USES_BLOCK = _workflow({"compile": {"uses": "emacscollective/workflows/.github/workflows/compile.yml@main\n"}})

PRE_COMMIT_RUNNERS: dict[str, dict[str, str]] = {
    "pre-commit.ci known by its README badge, no ci: section": {
        **PYTHON_PROJECT,
        ".pre-commit-config.yaml": RUFF_HOOKS,
        "README.md": PRE_COMMIT_CI_BADGE,
    },
    "j178/prek-action runs the hooks": {
        **PYTHON_PROJECT,
        ".pre-commit-config.yaml": RUFF_HOOKS,
        **_workflow({"lint": _job({"uses": f"j178/prek-action@{SHA}"})}),
    },
}

# Label -> (project files, the jobs of its workflow, the version count the platform-matrix message must give).
VERSION_COUNTS: dict[str, tuple[dict[str, str], dict[str, object], str]] = {
    "devguide: 3 and 3.x are one CPython": (
        PYTHON_PROJECT,
        _versioned_jobs("actions/setup-python@v5", "python-version", "python -m pytest", "3", "3.x"),
        "1 Python version(s)",
    ),
    "flask: an unpinned job adds no Python version": (
        PYTHON_PROJECT,
        _versioned_jobs("actions/setup-python@v5", "python-version", "python -m pytest", "3.12", None),
        "1 Python version(s)",
    ),
    "flask: 3.14t is the free-threaded build, not 3.14": (
        PYTHON_PROJECT,
        _versioned_jobs("actions/setup-python@v5", "python-version", "python -m pytest", "3.14", "3.14t"),
        "2 Python version(s) (3.14, 3.14t)",
    ),
    "golangci-lint: 1.27 and 1.27.0 are one Go": (
        {"go.mod": "module x\n\ngo 1.27\n", "x.go": "package x\n"},
        _versioned_jobs("actions/setup-go@v5", "go-version", "go test ./...", "1.27", "1.27.0"),
        "1 Go version(s)",
    ),
    "caddy: ~1.27 and ~1.27.0 are one Go": (
        {"go.mod": "module x\n\ngo 1.27\n", "x.go": "package x\n"},
        _versioned_jobs("actions/setup-go@v5", "go-version", "go test ./...", "~1.27", "~1.27.0"),
        "1 Go version(s)",
    ),
    "Penlight: a job choosing no Lua adds no Lua version": (
        {"x-dev-1.rockspec": "", "src/x.lua": ""},
        _versioned_jobs("leafo/gh-actions-lua@v11", "luaVersion", "busted", "5.4", None),
        "1 Lua version(s)",
    ),
    "metals: a job naming no JDK adds no JDK version": (
        {"pom.xml": "<project/>", "src/main/java/A.java": ""},
        _versioned_jobs(SETUP_JAVA, "java-version", "mvn test", "17", None),
        "1 JDK version(s)",
    ),
}


class SetupActionVersionInputTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #216: block-scalar version lists, version files, pnpm runtime not read
    def test_every_version_a_setup_action_installs_is_a_toolchain(self) -> None:
        """setup-dotnet and setup-java install every version of a multi-line `*-version: |` (FluentValidation,
        Open-XML-SDK, guava, okhttp); setup-node reads `node-version-file: .tool-versions` (action-gh-release);
        pnpm/setup's `runtime: node@<v>` names the runtime (vite)."""
        for label, (files, language, acceptable) in SETUP_INPUTS.items():
            with self.subTest(label):
                self.assertIn(_versions(files, language), acceptable)


class CiLintUnknownTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #217: an unread reusable workflow makes ci-lint WARN, not ERROR
    def test_an_unread_reusable_workflow_leaves_ci_lint_unknown(self) -> None:
        """docker/build-push-action and opentelemetry-proto: zizmor.yml's only job calls another repository's reusable
        workflow, which is not read; whether CI lints its workflows is unknown, an ERROR without --allow-unknown."""
        files = _workflow(
            {"zizmor": {"uses": f"org/shared/.github/workflows/zizmor.yml@{SHA}"}}, path=".github/workflows/zizmor.yml"
        )
        result = _run(ci_lint, files)
        self.assertEqual(result.status, Status.ERROR, result)


class ToolchainFreeTextTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #218: toolchain patterns match cache keys, SHAs, linker names, '> 0'
    def test_toolchain_patterns_do_not_match_free_text(self) -> None:
        """A toolchain is read from a setup action's inputs or an install command, not from any text of the job:
        hledger has no Rust, pydantic no Python 17, cowboy no OTP 0, tinymist/ripgrep/bat no Nix system or gcc; ecto's
        hexpm/elixir tag names Elixir 1.17.3 beside OTP 27.1, or nothing."""
        for label, (files, unwanted) in FREE_TEXT_MATCHES.items():
            with self.subTest(label):
                self.assertNotIn(unwanted, _labels(files))
        with self.subTest("ecto: a hexpm/elixir tag keeps its Elixir version"):
            labels = _labels(ECTO_TAG)
            if "BEAM OTP 27.1" in labels:
                self.assertIn("BEAM Elixir 1.17.3", labels)


class JobNameRenderingTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #220: job names keep ${{ }} ternaries and newlines; uses: | keeps newline
    def test_job_and_action_names_are_rendered_as_github_shows_them(self) -> None:
        """Job names evaluate (or elide) `${{ a && 'b' || '' }}` with absent matrix keys empty (serde, prettier) and
        fold a block scalar to one line (sinatra); a `uses: |` block loses its trailing newline (magit)."""
        for label, files in RENDERED_NAMES.items():
            with self.subTest(label):
                for name in (job.name for job in ci_jobs(files)):
                    self.assertNotIn("${{", name)
                    self.assertNotIn("\n", name)
        with self.subTest("magit: uses: | block scalar"):
            for detail in _run(action_pinning, MAGIT_USES_BLOCK).details:
                self.assertNotIn("\n", detail)


class PreCommitRunnerTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #221: pre-commit.ci needs a ci: section; prek-action is not a runner
    def test_pre_commit_ci_by_badge_and_prek_action_run_the_hooks(self) -> None:
        """pytest and pre-commit run their hooks on pre-commit.ci with no `ci:` section (the README badge shows it);
        Bash-it runs them with j178/prek-action: the ruff-format hook enforces formatting in both."""
        for label, files in PRE_COMMIT_RUNNERS.items():
            with self.subTest(label):
                result = _run(code_formatting, files)
                self.assertEqual(result.status, Status.PASS, result)


class ToolchainVersionCountingTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #222: "default" counted as a version; 3 vs 3.x, 1.27 vs 1.27.0 twice
    def test_versions_are_normalised_and_unpinned_jobs_not_counted(self) -> None:
        """One version spelled two ways (3/3.x, 1.27/1.27.0, ~1.27/~1.27.0) counts once (devguide, golangci-lint,
        caddy); a job pinning no version adds none (flask, Penlight, metals); 3.14t stays distinct from 3.14."""
        for label, (project, jobs, expected) in VERSION_COUNTS.items():
            with self.subTest(label):
                result = _run(platform_matrix, {**project, **_workflow(jobs)})
                self.assertIn(expected, result.message)
