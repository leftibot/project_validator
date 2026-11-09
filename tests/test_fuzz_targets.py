"""The repository's own atheris fuzz targets stay importable and total on garbage input."""

import contextlib
import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

FUZZ_DIRECTORY = Path(__file__).parent / "fuzz"


def stubbed_atheris() -> mock.MagicMock:
    atheris = mock.MagicMock()
    atheris.instrument_imports.side_effect = contextlib.nullcontext
    return atheris


def load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"fuzz_target_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FuzzTargetTests(unittest.TestCase):
    def test_every_target_exposes_test_one_input(self) -> None:
        paths = sorted(FUZZ_DIRECTORY.glob("fuzz_*.py"))
        self.assertEqual(len(paths), 6)
        for path in paths:
            with self.subTest(path.name), mock.patch.dict(sys.modules, {"atheris": stubbed_atheris()}):
                module = load_module(path)
                self.assertTrue(callable(module.TestOneInput))
                module.TestOneInput(b"")
                module.TestOneInput(b"{[(" * 50)

    def test_the_json_target_agrees_with_json_loads_on_non_finite_numbers_and_huge_integers(self) -> None:
        with mock.patch.dict(sys.modules, {"atheris": stubbed_atheris()}):
            module = load_module(FUZZ_DIRECTORY / "fuzz_json.py")
        for text in ("NaN", "[NaN, -Infinity]", "9" * 5000, "Infinity"):
            with self.subTest(text=text[:20]):
                module.TestOneInput(text.encode())

    def test_unittest_discovers_nothing_under_tests_fuzz(self) -> None:
        self.assertEqual(unittest.defaultTestLoader.discover(str(FUZZ_DIRECTORY)).countTestCases(), 0)
