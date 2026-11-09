"""The fuzz aspect: fuzz targets and property tests as kinds of test file, and the fuzzers defined by them."""

import re
import unittest

from project_validator.core import Result
from project_validator.ecosystems.c_cpp.fuzzing import (
    AFL,
    C_FUZZ_TARGETS,
    C_PROPERTY_TESTS,
    LIBFUZZER,
)
from project_validator.ecosystems.dotnet.fuzzing import DOTNET_FUZZ_TARGETS, DOTNET_PROPERTY_TESTS, SHARPFUZZ
from project_validator.ecosystems.go import GO_FUZZ, GO_FUZZ_TARGETS, GO_PROPERTY_TESTS, GO_TEST_FILES
from project_validator.ecosystems.javascript.fuzzing import (
    JAZZER_JS,
    JS_FUZZ_TARGETS,
    JS_PROPERTY_TESTS,
)
from project_validator.ecosystems.jvm.fuzzing import JAZZER, JVM_FUZZ_TARGETS, JVM_PROPERTY_TESTS
from project_validator.ecosystems.python.fuzzing import ATHERIS, PYTHON_FUZZ_TARGETS, PYTHON_PROPERTY_TESTS
from project_validator.ecosystems.rust.fuzzing import (
    CARGO_FUZZ,
    RUST_FUZZ_TARGETS,
    RUST_PROPERTY_TESTS,
)
from project_validator.ecosystems.swift import SWIFT_FUZZ_TARGETS, SWIFT_LIBFUZZER, SWIFT_PROPERTY_TESTS
from project_validator.facts import Facts, Origin
from project_validator.facts.fuzzing import (
    FUZZ,
    RUNS,
    FuzzTargets,
    PropertyTests,
    fuzz_kinds,
    fuzzed,
    fuzzer,
    known_fuzz_targets,
    known_property_tests,
    property_kinds,
)
from project_validator.facts.roles import role
from project_validator.facts.testing import TestFile, TestFiles
from project_validator.facts.tools import ToolRun
from project_validator.policy.fuzzing import judge_fuzzing
from project_validator.questions.fuzzing import FuzzAnswer, _other_runs, fuzzing
from tests.support import command, fixture_files, github_job, make_context, temp_project


def facts_of(files: dict[str, str]) -> Facts:
    with temp_project(files) as root:
        return make_context(root).facts


class FuzzAspectTests(unittest.TestCase):
    def test_fuzz_targets_and_property_tests_are_test_files(self) -> None:
        for kind_type in (FuzzTargets, PropertyTests):
            kind = kind_type(name="k", languages=frozenset({"Python"}), path=re.compile(r"\.py$"))
            self.assertIsInstance(kind, TestFiles)

    def test_the_known_kind_names_are_those_of_the_known_kinds(self) -> None:
        self.assertIsInstance(known_fuzz_targets(), tuple)
        self.assertIsInstance(known_property_tests(), tuple)
        self.assertEqual(fuzz_kinds(), frozenset(kind.name for kind in known_fuzz_targets()))
        self.assertEqual(property_kinds(), frozenset(kind.name for kind in known_property_tests()))

    def test_a_fuzzer_is_defined_by_the_fuzz_target_files_of_its_targets(self) -> None:
        kind = FuzzTargets(
            name="python fuzz targets", languages=frozenset({"Python"}), path=re.compile(r"fuzz_.*\.py$")
        )
        tool = fuzzer(name="f", languages=frozenset({"Python"}), how="f", runs=lambda c, f: None, targets=(kind,))
        facts = Facts(
            [
                TestFile(origin=Origin(path="tests/fuzz/fuzz_x.py"), language="Python", kind="python fuzz targets"),
                TestFile(origin=Origin(path="tests/fuzz/fuzz_x.py"), language="Python", kind="python fuzz targets"),
                TestFile(origin=Origin(path="tests/test_x.py"), language="Python", kind="test_*.py or *_test.py files"),
            ]
        )
        self.assertEqual(tool.defined(FUZZ, facts), ("tests/fuzz/fuzz_x.py",))
        self.assertTrue(tool.needs_definition(FUZZ))
        self.assertEqual(tool.definitions[FUZZ].describe, kind.name)

    def test_a_fuzzer_with_two_targets_names_both(self) -> None:
        first = FuzzTargets(name="libFuzzer targets", languages=frozenset({"C++"}), path=re.compile(r"\.cpp$"))
        second = FuzzTargets(name="atheris targets", languages=frozenset({"C++"}), path=re.compile(r"\.py$"))
        tool = fuzzer(name="f", languages=frozenset({"C++"}), how="f", runs=lambda c, f: None, targets=(first, second))
        self.assertEqual(tool.definitions[FUZZ].describe, "libFuzzer targets or atheris targets")

    def test_fuzzed_provides_runs(self) -> None:
        self.assertEqual(fuzzed().provides, {FUZZ: frozenset({RUNS})})


