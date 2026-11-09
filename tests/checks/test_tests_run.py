import os
import shutil
import subprocess
import unittest
from unittest import mock

from project_validator.checks.tests_run import tests_run
from project_validator.core import Options, Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST
from project_validator.facts import Facts
from project_validator.facts.testing import RUNS, TEST
from project_validator.policy.testing import judge_tests
from project_validator.questions.tooling import tool_answer
from tests.support import (
    BARE_PROJECT,
    CI_FILES,
    FIXTURES,
    NON_CMAKE_C_FAMILY_LAYOUTS,
    UNSTRUCTURED_CI_FILES,
    WELL_CONFIGURED,
    WELL_CONFIGURED_PYTHON,
    c_family_layouts_built_with,
    ci_running,
    github_job,
    make_context,
    run_as,
    run_in_every_layout,
    temp_project,
)

NO_C_TESTS = (
    "no tests found (tests registered with CTest (enable_testing(), then add_test or a *_discover_tests call) or "
    "tests registered with Meson's test() in meson.build)"
)


class CtestRunsTests(unittest.TestCase):
    def _run(self, files: dict[str, str], options: Options | None = None) -> Result:
        return run_in_every_layout(self, tests_run, files, c_family_layouts_built_with(tests_run, "CMake"), options)

    def test_declares_the_languages_it_judges(self) -> None:
        # Profiles and plugins add languages, so only the stable ones are pinned.
        self.assertLessEqual(C_FAMILY | {"Python", "Rust"}, tests_run.languages)
        self.assertIn("ctest-runs", tests_run.aliases)

    def test_passes_when_tests_are_registered_and_run_in_ci(self) -> None:
        self.assertEqual(self._run(WELL_CONFIGURED), Result.passed("tests found in 2 file(s)"))

    def test_a_project_without_a_build_system_has_no_registered_tests(self) -> None:
        layouts = tuple(layout for layout in NON_CMAKE_C_FAMILY_LAYOUTS if not layout.build_systems)
        result = run_in_every_layout(self, tests_run, {"main.cpp": ""}, layouts)
        self.assertEqual(result, Result.failed(NO_C_TESTS))

    def test_fails_when_ctest_is_never_enabled_or_registers_nothing(self) -> None:
        for files in (
            BARE_PROJECT,
            {"CMakeLists.txt": "add_test(NAME t COMMAND t)\n"},
            {"CMakeLists.txt": "enable_testing()\n# add_test(NAME t COMMAND t)\n"},
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(files), Result.failed(NO_C_TESTS))

    def test_warns_when_ci_never_runs_ctest(self) -> None:
        cmake = {"CMakeLists.txt": "include(CTest)\ncatch_discover_tests(tests)\n"}
        result = self._run({**cmake, **github_job("ubuntu-latest", "cmake --build build")})
        self.assertEqual(
            result, Result.warned("tests found in 1 file(s), but no CI configuration runs ctest or meson test")
        )

    def test_passes_when_any_ci_provider_runs_ctest(self) -> None:
        cmake = {"CMakeLists.txt": "include(CTest)\nadd_test(NAME t COMMAND t)\n"}
        for provider in CI_FILES:
            for command in ("ctest --test-dir build", "cmake --build build --target test", "cmake --workflow ci"):
                with self.subTest(ci=provider, command=command):
                    self.assertEqual(self._run({**cmake, **ci_running(provider, command)}).status, Status.PASS)

    @unittest.skipUnless(shutil.which("cmake") and shutil.which("ctest"), "cmake is not installed")
    def test_build_mode_counts_the_tests_ctest_finds(self) -> None:
        result = tests_run.run(make_context(FIXTURES / "buildable", Options(build=True)))
        self.assertEqual(
            result, Result.warned("tests found in 1 file(s), but no CI configuration runs ctest or meson test")
        )

    @unittest.skipUnless(shutil.which("cmake") and shutil.which("ninja"), "cmake or ninja is not installed")
    def test_build_mode_finds_tests_with_multi_config_generators(self) -> None:
        with mock.patch.dict(os.environ, {"CMAKE_GENERATOR": "Ninja Multi-Config"}):
            result = tests_run.run(make_context(FIXTURES / "buildable", Options(build=True)))
        self.assertIn("tests found in 1 file(s)", result.message)

    def test_build_mode_counts_what_ctest_lists(self) -> None:
        cmake = {"CMakeLists.txt": "enable_testing()\nadd_test(NAME t COMMAND t)\n", **github_job("x", "ctest")}
        with mock.patch("project_validator.build_systems.cmake.ctest.count_built_tests", return_value=0):
            self.assertEqual(self._run(cmake, Options(build=True)), Result.failed(NO_C_TESTS))
        with mock.patch("project_validator.build_systems.cmake.ctest.count_built_tests", return_value=3):
            self.assertEqual(self._run(cmake, Options(build=True)).status, Status.PASS)

    def test_a_build_that_fails_is_unknown(self) -> None:
        failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="CMake Error: boom\n")
        cmake = {"CMakeLists.txt": "enable_testing()\n", **github_job("x", "ctest")}
        with (
            mock.patch("project_validator.build_systems.cmake.ctest.subprocess.run", return_value=failed),
            temp_project(cmake) as root,
        ):
            result = tests_run.run(make_context(root, Options(build=True)))
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("CMake Error: boom", result.details[0])

    def test_a_build_that_cannot_run_is_unknown(self) -> None:
        options = Options(build=True, cmake="no-such-cmake-binary")
        result = tests_run.run(make_context(FIXTURES / "buildable", options))
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("could not run no-such-cmake-binary", result.details[0])


class MesonTestsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        layouts = c_family_layouts_built_with(tests_run, "Meson")
        self.assertTrue(layouts)
        return run_in_every_layout(self, tests_run, files, layouts)

    def test_fails_when_meson_registers_no_tests(self) -> None:
        self.assertEqual(self._run({}), Result.failed(NO_C_TESTS))

    def test_commented_out_or_other_calls_do_not_count(self) -> None:
        result = self._run({"tests/meson.build": "# test('unit', exe)\nunittest_exe = executable('t', 't.cpp')\n"})
        self.assertEqual(result.status, Status.FAIL)

    def test_warns_when_ci_never_runs_meson_test(self) -> None:
        result = self._run({"tests/meson.build": "test('unit', executable('t', 't.cpp'))\n"})
        self.assertEqual(
            result, Result.warned("tests found in 1 file(s), but no CI configuration runs ctest or meson test")
        )

    def test_passes_when_ci_runs_meson_test(self) -> None:
        for command in ("meson test -C build", "ninja -C build test"):
            with self.subTest(command=command):
                files = {"tests/meson.build": "test('unit', exe)\n", **github_job("ubuntu-latest", command)}
                self.assertEqual(self._run(files).status, Status.PASS)


class PythonTestsRunTests(unittest.TestCase):
    def _run(self, files: dict[str, str], options: Options | None = None) -> Result:
        return run_as(self, tests_run, files, PYTHON, options=options)

    def test_passes_when_tests_exist_and_any_ci_runs_them(self) -> None:
        tests = {"tests/test_app.py": "", "app/io_test.py": ""}
        for provider in CI_FILES:
            for runner in ("python -m pytest", "python -m unittest discover", "nox -s tests"):
                with self.subTest(ci=provider, runner=runner):
                    result = self._run({**tests, **ci_running(provider, runner)})
                    self.assertEqual(result, Result.passed("tests found in 2 file(s)"))

    def test_coverage_run_runs_the_module_it_names(self) -> None:
        tests = {"tests/test_app.py": ""}
        for command, status in (
            ("coverage run --rcfile=.coveragerc --branch -m pytest", Status.PASS),
            ("coverage run --source src -m", Status.WARN),
            ("coverage run tests/run.py", Status.WARN),
        ):
            with self.subTest(command=command):
                self.assertEqual(self._run({**tests, **github_job("x", command)}).status, status)

    def test_tox_runs_the_commands_of_its_environments(self) -> None:
        tox = {"tox.ini": "[testenv]\ncommands = pytest\n", "tests/test_app.py": ""}
        self.assertEqual(self._run({**tox, **github_job("x", "tox -e py314")}).status, Status.PASS)

    def test_fails_without_tests(self) -> None:
        result = self._run({"tests/helpers.py": "", "tests/conftest.py": "", **github_job("x", "pytest")})
        self.assertEqual(result, Result.failed("no tests found (test_*.py or *_test.py files)"))

    def test_warns_when_ci_never_runs_the_tests(self) -> None:
        result = self._run({"tests/test_app.py": "", **github_job("x", "python -m build")})
        self.assertEqual(
            result, Result.warned("tests found in 1 file(s), but no CI configuration runs pytest, unittest or nox")
        )

    def test_unread_ci_makes_whether_tests_run_unknown(self) -> None:
        for provider in UNSTRUCTURED_CI_FILES:
            with self.subTest(ci=provider):
                result = self._run({"tests/test_app.py": "", **ci_running(provider, "make")})
                self.assertEqual(result.status, Status.ERROR)
                self.assertEqual(
                    result.message, "whether CI runs the tests is unknown: some of what it runs could not be read"
                )

    def test_build_mode_does_not_need_cmake(self) -> None:
        result = self._run(dict(WELL_CONFIGURED_PYTHON), Options(build=True, cmake="no-such-cmake-binary"))
        self.assertEqual(result.status, Status.PASS)


class RustTestsRunTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, tests_run, files, RUST)

    def test_passes_when_tests_exist_and_any_ci_runs_them(self) -> None:
        sources = {"src/lib.rs": "#[test]\nfn unit() {}\n", "tests/api.rs": "#[tokio::test]\nasync fn api() {}\n"}
        for provider in CI_FILES:
            for runner in ("cargo test", "cargo +nightly nextest run", "cargo llvm-cov --branch"):
                with self.subTest(ci=provider, runner=runner):
                    result = self._run({**sources, **ci_running(provider, runner)})
                    self.assertEqual(result, Result.passed("tests found in 2 file(s)"))

    def test_fails_without_tests(self) -> None:
        result = self._run({"src/lib.rs": "pub fn testing() {}\n", **github_job("x", "cargo test")})
        self.assertEqual(result, Result.failed("no tests found (#[test] functions)"))

    def test_warns_when_ci_never_runs_the_tests(self) -> None:
        result = self._run({"src/lib.rs": "#[test]\nfn unit() {}\n", **github_job("x", "cargo build")})
        self.assertEqual(result, Result.warned("tests found in 1 file(s), but no CI configuration runs cargo test"))


class AnswerTests(unittest.TestCase):
    def test_a_language_no_known_runner_runs_is_skipped(self) -> None:
        answer = tool_answer(TEST, RUNS, "Lang", Facts(()), ())
        self.assertEqual(judge_tests(answer), Result(status=Status.SKIP, message="no known test runner runs Lang"))


class MixedLanguageTestsRunTests(unittest.TestCase):
    def test_every_language_needs_tests_and_findings_are_labelled(self) -> None:
        result = run_as(self, tests_run, dict(WELL_CONFIGURED), C_AND_CXX, PYTHON)
        self.assertEqual(
            result,
            Result.failed("C/C++: tests found in 2 file(s); Python: no tests found (test_*.py or *_test.py files)"),
        )
