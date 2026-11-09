"""The fuzz aspect: fuzz targets and property tests as kinds of test file, and the fuzzers defined by them."""

import re
import unittest

from project_validator.ecosystems.python.fuzzing import ATHERIS, PYTHON_FUZZ_TARGETS, PYTHON_PROPERTY_TESTS
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
from tests.support import command, make_context, temp_project


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

    def test_a_path_with_an_unexpanded_expression_is_a_heuristic_run(self) -> None:
        for line in ("python tests/fuzz/${TARGET}", "python tests/fuzz/${{ matrix.target }}"):
            run = ATHERIS.claims(command(line), facts_of(PYTHON_PROJECT))
            self.assertTrue(run is not None and run.heuristic)
