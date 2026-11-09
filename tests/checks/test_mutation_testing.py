import unittest

from project_validator.checks.mutation_testing import mutation_testing
from project_validator.core import Options, Result, Status
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.dotnet import DOTNET
from project_validator.ecosystems.go import GO
from project_validator.ecosystems.javascript import JAVASCRIPT_AND_TYPESCRIPT
from project_validator.ecosystems.jvm import JVM
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST
from tests.support import (
    FIXTURES,
    UNSTRUCTURED_CI_FILES,
    WELL_CONFIGURED,
    WELL_CONFIGURED_DOTNET,
    WELL_CONFIGURED_GO,
    WELL_CONFIGURED_JAVASCRIPT,
    WELL_CONFIGURED_JVM,
    WELL_CONFIGURED_PYTHON,
    WELL_CONFIGURED_RUST,
    ci_running,
    fixture_files,
    github_job,
    make_context,
    run_as,
)

PYTHON_HINT = "consider running mutmut run, cosmic-ray exec or mutatest in CI"
BARE_PYTHON_WITH_CI = {**fixture_files("bare_python"), **github_job("ubuntu-latest", "pytest")}


class MutationTestingTests(unittest.TestCase):
    def _run(self, files: dict[str, str], options: Options | None = None) -> Result:
        return run_as(self, mutation_testing, files, PYTHON, options=options)

    def test_applies_to_every_language_with_a_tool(self) -> None:
        self.assertIn("Python", mutation_testing.languages)
        self.assertNotIn("Fortran", mutation_testing.languages)

    def test_the_well_configured_python_project_passes(self) -> None:
        expected = Result.passed(
            "mutmut (pyproject.toml) runs",
            "consider running it on the pull request's changes only: mutmut run <module>.* for the changed modules",
        )
        self.assertEqual(self._run(WELL_CONFIGURED_PYTHON), expected)

    def test_the_well_configured_compiled_and_scripted_projects_pass(self) -> None:
        cases = (
            (C_AND_CXX, WELL_CONFIGURED, "Mull runs"),
            (
                RUST,
                WELL_CONFIGURED_RUST,
                "cargo-mutants (.cargo/mutants.toml) runs; on the pull request's changes only (bonus)",
            ),
            (GO, WELL_CONFIGURED_GO, "gremlins runs; on the pull request's changes only (bonus)"),
            (
                JAVASCRIPT_AND_TYPESCRIPT,
                WELL_CONFIGURED_JAVASCRIPT,
                "StrykerJS (stryker.config.json) runs; on the pull request's changes only (bonus)",
            ),
            (
                DOTNET,
                WELL_CONFIGURED_DOTNET,
                "Stryker.NET (stryker-config.json) runs; on the pull request's changes only (bonus)",
            ),
        )
        for ecosystem, files, message in cases:
            with self.subTest(ecosystem=ecosystem.label):
                self.assertEqual(run_as(self, mutation_testing, files, ecosystem), Result.passed(message))

    def test_pit_wired_into_verify_passes_without_the_bonus(self) -> None:
        expected = Result.passed(
            "PIT (pom.xml) runs",
            "consider running it on the pull request's changes only: pitest:scmMutationCoverage",
        )
        self.assertEqual(run_as(self, mutation_testing, WELL_CONFIGURED_JVM, JVM), expected)

    def test_an_incremental_run_passes_with_the_bonus(self) -> None:
        files = {**WELL_CONFIGURED_PYTHON, **github_job("ubuntu-latest", "mutmut run 'app.*'")}
        expected = Result.passed("mutmut (pyproject.toml) runs; on the pull request's changes only (bonus)")
        self.assertEqual(self._run(files), expected)

    def test_warns_when_nothing_runs(self) -> None:
        self.assertEqual(self._run(BARE_PYTHON_WITH_CI), Result.warned("no mutation testing runs", PYTHON_HINT))

    def test_warns_when_configured_but_not_run(self) -> None:
        pyproject = "[project]\nname='a'\n[tool.mutmut]\nsource_paths=['src']\n"
        expected = Result.warned("mutmut is configured (pyproject.toml) but does not run", PYTHON_HINT)
        self.assertEqual(self._run({**BARE_PYTHON_WITH_CI, "pyproject.toml": pyproject}), expected)

    def test_fortran_is_skipped(self) -> None:
        result = mutation_testing.run(make_context(FIXTURES / "well_configured_fortran"))
        self.assertEqual(result.status, Status.SKIP)

    def test_unknown_is_an_error_unless_allowed(self) -> None:
        for provider in UNSTRUCTURED_CI_FILES:
            with self.subTest(ci=provider):
                files = {**fixture_files("bare_python"), **ci_running(provider, "pytest")}
                self.assertEqual(self._run(files).status, Status.ERROR)
                self.assertEqual(self._run(files, Options(allow_unknown=True)).status, Status.WARN)