class RolesTests(unittest.TestCase):
    def test_fuzz_test_directories_are_tests(self) -> None:
        for path in ("fuzz_test/fuzz_tester.cpp", "fuzz_tests/a.rs", "fuzztest/x.go", "fuzz/target.rs"):
            with self.subTest(path=path):
                self.assertEqual(role(path), "test")


PYTHON_PROJECT = {
    "tests/fuzz/fuzz_x.py": "import atheris\natheris.Setup(sys.argv, f)\n",
    "tests/test_p.py": "from hypothesis import given\n",
    "pyproject.toml": "[project]\nname='a'\n",
}


class PythonFuzzingTests(unittest.TestCase):
    def test_atheris_files_are_fuzz_targets_and_hypothesis_files_are_property_tests(self) -> None:
        facts = facts_of(PYTHON_PROJECT)
        kinds = {(t.origin.path, t.kind) for t in facts.of(TestFile)}
        self.assertIn(("tests/fuzz/fuzz_x.py", PYTHON_FUZZ_TARGETS.name), kinds)
        self.assertIn(("tests/test_p.py", PYTHON_PROPERTY_TESTS.name), kinds)
        self.assertNotIn(("tests/test_p.py", PYTHON_FUZZ_TARGETS.name), kinds)

    def test_python_running_a_fuzz_target_file_is_a_run(self) -> None:
        facts = facts_of(PYTHON_PROJECT)
        self.assertIsNotNone(ATHERIS.claims(command("python tests/fuzz/fuzz_x.py corpus -max_total_time=60"), facts))
        self.assertIsNotNone(ATHERIS.claims(command("python3 -X dev tests/fuzz/fuzz_x.py"), facts))
        self.assertIsNotNone(ATHERIS.claims(command("python3.13 ./tests/fuzz/fuzz_x.py"), facts))
        self.assertIsNone(ATHERIS.claims(command("python -m pytest"), facts))
        self.assertIsNone(ATHERIS.claims(command("python tests/test_p.py"), facts))
        self.assertIsNone(ATHERIS.claims(command("ruby tests/fuzz/fuzz_x.py"), facts))

    def test_a_path_with_an_unexpanded_shell_variable_is_a_heuristic_run_only_when_it_names_fuzzing(self) -> None:
        facts = facts_of(PYTHON_PROJECT)
        for line in ("python tests/fuzz/${TARGET}", "python tests/FUZZ/${TARGET}"):
            run = ATHERIS.claims(command(line), facts)
            self.assertTrue(run is not None and run.heuristic)
        for line in ("python scripts/${NAME}.py", "python ${SCRIPT}"):
            self.assertIsNone(ATHERIS.claims(command(line), facts))

    def test_a_ci_expression_path_is_a_heuristic_run_only_when_it_names_fuzzing(self) -> None:
        for script, heuristic in (
            ("tests/fuzz/${{ github.event.inputs.target }}", True),
            ("${{ github.event.inputs.fuzz_target }}", True),
            ("${{ github.event.inputs.script }}", False),
        ):
            with self.subTest(script=script):
                files = {**PYTHON_PROJECT, **github_job("ubuntu-latest", f"python {script}")}
                runs = [run for run in facts_of(files).of(ToolRun) if run.tool == ATHERIS.name]
                self.assertEqual([run.heuristic for run in runs], [True] if heuristic else [])


def _kinds(files: dict[str, str]) -> set[tuple[str, str]]:
    return {(t.origin.path, t.kind) for t in facts_of(files).of(TestFile)}


