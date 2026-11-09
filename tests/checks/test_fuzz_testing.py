import unittest

from project_validator.checks.fuzz_testing import fuzz_testing
from project_validator.core import Options, Result, Status
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.dotnet import DOTNET
from project_validator.ecosystems.go import GO
from project_validator.ecosystems.javascript import JAVASCRIPT_AND_TYPESCRIPT
from project_validator.ecosystems.jvm import JVM
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST
from project_validator.ecosystems.swift import SWIFT
from tests.support import (
    FIXTURES,
    GITHUB_WORKFLOW,
    UNSTRUCTURED_CI_FILES,
    WELL_CONFIGURED_PYTHON,
    ci_running,
    fixture_files,
    github_job,
    github_steps,
    make_context,
    run_as,
)

PYTHON_HINT = "consider adding python <fuzz target>.py"
TARGET = "tests/fuzz/fuzz_app.py"
CLUSTERFUZZLITE = "google/clusterfuzzlite/actions/run_fuzzers@v1"
FUZZ_FILE = "import atheris\natheris.Setup([], lambda data: None)\n"


def _without_the_fuzz_step(files: dict[str, str]) -> dict[str, str]:
    workflow = files[".github/workflows/ci.yml"]
    kept = "".join(line for line in workflow.splitlines(keepends=True) if "fuzz_app.py" not in line)
    return {**files, ".github/workflows/ci.yml": kept}


