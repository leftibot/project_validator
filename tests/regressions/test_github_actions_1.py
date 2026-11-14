"""Expected failures for GitHub Actions (and GitLab CI) reading bugs the corpus audit found (upstream #209 to #215).
Each test asserts the correct behaviour; it starts passing (an "unexpected success") when the bug is fixed, and its
decorator goes."""

from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
from types import MappingProxyType

from project_validator.checks.action_pinning import action_pinning
from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.link_check import link_check
from project_validator.checks.sanitizers import sanitizers
from project_validator.checks.tests_run import tests_run
from project_validator.ci.github_expressions import Known, rendered
from project_validator.core import Check, Result, Status
from project_validator.facts import CiJob, Command, Unknown
from project_validator.questions.pinning import pinning
from tests.support import GITHUB_WORKFLOW, ci_jobs, make_context, temp_project

type Job = Mapping[str, object]

NOTHING: Mapping[str, object] = MappingProxyType({})
CALLED = ".github/workflows/w.yml"
CALLED_WORKFLOW = (
    "on: workflow_call\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: swift test\n"
)
COMPOSITE = "runs:\n  using: composite\n  steps:\n    - run: {}\n      shell: bash\n"
NODE_ACTION = "runs:\n  using: node24\n  main: index.js\n"
# The targets of same-repository references: a composite action and a reusable workflow.
LOCAL_TARGETS = {".github/actions/x/action.yml": COMPOSITE.format("echo hi"), CALLED: CALLED_WORKFLOW}
GIT_CONFIG = (
    '[remote "origin"]\n\turl = https://github.com/me/repo.git\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n'
)
UBUNTU = "ubuntu-latest"

# A caller job's matrix and `with:`, the called workflow's job, the inputs it declares, and the OSes its jobs run on.
INPUT_VARIANTS: tuple[tuple[str, Job, Job, Job, list[str]], ...] = (
    (  # googletest: `with: os:` per matrix entry; `container:` whose image is empty off linux
        "google/googletest",
        {"strategy": {"matrix": {"os": [UBUNTU, "macos-latest"]}}, "with": {"os": "${{ matrix.os }}"}},
        {"runs-on": "${{ inputs.os }}", "container": {"image": ""}, "steps": [{"run": "cmake -B b"}]},
        {},
        ["linux", "macos"],
    ),
    (  # poetry: a nested matrix object's field passed as an input
        "python-poetry/poetry",
        {"strategy": {"matrix": {"os": [{"image": "windows-latest"}]}}, "with": {"runner": "${{ matrix.os.image }}"}},
        {"runs-on": "${{ inputs.runner }}", "steps": []},
        {},
        ["windows"],
    ),
    (  # devenv: a JSON list of runner labels passed through fromJSON
        "cachix/devenv",
        {
            "strategy": {
                "matrix": {"include": [{"system": "x86_64-linux", "runs-on": '["self-hosted", "linux", "X64"]'}]}
            },
            "with": {"runs-on": "${{ matrix.runs-on }}"},
        },
        {"runs-on": "${{ fromJSON(inputs.runs-on) }}", "steps": []},
        {},
        ["linux"],
    ),
    (  # grafana/helm-charts: no `with:`, so the declared default applies
        "grafana/helm-charts",
        {},
        {"runs-on": "${{ inputs.runner }}", "steps": []},
        {"runner": {"type": "string", "default": "macos-latest"}},
        ["macos"],
    ),
)
# Homebrew's cask audit: an include-only matrix whose macOS entry has no container.
BREW_AUDIT: Job = {
    "runs-on": "${{ matrix.runs-on }}",
    "container": {"image": "${{ matrix.container }}"},
    "strategy": {
        "matrix": {"include": [{"runs-on": UBUNTU, "container": "ghcr.io/homebrew/brew:main"}, {"runs-on": "macos-26"}]}
    },
    "steps": [],
}

