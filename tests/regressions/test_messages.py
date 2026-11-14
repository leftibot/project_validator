"""Expected failures for the message bugs the corpus audit found (upstream #219, #229, #231, #234, #249, #250). Each
test asserts the correct wording; it starts passing (an "unexpected success") when the bug is fixed, and its
decorator goes."""

from __future__ import annotations

import json
import re
import unittest
from collections.abc import Mapping

from project_validator.checks.action_pinning import action_pinning
from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.cxx_extensions import cxx_extensions
from project_validator.checks.data_wellformed import data_wellformed
from project_validator.checks.function_limits import function_limits
from project_validator.checks.security_scanning import security_scanning
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.core import Check, Result, Status
from tests.support import GITHUB_WORKFLOW, github_job, github_steps, make_context, temp_project

RUNS = github_job  # a GitHub workflow with one job that runs the steps given

# actions/checkout's test.yml: a matrix of three OSes whose job uses the repository's own action, not readable here.
MATRIX_LOCAL_ACTION = {
    GITHUB_WORKFLOW: json.dumps(
        {
            "jobs": {
                "test": {
                    "runs-on": "${{ matrix.os }}",
                    "strategy": {"matrix": {"os": ["ubuntu-latest", "macos-latest", "windows-latest"]}},
                    "steps": [{"uses": "actions/checkout@v4"}, {"uses": "./"}, {"run": "shellcheck x.sh"}],
                }
            }
        }
    ),
    "x.sh": "#!/bin/sh\n",
    "src/a.py": "",
}
# A MakeMaker distribution (mojo, perl-code-tidyall, Dist-Zilla) that does not ignore Devel::Cover's cover_db.
PERL_DISTRIBUTION = {
    "Makefile.PL": "use ExtUtils::MakeMaker;\nWriteMakefile(NAME => 'Shop');\n",
    "lib/Shop.pm": "package Shop;\n1;\n",
    ".gitignore": "blib/\nMYMETA.*\n",
}
# zod's layout: workspace packages, one with JavaScript and TypeScript sources, each with a biome.jsonc CI never runs
# (with one package alone the identical results fold into one clause; with two, each language has its own).
JS_TS_WORKSPACE = {
    "package.json": '{"name": "zod", "private": true, "workspaces": ["packages/*"]}',
    "packages/mini/package.json": '{"name": "mini"}',
    "packages/mini/src/a.js": "",
    "packages/mini/src/b.ts": "",
    "packages/mini/biome.jsonc": "{}",
    "packages/core/package.json": '{"name": "core"}',
    "packages/core/src/a.ts": "",
    "packages/core/biome.jsonc": "{}",
    **RUNS("ubuntu-latest", "npx jest"),
}
LANGUAGE_PREFIX = re.compile(r"^[\w+#/ ]+?(?P<unit> in \S+)?: ")