class FuzzTestingTests(unittest.TestCase):
    def test_applies_to_every_language_with_a_fuzzer(self) -> None:
        self.assertIn("Python", fuzz_testing.languages)
        self.assertNotIn("PHP", fuzz_testing.languages)

    def test_the_well_configured_python_project_passes(self) -> None:
        result = run_as(self, fuzz_testing, WELL_CONFIGURED_PYTHON, PYTHON)
        self.assertEqual(result, Result.passed("fuzz targets in 1 file(s), run by atheris"))

    def test_the_well_configured_c_cpp_project_passes_through_ctest(self) -> None:
        result = run_as(self, fuzz_testing, fixture_files("well_configured_c_cpp"), C_AND_CXX)
        self.assertEqual(
            result,
            Result.passed("fuzz targets in 1 file(s), run by CTest (fuzz_test/CMakeLists.txt): fuzz_tester_run"),
        )

    def test_the_well_configured_rust_project_passes(self) -> None:
        result = run_as(self, fuzz_testing, fixture_files("well_configured_rust"), RUST)
        self.assertEqual(result, Result.passed("fuzz targets in 1 file(s), run by cargo-fuzz"))

    def test_the_well_configured_go_project_passes(self) -> None:
        result = run_as(self, fuzz_testing, fixture_files("well_configured_go"), GO)
        self.assertEqual(result, Result.passed("fuzz targets in 1 file(s), run by go test -fuzz"))

    def test_the_well_configured_jvm_project_passes(self) -> None:
        result = run_as(self, fuzz_testing, fixture_files("well_configured_jvm"), JVM)
        self.assertEqual(result, Result.passed("fuzz targets in 1 file(s), run by Jazzer"))

    def test_the_well_configured_javascript_project_passes(self) -> None:
        result = run_as(self, fuzz_testing, fixture_files("well_configured_javascript"), JAVASCRIPT_AND_TYPESCRIPT)
        self.assertEqual(result, Result.passed("fuzz targets in 1 file(s), run by Jazzer.js"))

    def test_the_well_configured_dotnet_project_passes(self) -> None:
        result = run_as(self, fuzz_testing, fixture_files("well_configured_dotnet"), DOTNET)
        self.assertEqual(result, Result.passed("fuzz targets in 1 file(s), run by SharpFuzz"))

    def test_the_well_configured_swift_project_passes(self) -> None:
        result = run_as(self, fuzz_testing, fixture_files("well_configured_swift"), SWIFT)
        self.assertEqual(result, Result.passed("fuzz targets in 1 file(s), run by libFuzzer"))

    def test_the_bare_projects_fail(self) -> None:
        bare = (
            ("bare_c_cpp", C_AND_CXX),
            ("bare_rust", RUST),
            ("bare_go", GO),
            ("bare_jvm", JVM),
            ("bare_javascript", JAVASCRIPT_AND_TYPESCRIPT),
            ("bare_dotnet", DOTNET),
            ("bare_swift", SWIFT),
        )
        for name, ecosystem in bare:
            with self.subTest(project=name):
                files = {**fixture_files(name), **github_job("ubuntu-latest", "make")}
                self.assertEqual(run_as(self, fuzz_testing, files, ecosystem).status, Status.FAIL)

    def test_fails_without_targets(self) -> None:
        files = {**fixture_files("bare_python"), **github_job("ubuntu-latest", "pytest")}
        self.assertEqual(
            run_as(self, fuzz_testing, files, PYTHON),
            Result.failed("no fuzz targets found (atheris fuzz targets (atheris.Setup or atheris.Fuzz))", PYTHON_HINT),
        )

    def test_warns_with_only_property_based_tests(self) -> None:
        files = {**fixture_files("bare_python"), "tests/test_p.py": "from hypothesis import given\n"}
        files |= github_job("ubuntu-latest", "pytest")
        self.assertEqual(
            run_as(self, fuzz_testing, files, PYTHON),
            Result.warned("only property-based tests (tests/test_p.py); no fuzz targets", PYTHON_HINT),
        )

    def test_warns_when_targets_never_run(self) -> None:
        files = _without_the_fuzz_step(WELL_CONFIGURED_PYTHON)
        self.assertNotEqual(files, WELL_CONFIGURED_PYTHON)
        self.assertEqual(
            run_as(self, fuzz_testing, files, PYTHON),
            Result.warned("fuzz targets in 1 file(s), but no CI configuration runs python <fuzz target>.py"),
        )

    def test_clusterfuzzlite_counts_as_a_run(self) -> None:
        files = {**_without_the_fuzz_step(WELL_CONFIGURED_PYTHON)}
        files |= github_steps("uses: google/clusterfuzzlite/actions/run_fuzzers@v1")
        result = run_as(self, fuzz_testing, files, PYTHON)
        self.assertEqual(
            result,
            Result.passed(f"fuzz targets in 1 file(s), run by CI ({GITHUB_WORKFLOW}): {CLUSTERFUZZLITE}"),
        )

    def test_both_kinds_of_run_are_named(self) -> None:
        workflow = WELL_CONFIGURED_PYTHON[GITHUB_WORKFLOW]
        files = {**WELL_CONFIGURED_PYTHON, GITHUB_WORKFLOW: f"{workflow}      - uses: {CLUSTERFUZZLITE}\n"}
        self.assertEqual(
            run_as(self, fuzz_testing, files, PYTHON),
            Result.passed(f"fuzz targets in 1 file(s), run by atheris and CI ({GITHUB_WORKFLOW}): {CLUSTERFUZZLITE}"),
        )

    def test_a_fuzzer_running_without_recognised_targets_warns(self) -> None:
        files = {**fixture_files("bare_python"), **github_steps("uses: google/clusterfuzzlite/actions/run_fuzzers@v1")}
        result = run_as(self, fuzz_testing, files, PYTHON)
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("no fuzz targets were recognised", result.message)

    def test_php_is_skipped(self) -> None:
        self.assertEqual(fuzz_testing.run(make_context(FIXTURES / "well_configured_php")).status, Status.SKIP)

    def test_unknown_is_an_error_unless_allowed(self) -> None:
        for provider in UNSTRUCTURED_CI_FILES:
            files = {**fixture_files("bare_python"), TARGET: FUZZ_FILE, **ci_running(provider, "make")}
            with self.subTest(ci=provider):
                result = run_as(self, fuzz_testing, files, PYTHON)
                self.assertEqual(result.status, Status.ERROR)
                self.assertEqual(
                    result.message,
                    "whether CI runs the fuzz targets is unknown: some of what it runs could not be read",
                )
                allowed = run_as(self, fuzz_testing, files, PYTHON, options=Options(allow_unknown=True))
                self.assertEqual(allowed.status, Status.WARN)