class CFuzzingTests(unittest.TestCase):
    def test_llvm_fuzzer_entry_point_is_a_target(self) -> None:
        files = {
            "fuzz_test/t.cpp": 'extern "C" int LLVMFuzzerTestOneInput(const unsigned char*, unsigned long);\n',
            "src/a.cpp": "int main() {}\n",
            "t/p.cpp": "RC_GTEST_PROP(A, b, ()) {}\n",
        }
        kinds = _kinds(files)
        self.assertIn(("fuzz_test/t.cpp", C_FUZZ_TARGETS.name), kinds)
        self.assertNotIn(("src/a.cpp", C_FUZZ_TARGETS.name), kinds)
        self.assertIn(("t/p.cpp", C_PROPERTY_TESTS.name), kinds)

    def test_a_libfuzzer_binary_run_in_ci_is_a_heuristic_run(self) -> None:
        facts = Facts([])
        run = LIBFUZZER.claims(command("./build/fuzz_tester -max_total_time=30"), facts)
        self.assertTrue(run is not None and run.heuristic)
        self.assertIsNotNone(LIBFUZZER.claims(command("build/fuzz_tester corpus/ -runs=1000"), facts))
        self.assertIsNone(LIBFUZZER.claims(command("./build/fuzz_tester"), facts))
        self.assertIsNone(LIBFUZZER.claims(command("pytest -runs=3"), facts))
        self.assertIsNone(LIBFUZZER.claims(command("cargo fuzz run parse -- -max_total_time=30"), facts))

    def test_afl_fuzz_is_a_run(self) -> None:
        self.assertIsNotNone(AFL.claims(command("afl-fuzz -i in -o out -- ./target"), Facts([])))
        self.assertIsNone(AFL.claims(command("afl-gcc a.c"), Facts([])))

    def test_a_ctest_registered_fuzz_target_runs(self) -> None:
        files = {
            **fixture_files("well_configured_c_cpp"),
            "fuzz_test/CMakeLists.txt": "add_test(NAME other_run COMMAND other_tool -max_total_time=10)\n",
        }
        self.assertEqual(_ctest_entries(files), ())
        files["fuzz_test/CMakeLists.txt"] = "add_test(NAME fuzz_tester_run COMMAND fuzz_tester)\n"
        self.assertEqual(_ctest_entries(files), ("CTest (fuzz_test/CMakeLists.txt): fuzz_tester_run",))

    def test_a_ctest_fuzz_test_does_not_run_without_a_ctest_run(self) -> None:
        files = {
            **fixture_files("well_configured_c_cpp"),
            **github_job("ubuntu-latest", "cmake --build build"),
            "fuzz_test/CMakeLists.txt": "add_test(NAME fuzz_tester_run COMMAND fuzz_tester)\n",
        }
        self.assertEqual(_ctest_entries(files), ())


def _ctest_entries(files: dict[str, str]) -> tuple[str, ...]:
    facts = facts_of(files)
    return tuple(entry for entry in _other_runs(facts, ".", "C++") if entry.startswith("CTest"))


MIXED_FILES = {
    "CMakeLists.txt": "project(x LANGUAGES CXX)\nenable_testing()\n"
    "add_test(NAME fuzz_tester_run COMMAND fuzz_tester -max_total_time=10)\n",
    "fuzz/t.cpp": 'extern "C" int LLVMFuzzerTestOneInput(const unsigned char*, unsigned long) { return 0; }\n',
    "fuzz/fuzz_targets/parse.rs": "fuzz_target!(|data: &[u8]| {});\n",
    "Cargo.toml": "[package]\nname='a'\n",
    **github_job("ubuntu-latest", "cmake -S . -B build && cmake --build build && ctest --test-dir build"),
}


class CTestLanguageTests(unittest.TestCase):
    def test_a_ctest_registration_is_evidence_only_for_the_languages_cmake_builds(self) -> None:
        facts = facts_of(MIXED_FILES)
        results = {language: judge_fuzzing(_only_unit(language, facts)) for language in ("C++", "Rust")}
        self.assertEqual(
            results["C++"],
            Result.passed("fuzz targets in 1 file(s), run by CTest (CMakeLists.txt): fuzz_tester_run"),
        )
        self.assertEqual(
            results["Rust"],
            Result.warned(
                "fuzz targets in 1 file(s), but no CI configuration runs cargo fuzz run <target> -- -max_total_time=60"
            ),
        )


def _only_unit(language: str, facts: Facts) -> FuzzAnswer:
    [answer] = fuzzing(language, facts).units
    return answer


class RustFuzzingTests(unittest.TestCase):
    def test_fuzz_target_macro_is_a_target(self) -> None:
        files = {
            "fuzz/fuzz_targets/parse.rs": "fuzz_target!(|data: &[u8]| {});\n",
            "src/lib.rs": "pub fn f() {}\n",
            "tests/p.rs": "proptest! { #[test] fn a() {} }\n",
        }
        kinds = _kinds(files)
        self.assertIn(("fuzz/fuzz_targets/parse.rs", RUST_FUZZ_TARGETS.name), kinds)
        self.assertNotIn(("src/lib.rs", RUST_FUZZ_TARGETS.name), kinds)
        self.assertIn(("tests/p.rs", RUST_PROPERTY_TESTS.name), kinds)

    def test_cargo_fuzz_run_is_a_run(self) -> None:
        for line in (
            "cargo fuzz run parse -- -max_total_time=30",
            "cargo +nightly fuzz run parse",
            "cargo afl fuzz -i in -o out target/debug/x",
        ):
            with self.subTest(line=line):
                self.assertIsNotNone(CARGO_FUZZ.claims(command(line), Facts([])))
        for line in ("cargo fuzz build", "cargo test", "cargo fuzz list"):
            with self.subTest(line=line):
                self.assertIsNone(CARGO_FUZZ.claims(command(line), Facts([])))