CMAKE_TESTS = {
    "CMakeLists.txt": (
        "cmake_minimum_required(VERSION 3.21)\nproject(p LANGUAGES CXX)\ninclude(CTest)\nadd_test(NAME t COMMAND t)\n"
    ),
    "src/a.cpp": "",
}
NOTEBOOK = json.dumps({"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5})
# (name, files, what the message must say, what it must not say) for tests-run.
TESTS_RUN_WORDING = (
    ("ctest", {**CMAKE_TESTS, **RUNS("ubuntu-latest", "ctest --test-dir build")}, "ctest", ""),
    (
        "mkdocs",
        {"mkdocs.yml": "site_name: x\n", "docs/index.md": "# x\n", **RUNS("ubuntu-latest", "mkdocs build")},
        "mkdocs build",
        "tests found",
    ),
    ("jekyll", {"_config.yml": "theme: jekyll-theme-slate\n", "docs/a.md": "# a\n"}, "", "tests found"),
    ("notebook", {"analysis/a.ipynb": NOTEBOOK}, "notebook", "tests found"),
)

HELM_CHART = {
    "charts/shop/Chart.yaml": "apiVersion: v2\nname: shop\nversion: 0.1.0\n",
    "charts/shop/values.yaml": "a: 1\n",
}
TEMPLATES = {f"charts/shop/templates/{name}.yaml": "apiVersion: v1\nkind: {{ .Kind }}\n" for name in ("a", "b", "c")}
# A project whose only file of a format is test data, as the map still detects the format from.
TEST_DATA_ONLY = {
    "XML": {"tests/fixtures/a.xml": "<a/>"},
    "TOML": {"tests/invalid/a.toml": "a = [1,,]\n"},
    "Dockerfile": {"test/Dockerfile.debian": "FROM debian\n"},
    "Jupyter": {"test/ipynb/simple.ipynb": NOTEBOOK},
}

GO_MODULE = {"go.mod": "module x\n\ngo 1.22\n", "a.go": "package x\n"}
GOLANGCI = RUNS("ubuntu-latest", "golangci-lint run")
GOLANGCI_DEFAULT_NONE = {".golangci.yml": "version: '2'\nlinters:\n  default: none\n  enable:\n    - govet\n"}
JAVA = {"src/main/java/A.java": "class A {}\n"}
# spring-petclinic's Checkstyle: bound to check, with a configuration whose one module flags http:// URLs.
NOHTTP_CHECKSTYLE = {
    "pom.xml": (
        "<project><build><plugins><plugin><artifactId>maven-checkstyle-plugin</artifactId>"
        "<executions><execution><goals><goal>check</goal></goals><configuration>"
        "<configLocation>src/checkstyle/nohttp-checkstyle.xml</configLocation>"
        "</configuration></execution></executions></plugin></plugins></build></project>"
    ),
    "src/checkstyle/nohttp-checkstyle.xml": (
        '<module name="com.puppycrawl.tools.checkstyle.Checker">\n'
        '  <module name="io.spring.nohttp.checkstyle.check.NoHttpCheck"/>\n</module>\n'
    ),
    **RUNS("ubuntu-latest", "./mvnw -B verify"),
}
C_PROJECT = {"CMakeLists.txt": "cmake_minimum_required(VERSION 3.21)\nproject(p LANGUAGES C)\n", "src/a.c": ""}
# uber/h3's .clang-tidy: the threshold is an option of the disabled google- alias; the check is not enabled.
H3_CLANG_TIDY = (
    "Checks: 'clang-diagnostic-*,clang-analyzer-*'\nCheckOptions:\n"
    "  - key: google-readability-function-size.StatementThreshold\n    value: '800'\n"
)
# (name, files, the host tool the message should name) for function-limits: the rule is not enabled in any.
RULE_NOT_ENABLED = (
    (
        "eslint",
        {
            "package.json": '{"name": "x"}',
            "src/a.js": "",
            "eslint.config.js": "export default [];\n",
            **RUNS("ubuntu-latest", "npx eslint ."),
        },
        "eslint",
    ),
    (
        "golangci enable list",
        {**GO_MODULE, ".golangci.yml": "linters:\n  enable:\n    - revive\n", **GOLANGCI},
        "golangci-lint",
    ),
    (
        "golangci disable",
        {**GO_MODULE, ".golangci.yml": "linters:\n  enable-all: true\n  disable:\n    - funlen\n", **GOLANGCI},
        "golangci-lint",
    ),
    ("checkstyle", {**JAVA, **NOHTTP_CHECKSTYLE}, "Checkstyle"),
    (
        "clang-tidy -checks",
        {
            **C_PROJECT,
            **RUNS(
                "ubuntu-latest",
                "clang-tidy -checks='readability-inconsistent-declaration-parameter' src/*.c -- -std=c99",
            ),
        },
        "clang-tidy",
    ),
    (
        "clang-tidy alias option",
        {**C_PROJECT, ".clang-tidy": H3_CLANG_TIDY, **RUNS("ubuntu-latest", "run-clang-tidy -p build")},
        "clang-tidy",
    ),
)

RACKET = {"info.rkt": "#lang info\n", "main.rkt": "#lang racket\n", **RUNS("ubuntu-latest", "raco test .")}
REUSABLE_WORKFLOW = {
    GITHUB_WORKFLOW: (
        "jobs:\n  terraform-module:\n    uses: cloudposse/.github/.github/workflows/shared-terraform-module.yml@main\n"
    ),
    "main.tf": "",
}

# protovalidate's .golangci.yml: gosec enabled by enable-all, then excluded for the path every Go file is under.
GOSEC_EXCLUDED = (
    "linters:\n  enable-all: true\nissues:\n  exclude-rules:\n    - path: .\n      linters:\n        - gosec\n"
)
# (name, check, files) whose tool is claimed from a file's existence, not from the section that would enable it.
CLAIMED_FROM_A_FILE = (
    (
        "buf.yaml without lint",
        static_analysis,
        {
            "proto/a.proto": 'syntax = "proto3";\n',
            "buf.yaml": "version: v1\nbreaking:\n  use:\n    - WIRE\n",
            **RUNS("ubuntu-latest", "buf build"),
        },
    ),
    ("Checkstyle with only NoHttpCheck", static_analysis, {**JAVA, **NOHTTP_CHECKSTYLE}),
    (
        "golangci default none",
        compiler_warnings,
        {**GO_MODULE, **GOLANGCI_DEFAULT_NONE, **github_steps("uses: golangci/golangci-lint-action@v9")},
    ),
    (
        "gosec excluded for every path",
        security_scanning,
        {**GO_MODULE, ".golangci.yml": GOSEC_EXCLUDED, **GOLANGCI},
    ),
)


def _run(check: Check, files: Mapping[str, str]) -> Result:
    """The result of `check` in a throw-away project of `files`, judged strictly (unknown is an error)."""
    with temp_project(files) as root:
        return check.run(make_context(root))


def _without_language(text: str) -> str:
    """`text` without the language of its "Language in unit: " prefix, the unit kept: two languages of one ecosystem
    saying the same thing of the same unit become one text."""
    return LANGUAGE_PREFIX.sub(lambda match: f"{match['unit'] or ''}: ".lstrip(), text, count=1)


def _repeated(check: Check, files: Mapping[str, str]) -> list[str]:
    """The clauses and details of `check` in `files` that are said more than once (the language left aside)."""
    result = _run(check, files)
    texts = [_without_language(text) for text in (*result.message.split("; "), *result.details)]
    return sorted({text for text in texts if texts.count(text) > 1})


class RepeatedDetailTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #219: one unread subject or clause is repeated per OS, per language
    def test_each_unread_subject_and_each_clause_is_said_once(self) -> None:
        """An unread local action is one detail line, not one per matrix OS (actions/checkout, build-push-action); a
        distribution's unignored cover_db is one clause (mojo, perl-code-tidyall); a unit's clause is said once for
        the JavaScript/TypeScript ecosystem, not per language (zod, axios)."""
        cases = (
            ("matrix OS", static_analysis, MATRIX_LOCAL_ACTION),
            ("Perl distribution", vcs_ignore, PERL_DISTRIBUTION),
            ("JavaScript and TypeScript", code_formatting, JS_TS_WORKSPACE),
        )
        for name, check, files in cases:
            with self.subTest(name):
                self.assertEqual(_repeated(check, files), [])


class TestsRunWordingTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #229: a passing tests-run part says only "tests found in N file(s)"
    def test_the_message_says_what_was_found_and_that_ci_runs_it(self) -> None:
        """A pass names the runner CI uses (fmt, googletest: ctest; terraform-aws-eks: mkdocs build); a site's
        configuration (monolog, kubespray: a one-line _config.yml) and notebooks (fivethirtyeight/data) are not
        "tests found in N file(s)"."""
        for name, files, says, never_says in TESTS_RUN_WORDING:
            with self.subTest(name):
                message = _run(tests_run, files).message
                if says:
                    self.assertIn(says, message)
                if never_says:
                    self.assertNotIn(never_says, message)


class DataWellformedSummaryTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #231: every template is a detail line; "no X file" contradicts the map
    def test_a_pass_summarises_and_agrees_with_the_detection(self) -> None:
        """A chart's templates are counted, not listed one per line (prometheus-community/helm-charts: 577 lines);
        a format detected from test data alone is not "no XML file to parse" (community.general, Open-XML-SDK,
        pgaudit, pandoc)."""
        with self.subTest("templates"):
            details = _run(data_wellformed, {**HELM_CHART, **TEMPLATES}).details
            listed = [detail for detail in details if any(path in detail for path in TEMPLATES)]
            self.assertEqual(listed, [])
        for format_, files in TEST_DATA_ONLY.items():
            with self.subTest(format_):
                message = _run(data_wellformed, {**files, "src/a.py": ""}).message
                self.assertNotIn(f"no {format_} file to parse", message)


class FunctionLimitsWordingTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #234: "CI runs X's rule, but without a limit" when the rule is off
    def test_a_rule_that_is_not_enabled_is_not_said_to_run(self) -> None:
        """When the host tool runs without the length rule (checkout's eslint, cli/cli's and protovalidate's
        golangci-lint, petclinic's Checkstyle, data.table's and h3's clang-tidy), the message names the tool and says
        the rule is not enabled, instead of "CI runs <tool>'s <rule>, but without a function length limit"."""
        for name, files, host in RULE_NOT_ENABLED:
            with self.subTest(name):
                result = _run(function_limits, files)
                self.assertEqual(result.status, Status.FAIL, result)
                self.assertIn(host, result.message)
                self.assertNotRegex(result.message, r"CI runs .+, but without a function length limit")


class SmallMessageTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #250: example value printed, empty raco fmt hint, workflows as actions
    def test_the_fact_found_the_hint_and_the_kind_of_reference_are_right(self) -> None:
        """cxx-extensions prints the c_std found (dbus-broker: c11), not the requirement's example; the raco fmt hint
        names a command (every Racket repo); a job-level `uses:` is a reusable workflow, not an action
        (terraform-null-label)."""
        with self.subTest("c_std"):
            meson = {"meson.build": "project('x', 'c', default_options: ['c_std=c11'])\n", "a.c": ""}
            self.assertIn("c_std=c11", _run(cxx_extensions, meson).message)
        with self.subTest("raco fmt"):
            hints = [detail for detail in _run(code_formatting, RACKET).details if detail.startswith("consider")]
            self.assertTrue(hints and "raco fmt" in hints[0], hints)
        with self.subTest("reusable workflow"):
            self.assertIn("reusable workflow", _run(action_pinning, REUSABLE_WORKFLOW).message)


class ConfiguredClaimTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #249: a tool is "configured" or passes from a file's existence alone
    def test_a_tool_is_credited_only_when_its_section_enables_it(self) -> None:
        """buf lint is not "configured" by a buf.yaml with only `breaking:` (opentelemetry-proto); Checkstyle with only
        NoHttpCheck is no static analysis (spring-petclinic); staticcheck is not enabled under `default: none`
        (cli/cli); gosec excluded for every path scans nothing (protovalidate)."""
        for name, check, files in CLAIMED_FROM_A_FILE:
            with self.subTest(name):
                result = _run(check, files)
                self.assertNotEqual(result.status, Status.PASS, result)
                self.assertNotIn("is configured", result.message)
