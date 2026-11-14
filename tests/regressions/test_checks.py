"""Expected failures for check bugs the corpus audit found (upstream #225, #226, #243, #244, #247, #251). Each test
asserts the correct behaviour; it starts passing (an "unexpected success") when the bug is fixed, and its decorator
goes."""

from __future__ import annotations

import json
import unittest
from collections.abc import Mapping

from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.fuzz_testing import fuzz_testing
from project_validator.core import Check, Options, Result, Status
from tests.support import GITHUB_WORKFLOW, PROJECT_LAYOUTS, checks_named, github_job, run_in_every_layout

CI_BUILD_TYPES, HARDENING, SANITIZERS, STATIC_ANALYSIS, WARNINGS_AS_ERRORS = checks_named(
    "ci-build-types", "hardening", "sanitizers", "static-analysis", "warnings-as-errors"
)
ALLOW_UNKNOWN = Options(allow_unknown=True)
SWIFTPM = "SwiftPM"
CMAKE_CXX = "CMake C++"
REPORT_HINT = "consider reporting"
# A job that calls a reusable workflow: nothing of what it runs is read.
REUSABLE_JOB = {GITHUB_WORKFLOW: json.dumps({"jobs": {"tidy": {"uses": "other/repo/.github/workflows/x.yml@v1"}}})}
SWIFT_CI = github_job("macos-latest", "swift test -c debug", "swift test -c release")
# Alamofire's Package.swift: a Swift 6 toolchain, pinned to the Swift 5 language mode.
SWIFT5_MODE = {"Package.swift": "// swift-tools-version: 6.0\nlet package = Package(swiftLanguageModes: [.v5])\n"}
# fmt's CMakeLists: -Wshadow for GCC 5 and later, and for Clang; CI builds with both compilers.
FMT_FLAGS = {
    "CMakeLists.txt": (
        "if(CMAKE_CXX_COMPILER_ID MATCHES GNU)\n"
        "  set(PEDANTIC_COMPILE_FLAGS -Wall -Wextra -Wpedantic -Wconversion)\n"
        "  if(NOT CMAKE_CXX_COMPILER_VERSION VERSION_LESS 5.0)\n"
        "    set(PEDANTIC_COMPILE_FLAGS ${PEDANTIC_COMPILE_FLAGS} -Wshadow)\n"
        "  endif()\n"
        "endif()\n"
        "if(CMAKE_CXX_COMPILER_ID MATCHES Clang)\n"
        "  set(PEDANTIC_COMPILE_FLAGS -Wall -Wextra -Wpedantic -Wconversion -Wshadow)\n"
        "endif()\n"
        "add_compile_options(${PEDANTIC_COMPILE_FLAGS})\n"
    ),
    **github_job("ubuntu-latest", "CXX=${{ matrix.cxx }} cmake -S . -B build", matrix={"cxx": ["g++", "clang++"]}),
}
# glib's meson.build: warning_level=3 implies -Wpedantic, which the project then takes back.
GLIB_MESON = {
    "meson.build": (
        "project('x', 'c', default_options: ['warning_level=3'])\n"
        "add_project_arguments('-Wno-pedantic', language: 'c')\n"
    )
}
CODECOV = {"uses": "codecov/codecov-action@v7", "with": {"files": "lcov.info"}}
COVERALLS = {"uses": "coverallsapp/github-action@v2", "with": {"path-to-lcov": "coverage.info"}}
JULIA_COVERAGE = ({"uses": "julia-actions/julia-runtest@v1"}, {"uses": "julia-actions/julia-processcoverage@v1"})
CODECOV_YML = {".github/codecov.yml": "coverage:\n  status:\n    project:\n      default:\n        target: 80%\n"}
VITEST_THRESHOLDS = {"vitest.config.ts": "test: { coverage: { thresholds: { branches: 90 } } }\n"}
CIFUZZ = "google/oss-fuzz/infra/cifuzz/actions"
FUZZ_TARGET = {"fuzz_test/t.cpp": 'extern "C" int LLVMFuzzerTestOneInput(const unsigned char*, unsigned long);\n'}
# guava's pom.xml: Error Prone on the compiler's processor path, and its plugin passed to every compile.
ERROR_PRONE_POM = {
    "pom.xml": (
        "<project><build><plugins><plugin><artifactId>maven-compiler-plugin</artifactId><configuration>"
        "<compilerArgs><arg>-Xplugin:ErrorProne -Xep:Java8ApiChecker:ERROR</arg></compilerArgs>"
        "<annotationProcessorPaths><path><groupId>com.google.errorprone</groupId>"
        "<artifactId>error_prone_core</artifactId><version>2.36.0</version></path></annotationProcessorPaths>"
        "</configuration></plugin></plugins></build></project>\n"
    )
}