class GoFuzzingTests(unittest.TestCase):
    def test_fuzz_functions_are_targets_and_tests(self) -> None:
        files = {
            "app_test.go": "func FuzzParse(f *testing.F) {}\nfunc TestA(t *testing.T) {}\n",
            "go.mod": "module a\n",
        }
        kinds = _kinds(files)
        self.assertIn(("app_test.go", GO_FUZZ_TARGETS.name), kinds)
        self.assertIn(("app_test.go", GO_TEST_FILES.name), kinds)
        self.assertNotIn(("app_test.go", GO_PROPERTY_TESTS.name), kinds)
        plain = _kinds({"b_test.go": "func TestA(t *testing.T) {}\n", "go.mod": "module a\n"})
        self.assertNotIn(("b_test.go", GO_FUZZ_TARGETS.name), plain)

    def test_plain_go_test_does_not_fuzz(self) -> None:
        self.assertIsNone(GO_FUZZ.claims(command("go test ./..."), Facts([])))
        self.assertIsNotNone(GO_FUZZ.claims(command("go test -fuzz=Fuzz -fuzztime=30s ."), Facts([])))


def _marks(path: str, text: str, *kinds: TestFiles) -> list[bool]:
    found = _kinds({path: text})
    return [(path, kind.name) in found for kind in kinds]


class JvmFuzzingTests(unittest.TestCase):
    def test_fuzz_tests_are_targets_and_jqwik_properties_are_property_tests(self) -> None:
        target = "class T { @FuzzTest void f(FuzzedDataProvider d) {} }\n"
        self.assertEqual(_marks("src/test/java/T.java", target, JVM_FUZZ_TARGETS, JVM_PROPERTY_TESTS), [True, False])
        classic = "class T { static void fuzzerTestOneInput(byte[] b) {} }\n"
        self.assertEqual(_marks("src/T.kt", classic, JVM_FUZZ_TARGETS), [True])
        prop = "import net.jqwik.api.*;\nclass P { @Property void p() {} }\n"
        self.assertEqual(_marks("src/test/java/P.java", prop, JVM_FUZZ_TARGETS, JVM_PROPERTY_TESTS), [False, True])
        self.assertEqual(_marks("notes.txt", target, JVM_FUZZ_TARGETS), [False])

    def test_jazzer_runs_by_its_cli_or_by_a_maven_or_gradle_test_with_jazzer_fuzz(self) -> None:
        facts = Facts([])
        self.assertIsNotNone(JAZZER.claims(command("jazzer --cp=a.jar --target_class=T"), facts))
        for line in ("mvn test", "mvn --batch-mode verify -Dtest=T", "./gradlew test", "gradle check"):
            with self.subTest(line=line):
                self.assertIsNotNone(JAZZER.claims(command(line, {"JAZZER_FUZZ": "1"}), facts))
                self.assertIsNone(JAZZER.claims(command(line), facts))
                self.assertIsNone(JAZZER.claims(command(line, {"JAZZER_FUZZ": "0"}), facts))
        self.assertIsNone(JAZZER.claims(command("mvn package", {"JAZZER_FUZZ": "1"}), facts))
        self.assertIsNone(JAZZER.claims(command("make test", {"JAZZER_FUZZ": "1"}), facts))