# felangel/bloc: a composite action run in each package of a matrix computed by an expression.
DART_PACKAGE_ACTION = (
    "inputs:\n  working_directory:\n    default: .\nruns:\n  using: composite\n  steps:\n"
    "    - run: dart test --coverage=coverage\n      shell: bash\n"
    "      working-directory: ${{ inputs.working_directory }}\n"
)
BLOC_JOB: Job = {
    "runs-on": UBUNTU,
    "strategy": {"matrix": {"package": "${{ fromJSON(needs.changes.outputs.packages) }}"}},
    "steps": [{"uses": "./.github/actions/pkg", "with": {"working_directory": "packages/${{ matrix.package }}"}}],
}
BLOC = {
    ".github/actions/pkg/action.yml": DART_PACKAGE_ACTION,
    "packages/a/pubspec.yaml": "name: a\n",
    "packages/a/lib/a.dart": "",
    "packages/a/test/a_test.dart": "import 'package:test/test.dart';\nvoid main() { test('x', () {}); }\n",
}

# An expression, the matrix combination it is rendered in, and the text GitHub puts in its place.
RENDERED: tuple[tuple[str, Mapping[str, object], str], ...] = (
    ("matrix.a || 'x'", {"a": 1.2}, "1.2"),  # mkdocs: hatch run +py=${{ matrix.py || matrix.python-version }}
    ("matrix.os || 'ubuntu-latest'", {"os": "windows-latest"}, "windows-latest"),  # flask's runs-on
    ("matrix.os || 'ubuntu-latest'", {}, UBUNTU),
    ("matrix.sanitizers && '-fsanitize=address,undefined' || ''", {"sanitizers": True}, "-fsanitize=address,undefined"),
    ("matrix.sanitizers && '-fsanitize=address,undefined' || ''", {}, ""),  # fmt's CXXFLAGS
    ("matrix.gen && '-G' || ''", {"gen": "Ninja"}, "-G"),  # fmt's cmake line
    ("(matrix.language == 'swift' && 'macos-latest') || 'ubuntu-latest'", {"language": "swift"}, "macos-latest"),
)
FLASK_TESTS: Job = {
    "runs-on": "${{ matrix.os || 'ubuntu-latest' }}",
    "strategy": {"matrix": {"include": [{"os": "windows-latest"}, {"python": "3.14"}]}},
    "steps": [],
}
FMT_LINUX: Job = {
    "runs-on": UBUNTU,
    "strategy": {"matrix": {"include": [{"cxx": "g++-14", "sanitizers": True}, {"cxx": "clang++-20"}]}},
    "steps": [
        {
            "env": {"CXXFLAGS": "${{ matrix.sanitizers && '-fsanitize=address,undefined' || '' }}"},
            "run": "cmake -B build\ncmake --build build",
        }
    ],
}
FMT = {"CMakeLists.txt": "cmake_minimum_required(VERSION 3.21)\nproject(p LANGUAGES CXX)\n", "src/a.cpp": ""}

SPHINX = {"docs/conf.py": 'project = "Shop"\nextensions = []\n', "docs/index.rst": "Shop\n====\n"}
LINKCHECK_ADVISORY: Job = {"runs-on": UBUNTU, "steps": [{"run": "make linkcheck", "continue-on-error": True}]}
CLANG_FORMAT = {
    ".clang-format": "BasedOnStyle: LLVM\n",
    "src/a.cpp": "",
    "CMakeLists.txt": "project(p LANGUAGES CXX)\n",
}
STYLE_ADVISORY: Job = {"script": ["clang-format --dry-run -Werror src/a.cpp"], "allow_failure": True}


def _workflow(**jobs: object) -> str:
    return json.dumps({"jobs": jobs})


def _calling(caller: Job, callee: Job, inputs: Job = NOTHING) -> dict[str, str]:
    """ci.yml whose job `m` calls the local reusable workflow w.yml with `caller`'s matrix and `with:`; w.yml declares
    `inputs` and has the one job `callee`."""
    called = {"on": {"workflow_call": {"inputs": inputs}}, "jobs": {"build": callee}}
    return {GITHUB_WORKFLOW: _workflow(m={"uses": f"./{CALLED}", **caller}), CALLED: json.dumps(called)}