def _in_layout(
    test: unittest.TestCase, name: str, selected: Check, files: Mapping[str, str], options: Options | None = None
) -> Result:
    layouts = tuple(layout for layout in PROJECT_LAYOUTS if layout.name == name)
    return run_in_every_layout(test, selected, files, layouts, options)


def _steps(*steps: str | Mapping[str, object]) -> dict[str, str]:
    """A workflow whose one job runs `steps`: a string is a `run:` line, a mapping is the step as written."""
    parsed = [{"run": step} if isinstance(step, str) else dict(step) for step in steps]
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": parsed}}})}


def _cmake(flags: str, ci: Mapping[str, str] | None = None) -> dict[str, str]:
    return {"CMakeLists.txt": f"add_compile_options({flags})\n", **(ci or {})}


def _said(result: Result) -> str:
    return " ".join((result.message, *result.details))


class HardeningTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #243: forbids practice unknown under --allow-unknown fails with empty evidence
    def test_nothing_forbidden_found_passes_when_unrelated_jobs_are_unread(self) -> None:
        """With --allow-unknown a `forbids` practice judges what was read: nothing forbidden found passes, as drift
        gets. swift-argument-parser, swift-nio, vapor, SwiftLint, dart-lang/http and bloc all got FAIL "...: "."""
        result = _in_layout(self, SWIFTPM, HARDENING, REUSABLE_JOB, ALLOW_UNKNOWN)
        self.assertEqual(result, Result.passed("release builds keep Swift's runtime safety checks (no -Ounchecked)"))


class SwiftSettingsTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #244: Swift settings matched by regex over comments, file names, tools version
    def test_settings_are_read_from_code_not_from_any_text(self) -> None:
        """A commented-out `.treatAllWarnings(as: .error)` (vapor) and a patch *file name* (SwiftLint) set nothing;
        `swift-tools-version: 6` with `swiftLanguageModes: [.v5]` (Alamofire) is not complete concurrency checking."""
        commented = {"Package.swift": "swiftSettings: [\n    //    .treatAllWarnings(as: .error),\n]\n"}
        patch = github_job("macos-latest", "git apply --ignore-whitespace .bcr/patches/no-warnings-as-errors.patch")
        for name, files in (("commented out", commented), ("patch file name", patch)):
            with self.subTest(name):
                self.assertEqual(_in_layout(self, SWIFTPM, WARNINGS_AS_ERRORS, files).status, Status.FAIL)
        with self.subTest("language mode"):
            swift5 = {**SWIFT5_MODE, **github_job("macos-latest", "swiftlint --strict")}
            result = _in_layout(self, SWIFTPM, compiler_warnings, swift5)
            self.assertNotEqual(result.status, Status.PASS, result)
            self.assertIn("complete concurrency checking", result.message)

    @unittest.expectedFailure  # upstream #244: ci-build-types demands Swift sanitizers the sanitizers check skips
    def test_ci_build_types_and_sanitizers_take_one_position_on_swift(self) -> None:
        """ci-build-types must not demand "+ sanitizers" of a language whose sanitizers check is skipped (every Swift
        project, Alamofire among them): either both see `swift build --sanitize=`, or neither asks."""
        skipped = _in_layout(self, SWIFTPM, SANITIZERS, SWIFT_CI).status is Status.SKIP
        result = _in_layout(self, SWIFTPM, CI_BUILD_TYPES, SWIFT_CI)
        self.assertFalse(skipped and "sanitizers" in _said(result), result)


class CompilerWarningsTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #247: -Wshadow=global, -Weverything, -Wno-pedantic and found/missing wording
    def test_equivalent_spellings_negations_and_conditions_of_the_flags(self) -> None:
        """`-Wshadow=global` is `-Wshadow` and more, `-Weverything` includes every warning (nlohmann/json);
        `-Wno-pedantic` takes back Meson's `-Wpedantic` (glib); "found -Wshadow" must not contradict "missing
        -Wshadow for gcc" when the flag is set under a version condition (fmt)."""
        clang = github_job("ubuntu-latest", "CXX=clang++ cmake -S . -B build", matrix={"compiler": ["clang"]})
        for name, files in (
            ("-Wshadow=global", _cmake("-Wall -Wextra -Wpedantic -Wshadow=global -Wconversion")),
            ("-Weverything", _cmake("-Weverything", clang)),
        ):
            with self.subTest(name):
                self.assertEqual(_in_layout(self, CMAKE_CXX, compiler_warnings, files).status, Status.PASS)
        with self.subTest("-Wno-pedantic"):
            result = _in_layout(self, "Meson C", compiler_warnings, GLIB_MESON)
            self.assertIn("-Wpedantic", result.message)
            self.assertNotIn("-Wpedantic", " ".join(result.details))
        with self.subTest("condition"):
            result = _in_layout(self, CMAKE_CXX, compiler_warnings, FMT_FLAGS)
            self.assertIn("-Wshadow for gcc", result.message)
            [found] = result.details
            self.assertTrue("-Wshadow" not in found or " for " in found or "5.0" in found, result)


class CoverageTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #226: Codecov/Coveralls uploads and threshold configurations are not read
    def test_uploads_and_thresholds_reach_the_reported_and_gated_rungs(self) -> None:
        """A Codecov or Coveralls upload step reports coverage (DataFrames.jl, JuMP.jl, Documenter.jl, PostgREST,
        deno std, uber/h3, mockito); vitest and codecov.yml thresholds gate it (action-gh-release, PostgREST)."""
        cases = {
            "Codecov": ("Julia package", _steps(*JULIA_COVERAGE, CODECOV), "reported"),
            "Coveralls": (
                CMAKE_CXX,
                _steps("lcov --rc branch_coverage=1 --capture -o coverage.info", COVERALLS),
                "reported",
            ),
            "deno": ("Deno TypeScript", _steps("deno test --coverage", CODECOV), "reported"),
            "codecov.yml": ("Julia package", {**CODECOV_YML, **_steps(*JULIA_COVERAGE, CODECOV)}, "gated"),
            "vitest": ("npm JavaScript", {**VITEST_THRESHOLDS, **_steps("npx vitest --coverage")}, "gated"),
        }
        for name, (layout, files, rung) in cases.items():
            with self.subTest(name):
                result = _in_layout(self, layout, coverage, files)
                self.assertEqual(result.status, Status.PASS, result)
                self.assertIn(f" coverage is {rung} with ", result.message)
                self.assertFalse(any(REPORT_HINT in hint for hint in result.details), result)


class FuzzTestingTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #225: CIFuzz (OSS-Fuzz) actions and shell loops over fuzzers are not runs
    def test_cifuzz_and_a_shell_loop_over_fuzzer_binaries_run_the_targets(self) -> None:
        """The OSS-Fuzz CIFuzz actions run the project's fuzzers in CI (fmt, nlohmann/json, dbus-broker, h3), as does
        h3's `for f in bin/fuzz*; do $f -max_total_time=60; done`."""
        cifuzz = _steps(
            {"uses": f"{CIFUZZ}/build_fuzzers@master", "with": {"oss-fuzz-project-name": "x"}},
            {"uses": f"{CIFUZZ}/run_fuzzers@master", "with": {"oss-fuzz-project-name": "x", "fuzz-seconds": 300}},
        )
        loop = _steps(
            "for fuzzer in bin/fuzzer*; do\n  echo $fuzzer\n  $fuzzer -runs=100000 -max_total_time=60\ndone\n"
        )
        for name, ci in (("CIFuzz", cifuzz), ("shell loop", loop)):
            with self.subTest(name):
                result = _in_layout(self, CMAKE_CXX, fuzz_testing, {**FUZZ_TARGET, **ci})
                self.assertEqual(result.status, Status.PASS, result)
                self.assertIn("fuzz targets in 1 file(s), run by", result.message)


class StaticAnalysisTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #251: Error Prone regex holds literal backspaces where \b was meant
    def test_error_prone_in_a_maven_compiler_configuration_runs(self) -> None:
        """Error Prone on maven-compiler-plugin's processor path with `-Xplugin:ErrorProne` runs on every compile of
        `mvn verify` (google/guava); the regex meant to match it holds literal backspaces where `\\b` was meant."""
        files = {**ERROR_PRONE_POM, **github_job("ubuntu-latest", "./mvnw -B verify")}
        result = _in_layout(self, "Maven Java", STATIC_ANALYSIS, files)
        self.assertNotEqual(result.status, Status.FAIL, result)
        self.assertIn("Error Prone", result.message)
