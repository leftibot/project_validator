"""The fuzz aspect: fuzz targets and property tests as kinds of test file, and the fuzzers defined by them."""

import re
import unittest

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