class JavaScriptFuzzingTests(unittest.TestCase):
    def test_fuzz_exports_are_targets_and_fast_check_tests_are_property_tests(self) -> None:
        self.assertEqual(_marks("fuzz/a.fuzz.js", "module.exports.fuzz = (d) => {};\n", JS_FUZZ_TARGETS), [True])
        self.assertEqual(_marks("fuzz/a.ts", "export function fuzz(d: Buffer) {}\n", JS_FUZZ_TARGETS), [True])
        self.assertEqual(_marks("src/a.test.js", "it.fuzz('x', (d) => {});\n", JS_FUZZ_TARGETS), [True])
        self.assertEqual(_marks("src/a.js", "function fuzzy() {}\n", JS_FUZZ_TARGETS), [False])
        prop = "import fc from 'fast-check';\nfc.assert(fc.property(fc.nat(), () => true));\n"
        self.assertEqual(_marks("src/p.test.js", prop, JS_FUZZ_TARGETS, JS_PROPERTY_TESTS), [False, True])

    def test_jazzer_js_runs_by_its_cli_or_by_jest_with_jazzer_fuzz(self) -> None:
        facts = Facts([])
        self.assertIsNotNone(JAZZER_JS.claims(command("jazzer fuzz/add.fuzz.js -- -max_total_time=30"), facts))
        self.assertIsNotNone(JAZZER_JS.claims(command("jest", {"JAZZER_FUZZ": "1"}), facts))
        self.assertIsNotNone(JAZZER_JS.claims(command("jest", {"JAZZER_FUZZ": "true"}), facts))
        self.assertIsNone(JAZZER_JS.claims(command("jest"), facts))
        self.assertIsNone(JAZZER_JS.claims(command("jest", {"JAZZER_FUZZ": "0"}), facts))
        self.assertIsNone(JAZZER_JS.claims(command("npm audit"), facts))


class DotnetFuzzingTests(unittest.TestCase):
    def test_sharpfuzz_entry_points_are_targets_and_fscheck_tests_are_property_tests(self) -> None:
        self.assertEqual(_marks("fuzz/Program.cs", "Fuzzer.LibFuzzer.Run(x => {});\n", DOTNET_FUZZ_TARGETS), [True])
        self.assertEqual(_marks("fuzz/P.fs", "Fuzzer.OutOfProcess.Run(f)\n", DOTNET_FUZZ_TARGETS), [True])
        self.assertEqual(_marks("src/A.cs", "Fuzzer.Run(f);\n", DOTNET_FUZZ_TARGETS), [True])
        self.assertEqual(_marks("src/A.cs", "class A {}\n", DOTNET_FUZZ_TARGETS), [False])
        prop = "[Property] public void P() { Prop.ForAll(g, f); }\n"
        self.assertEqual(_marks("tests/P.cs", prop, DOTNET_FUZZ_TARGETS, DOTNET_PROPERTY_TESTS), [False, True])

    def test_sharpfuzz_runs_by_libfuzzer_dotnet_sharpfuzz_or_afl(self) -> None:
        facts = Facts([])
        for line in (
            "libfuzzer-dotnet --target_path=x -max_total_time=30",
            "sharpfuzz a.dll",
            "afl-fuzz -i in -o out x",
        ):
            with self.subTest(line=line):
                self.assertIsNotNone(SHARPFUZZ.claims(command(line), facts))
        self.assertIsNone(SHARPFUZZ.claims(command("dotnet test"), facts))


class SwiftFuzzingTests(unittest.TestCase):
    def test_the_libfuzzer_entry_point_is_a_target_and_swiftcheck_tests_are_property_tests(self) -> None:
        main = '@_cdecl("LLVMFuzzerTestOneInput")\npublic func f(_ d: UnsafePointer<UInt8>, _ n: Int) -> CInt { 0 }\n'
        self.assertEqual(_marks("Sources/F/main.swift", main, SWIFT_FUZZ_TARGETS), [True])
        self.assertEqual(_marks("Sources/A/a.swift", "func f() {}\n", SWIFT_FUZZ_TARGETS), [False])
        prop = 'import SwiftCheck\nproperty("p") <- forAll { (x: Int) in true }\n'
        self.assertEqual(_marks("Tests/P.swift", prop, SWIFT_FUZZ_TARGETS, SWIFT_PROPERTY_TESTS), [False, True])

    def test_a_product_under_build_with_a_libfuzzer_option_is_a_heuristic_run(self) -> None:
        facts = Facts([])
        run = SWIFT_LIBFUZZER.claims(command(".build/debug/AppFuzz -max_total_time=30"), facts)
        self.assertTrue(run is not None and run.heuristic)
        self.assertIsNotNone(SWIFT_LIBFUZZER.claims(command(".build/release/AppFuzz corpus -runs=100"), facts))
        self.assertIsNone(SWIFT_LIBFUZZER.claims(command(".build/debug/AppFuzz"), facts))
        self.assertIsNone(SWIFT_LIBFUZZER.claims(command("./other/AppFuzz -max_total_time=30"), facts))
        build = "swift build -Xswiftc -sanitize=fuzzer --product AppFuzz"
        self.assertIsNone(SWIFT_LIBFUZZER.claims(command(build), facts))