def _npm_test_in(directory: str, level: str) -> dict[str, str]:
    """A workflow running `npm test` with `defaults.run.working-directory: <directory>` at the workflow or job level,
    and the package.json there (none at the root)."""
    job: dict[str, object] = {"runs-on": UBUNTU, "steps": [{"run": "npm test"}]}
    document: dict[str, object] = {"jobs": {"build": job}}
    (document if level == "workflow" else job)["defaults"] = {"run": {"working-directory": directory}}
    return {
        GITHUB_WORKFLOW: json.dumps(document),
        f"{directory}/package.json": json.dumps({"scripts": {"test": "node t.js"}}),
    }


def _facts(files: Mapping[str, str]) -> tuple[list[tuple[tuple[str, ...], str | None]], list[str], list[str]]:
    """What a project of `files` shows: its commands (argv, directory), its unknowns' subjects, and its jobs' OSes."""
    with temp_project(files) as root:
        facts = make_context(root).facts
    commands = [(command.argv, command.directory) for command in facts.of(Command)]
    return commands, [unknown.subject for unknown in facts.of(Unknown)], [job.os for job in facts.of(CiJob)]


def _oses(files: Mapping[str, str]) -> list[str]:
    return sorted(job.os for job in ci_jobs(files))


def _run(check: Check, files: Mapping[str, str]) -> Result:
    """The result of `check` in a throw-away project of `files`, judged strictly (unknown is an error)."""
    with temp_project(files) as root:
        return check.run(make_context(root))


class SameRepositoryReferenceTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #209: `$/` same-repository references are reported "not pinned"
    def test_references_with_the_dollar_prefix_have_nothing_to_pin(self) -> None:
        """`$/.github/actions/x` and `$/.github/workflows/w.yml` run at the triggering commit, like `./`: they are no
        references to pin, so a workflow with only them passes (junit5, koreader, pytest, poetry, vite, rspec)."""
        action = _workflow(build={"runs-on": UBUNTU, "steps": [{"uses": "$/.github/actions/x"}]})
        workflow = _workflow(call={"uses": f"$/{CALLED}"})
        for uses, ci in (("$/.github/actions/x", action), (f"$/{CALLED}", workflow)):
            with self.subTest(uses=uses):
                self.assertIsNone(pinning(uses))
                result = _run(action_pinning, {GITHUB_WORKFLOW: ci, **LOCAL_TARGETS})
                self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #210: `uses: ./` looks for "/action.yml": the root action is never read
    def test_the_repositorys_own_action_is_read(self) -> None:
        """`uses: ./` runs the root action.yml: a composite action's steps are the job's commands and a JavaScript
        action has nothing to read; neither is unknown (actions/checkout, lychee-action, pre-commit/action)."""
        workflow = {GITHUB_WORKFLOW: _workflow(test={"runs-on": UBUNTU, "steps": [{"uses": "./"}]})}
        for action, commands in ((COMPOSITE.format("shellcheck x.sh"), {("shellcheck", "x.sh")}), (NODE_ACTION, set())):
            with self.subTest(using=action.splitlines()[1].strip()):
                found, unknowns, _ = _facts({**workflow, "action.yml": action})
                self.assertEqual(unknowns, [])
                self.assertLessEqual(commands, {argv for argv, _ in found})

    @unittest.expectedFailure  # upstream #212: own workflow referenced by full name owner/repo/...@ref is not read
    def test_a_same_repository_workflow_referenced_by_its_full_name_is_read(self) -> None:
        """`uses: me/repo/.github/workflows/w.yml@main` names a file of this checkout, whose origin is me/repo: it is
        read like `./.github/workflows/w.yml` (swift-nio, ruff, dune)."""
        caller = _workflow(ci={"uses": f"me/repo/{CALLED}@main"})
        commands, unknowns, oses = _facts({GITHUB_WORKFLOW: caller, CALLED: CALLED_WORKFLOW, ".git/config": GIT_CONFIG})
        self.assertEqual(unknowns, [])
        self.assertEqual(oses, ["linux"])
        self.assertIn(("swift", "test"), [argv for argv, _ in commands])


class CalledWorkflowInputTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #211: a called workflow's inputs.* and an empty container: are misread
    def test_inputs_come_from_the_caller_and_an_empty_container_is_none(self) -> None:
        """`inputs.*` take the caller's `with:` values, per matrix combination, or the declared defaults; `container:`
        means linux only when its image is not empty (googletest, poetry, devenv, grafana/helm-charts, Homebrew)."""
        for project, caller, callee, inputs, expected in INPUT_VARIANTS:
            with self.subTest(project=project):
                self.assertEqual(_oses(_calling(caller, callee, inputs)), expected)
        with self.subTest(project="Homebrew/brew"):
            self.assertEqual(_oses({GITHUB_WORKFLOW: _workflow(audit=BREW_AUDIT)}), ["linux", "macos"])


class WorkingDirectoryTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #213: defaults.run.working-directory ignored; composite directory unexpanded
    def test_the_default_working_directory_and_a_composite_actions_directory_input_apply(self) -> None:
        """A workflow's or job's `defaults.run.working-directory` resolves `npm test` against sub/package.json
        (CycloneDX/specification, devenv); a composite action run in `packages/${{ matrix.package }}` of a computed
        matrix does not make a package definitely untested (felangel/bloc)."""
        for level in ("workflow", "job"):
            with self.subTest(level=level):
                commands, unknowns, _ = _facts(_npm_test_in("sub", level))
                self.assertEqual(unknowns, [])
                self.assertIn((("node", "t.js"), "sub"), commands)
        with self.subTest(project="felangel/bloc"):
            result = _run(tests_run, {GITHUB_WORKFLOW: _workflow(test=BLOC_JOB), **BLOC})
            self.assertNotIn(result.status, (Status.WARN, Status.FAIL), result)


class ExpressionOperandTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #214: && and || render as booleans, not as the deciding operand
    def test_and_and_or_yield_the_deciding_operand(self) -> None:
        """GitHub's `a && b` is `b` when `a` is truthy, and `a || b` is `a` or else `b`: a ternary renders its branch,
        a `runs-on` fallback picks the OS, and the sanitizer flags reach cmake (fmt, mkdocs, flask, vapor)."""
        for expression, matrix, expected in RENDERED:
            with self.subTest(expression=expression, matrix=dict(matrix)):
                self.assertEqual(rendered(expression, Known(os="linux", matrix=matrix, env={})), expected)
        with self.subTest(project="pallets/flask"):
            self.assertEqual(_oses({GITHUB_WORKFLOW: _workflow(tests=FLASK_TESTS)}), ["linux", "windows"])
        with self.subTest(project="fmtlib/fmt"):
            result = _run(sanitizers, {GITHUB_WORKFLOW: _workflow(linux=FMT_LINUX), **FMT})
            self.assertEqual(result.status, Status.PASS, result)


class AdvisoryStepTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #215: continue-on-error / allow_failure steps are credited as gates
    def test_a_step_that_cannot_fail_the_pipeline_is_no_gate(self) -> None:
        """A step with `continue-on-error: true` (GitHub) or a job with `allow_failure: true` (GitLab) never fails the
        pipeline: link-check warns and code-formatting does not pass on it alone (python/devguide, GNOME/glib)."""
        with self.subTest(provider="GitHub Actions"):
            result = _run(link_check, {**SPHINX, GITHUB_WORKFLOW: _workflow(docs=LINKCHECK_ADVISORY)})
            self.assertEqual(result.status, Status.WARN, result)
        with self.subTest(provider="GitLab CI"):
            result = _run(code_formatting, {**CLANG_FORMAT, ".gitlab-ci.yml": json.dumps({"style": STYLE_ADVISORY})})
            self.assertNotEqual(result.status, Status.PASS, result)
