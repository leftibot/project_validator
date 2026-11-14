"""Expected failures for the test-discovery gaps the corpus audit found (upstream #252 to #255, #265, #279): test
files found only at one conventional path or by one name pattern, and test runners launched in ways the profiles do
not read (a script through node, a Leiningen alias, an Eask command).

Each test asserts the behaviour the upstream issue asks for; it fails until the bug is fixed, when its decorator goes.
"""

from __future__ import annotations

import json
import unittest

from project_validator.core import Check, Status
from tests.support import checks_named, github_job, run_in_layout

STATIC_ANALYSIS, TESTS_RUN, TYPE_CHECKING = checks_named("static-analysis", "tests-run", "type-checking")
CI = "ubuntu-latest"
JUNIT_5_IMPORT = "import org.junit.jupiter.api.{annotation};\nclass ATest {{ @{annotation} void t() {{}} }}\n"
JUNIT_3_CASE = "import junit.framework.TestCase;\npublic class FooTest extends TestCase { public void testX() {} }\n"
SPOCK_SPEC = "import spock.lang.Specification\nclass FooSpec extends Specification { def 'x'() { expect: true } }\n"
MAVEN_TEST_DIRECTORY = "<project><build><testSourceDirectory>test</testSourceDirectory></build></project>\n"
KOTLIN_TEST = "import kotlin.test.Test\nclass FooTest { @Test fun x() {} }\n"
FACT = "public class AddTests { [Fact] public void Adds() {} }\n"
TEST_CSPROJ = "tests/App.Tests/App.Tests.csproj"
MTP_RUNNER = (
    "<PropertyGroup><UseMicrosoftTestingPlatformRunner>true</UseMicrosoftTestingPlatformRunner></PropertyGroup>"
)
ARCADE_PROPS = '<Project><Import Project="Sdk.props" Sdk="Microsoft.DotNet.Arcade.Sdk" /></Project>\n'
MOCHA_TEST = "describe('app', function () { it('works', function () {}) })\n"
NODE_ASSERT_TEST = "import { strict } from 'assert';\nstrict.equal(typeof validate, 'function');\n"
JEST_THROUGH_NODE = "node --experimental-vm-modules {path}jest/bin/jest.js"
UNITTEST_CASE = "import unittest\n\nclass BuildTests(unittest.TestCase):\n    def test_x(self) -> None: ...\n"
RT_SYSTEM = (
    '(defsystem "shop")\n(defsystem "shop/tests" :depends-on ("shop" "rt")\n'
    '  :perform (test-op (o s) (or (funcall (intern "DO-TESTS" (find-package "RTEST"))) (error "failed")))\n'
    '  :components ((:module "testing" :components ((:file "t")))))\n'
)
RT_RUN = """ros -e '(ql:quickload "shop/tests")' -e '(unless (rt:do-tests) (uiop:quit -1))'"""
LEIN_ALIASED = (
    '(defproject shop "0.1.0"\n  :dependencies [[org.clojure/clojure "1.12.0"]]\n'
    '  :aliases {"test-all" ["with-profile" "default:+1.11:+1.12" "test"]})\n'
)
CLOJURE_TEST = {
    "test/shop/core_test.clj": "(ns shop.core-test (:require [clojure.test :refer [deftest]]))\n(deftest t)\n"
}
EASK_COMMAND = (
    '(package "shop" "0.1.0" "Prices")\n(package-file "shop.el")\n'
    "(eask-defcommand test\n  (require 'shop-tests)\n  (ert-run-tests-batch-and-exit))\n"
)
ERT_TEST = {"test/shop-tests.el": "(require 'ert)\n(ert-deftest shop-total () (should t))\n"}


def _ci(*steps: str) -> dict[str, str]:
    return github_job(CI, *steps)


def _csproj(body: str) -> str:
    return f'<Project Sdk="Microsoft.NET.Sdk">{body}</Project>\n'


def _reference(package: str) -> str:
    return f'<ItemGroup><PackageReference Include="{package}" /></ItemGroup>'


def _scripts(**scripts: str) -> dict[str, str]:
    return {"package.json": json.dumps({"main": "index.js", "scripts": scripts})}


def _passes(test: unittest.TestCase, layout: str, selected: Check, files: dict[str, str]) -> None:
    result = run_in_layout(test, layout, selected, files)
    test.assertEqual(result.status, Status.PASS, result)


def _tests_run_in(test: unittest.TestCase, layout: str, files: dict[str, str]) -> None:
    _passes(test, layout, TESTS_RUN, files)


class JvmTestDiscoveryTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #252: the `@Test\b` regex misses @TestFactory and the other JUnit 5 markers
    def test_junit_5_annotations_other_than_test_mark_test_methods(self) -> None:
        """A class whose only tests are @TestFactory (CycloneDX/specification), @ParameterizedTest, @RepeatedTest or
        @TestTemplate methods under src/test/java holds tests, as one with @Test does."""
        for annotation in ("TestFactory", "ParameterizedTest", "RepeatedTest", "TestTemplate"):
            with self.subTest(annotation=annotation):
                files = {"src/test/java/ATest.java": JUNIT_5_IMPORT.format(annotation=annotation), **_ci("mvn test")}
                _tests_run_in(self, "Maven Java", files)

    @unittest.expectedFailure  # upstream #252: Maven's testSourceDirectory and JUnit 3 TestCase classes are unread
    def test_junit_3_test_cases_in_the_poms_test_source_directory_are_tests(self) -> None:
        """guava's `<testSourceDirectory>test</testSourceDirectory>` puts 1107 `extends TestCase` classes (no @Test)
        under guava-tests/test; `mvn verify` runs them."""
        files = {"pom.xml": MAVEN_TEST_DIRECTORY, "test/FooTest.java": JUNIT_3_CASE, **_ci("./mvnw -B verify")}
        _tests_run_in(self, "Maven Java", files)

    @unittest.expectedFailure  # upstream #252: Kotlin multiplatform test source sets are not test paths
    def test_kotlin_multiplatform_test_source_sets_hold_tests(self) -> None:
        """okhttp's src/jvmTest and src/commonTest (117 + 12 of 199 files) and kotlinx.coroutines' jvm/test and
        common/test are test source sets, like src/test/kotlin."""
        for directory in ("src/jvmTest/kotlin", "src/commonTest/kotlin", "core/jvm/test", "core/common/test"):
            with self.subTest(directory=directory):
                files = {f"{directory}/FooTest.kt": KOTLIN_TEST, **_ci("./gradlew test allTests")}
                _tests_run_in(self, "Gradle Kotlin", files)

    @unittest.expectedFailure  # upstream #252: Groovy is an unrecognised suffix, so Spock specifications are not tests
    def test_spock_specifications_in_groovy_are_jvm_tests(self) -> None:
        """liquibase's 392 Spock specifications under src/test/groovy are the bulk of its tests: Groovy is a JVM
        language, not an unrecognised suffix, and a `class FooSpec extends Specification` is a test."""
        files = {"src/test/groovy/FooSpec.groovy": SPOCK_SPEC, **_ci("./gradlew test")}
        _tests_run_in(self, "Gradle Kotlin", files)


class DotnetTestProjectTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #253: only a Microsoft.NET.Test.Sdk reference makes a test project
    def test_a_project_referencing_a_test_framework_is_a_test_project(self) -> None:
        """A .csproj referencing xunit.v3 (Humanizer, on Microsoft.Testing.Platform) or one under the Arcade SDK
        (dotnet/command-line-api, where the test SDK is implicit) is a test project; its [Fact] methods are tests."""
        cases = {
            "xunit.v3": {TEST_CSPROJ: _csproj(_reference("xunit.v3"))},
            "Microsoft.Testing.Platform": {TEST_CSPROJ: _csproj(MTP_RUNNER + _reference("xunit.v3.mtp-v2"))},
            "Arcade SDK": {TEST_CSPROJ: _csproj(""), "Directory.Build.props": ARCADE_PROPS},
        }
        for name, project in cases.items():
            with self.subTest(project=name):
                files = {**project, "tests/App.Tests/AddTests.cs": FACT, **_ci("dotnet test")}
                _tests_run_in(self, "MSBuild C#", files)


class JavaScriptTestLayoutTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #254: test files are found by file name only, never by directory
    def test_a_test_directory_run_by_a_known_runner_holds_the_tests(self) -> None:
        """mocha's and node's classic layout, `test/*.js` without `.test.` in the name, holds the tests when `npm test`
        runs mocha on it (express, mime-db), `node --test 'test/*.ts'` (got) or `node test` (octokit/graphql-schema)."""
        cases = {
            "mocha test/": ({"test/app.js": MOCHA_TEST}, "mocha --reporter spec --check-leaks test/"),
            "node --test": ({"test/abort.ts": MOCHA_TEST}, "node --test --test-timeout=60000 'test/*.ts'"),
            "node test": ({"test/index.js": NODE_ASSERT_TEST}, "node test"),
        }
        for name, (tests, script) in cases.items():
            with self.subTest(runner=name):
                _tests_run_in(self, "npm JavaScript", {**tests, **_scripts(test=script), **_ci("npm test")})

    @unittest.expectedFailure  # upstream #254: `node <path>/jest/bin/jest.js` is not matched as jest
    def test_jest_launched_through_node_is_jest(self) -> None:
        """`node --experimental-vm-modules ./node_modules/jest/bin/jest.js` (Jest's documented ESM invocation: phoenix,
        actions/checkout) runs the tests, as `jest` does."""
        for path in ("./node_modules/", "node_modules/"):
            with self.subTest(path=path):
                script = JEST_THROUGH_NODE.format(path=path)
                _tests_run_in(self, "npm JavaScript", {"a.test.js": "", **_scripts(test=script), **_ci("npm test")})

    @unittest.expectedFailure  # upstream #254: borp (node:test runner) is an unknown runner
    def test_borp_runs_the_node_test_files_it_is_configured_with(self) -> None:
        """fastify's `npm run unit` runs borp, a node:test runner, on the files of .borp.yaml."""
        files = {
            "test/a.test.js": "",
            ".borp.yaml": "files:\n  - 'test/**/*.test.js'\n",
            **_scripts(unit="borp"),
            **_ci("npm run unit"),
        }
        _tests_run_in(self, "npm JavaScript", files)

    @unittest.expectedFailure  # upstream #254: `nub run <script>` is unknown yet judged a confident miss, not unread
    def test_an_unknown_runner_of_a_package_script_is_not_a_confident_miss(self) -> None:
        """zod's `nub run test` runs the `test` package script (`vitest run`): the tests are run, or at worst the
        answer is unknown; a confident "no CI runs the tests" is wrong."""
        files = {"a.test.js": "", **_scripts(test="vitest run"), **_ci("nub run test")}
        result = run_in_layout(self, "npm JavaScript", TESTS_RUN, files)
        self.assertIn(result.status, (Status.PASS, Status.ERROR), result)

    @unittest.expectedFailure  # upstream #254: xo (eslint wrapper) is an unknown linter
    def test_xo_is_an_eslint_wrapper_that_lints(self) -> None:
        """got's `npm test` runs xo (eslint configured in package.json's `xo` key): a static analyzer runs."""
        package = {"package.json": json.dumps({"main": "index.js", "scripts": {"test": "xo"}, "xo": {}})}
        _passes(self, "npm JavaScript", STATIC_ANALYSIS, {**package, **_ci("npm test")})

    @unittest.expectedFailure  # upstream #254: the strict hint ignores an `extends` base that may be strict
    def test_a_tsconfig_extending_a_base_is_not_told_to_enable_strict(self) -> None:
        """got's tsconfig extends @sindresorhus/tsconfig (strict): whether strict is on is not visible, so the hint
        "consider enabling strict mode" is wrong; the result may say strict is not visible instead."""
        files = {"tsconfig.json": '{"extends": "@sindresorhus/tsconfig"}', "a.ts": "", **_ci("npx tsc --noEmit")}
        result = run_in_layout(self, "npm JavaScript", TYPE_CHECKING, files)
        self.assertEqual(result.status, Status.PASS, result)
        self.assertFalse(any("consider enabling strict mode" in detail for detail in result.details), result)


class PythonTestFilePatternTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #255: `*_tests.py` under tests/ is not a Python test file pattern
    def test_tests_py_files_under_a_tests_directory_are_test_files(self) -> None:
        """mkdocs' `mkdocs/tests/build_tests.py` (12 such files), discovered by CI with
        `unittest discover -s mkdocs -p "*tests.py"`, holds tests."""
        for runner in ('python -m unittest discover -s app -p "*tests.py"', "pytest"):
            with self.subTest(runner=runner):
                files = {"src/app/tests/build_tests.py": UNITTEST_CASE, **_ci(runner)}
                _tests_run_in(self, "Python pyproject", files)


class LispTestRunnerTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #265: testing/, (rtest:deftest and (rt:do-tests) are unknown to Common Lisp
    def test_rt_suites_under_testing_are_run_by_rt_do_tests(self) -> None:
        """ironclad's `testing/` holds `rtest:deftest` forms of the `rt` framework (137 .testvec vectors), and every
        CI job runs `(rt:do-tests)` after loading the test system."""
        files = {
            "shop.asd": RT_SYSTEM,
            "testing/t.lisp": "(rtest:deftest quotationp.1 (shop:total '(1)) 1)\n",
            **_ci(RT_RUN),
        }
        _tests_run_in(self, "ASDF system", files)

    @unittest.expectedFailure  # upstream #265: project.clj :aliases and `lein with-profile X test` are not resolved
    def test_leiningen_aliases_and_with_profile_run_the_tests(self) -> None:
        """compojure's `lein test-all` is a project.clj alias for `lein with-profile ... test`: both run the tests."""
        for line in ("lein test-all", "lein with-profile default:+1.12 test"):
            with self.subTest(line=line):
                files = {"project.clj": LEIN_ALIASED, **CLOJURE_TEST, **_ci(line)}
                _tests_run_in(self, "Leiningen project", files)


class EaskCommandTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #279: `eask run command <name>` running ert is not a test run
    def test_an_eask_command_that_runs_ert_is_a_test_run(self) -> None:
        """evil's `eask run command test` runs an Eask-defined command whose body requires the test file and calls
        ert-run-tests-batch-and-exit: the tests run (or, the body being Elisp, the answer is unknown), not "no CI
        runs the tests"."""
        files = {"Eask": EASK_COMMAND, **ERT_TEST, **_ci("eask run command test")}
        result = run_in_layout(self, "Eask package", TESTS_RUN, files)
        self.assertIn(result.status, (Status.PASS, Status.ERROR), result)
