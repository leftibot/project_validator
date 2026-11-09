"""Python's fuzzing: atheris fuzz targets, run as scripts, and Hypothesis property tests."""

import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from project_validator.ecosystems.python import _INTERPRETER_VALUES, _PYTHON, PYTHON_ONLY
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.arguments import program
from project_validator.facts.fuzzing import FuzzTargets, PropertyTests, fuzz_kinds, fuzzed, fuzzer
from project_validator.facts.testing import TestFile
from project_validator.facts.tools import Run

PYTHON_FUZZ_TARGETS = FuzzTargets(
    name="atheris fuzz targets (atheris.Setup or atheris.Fuzz)",
    languages=PYTHON_ONLY,
    path=re.compile(r"\.py$"),
    contains=re.compile(r"\batheris\.(?:Setup|Fuzz|instrument_imports)\b"),
)
PYTHON_PROPERTY_TESTS = PropertyTests(
    name="Hypothesis tests",
    languages=PYTHON_ONLY,
    path=re.compile(r"\.py$"),
    contains=re.compile(r"^\s*from hypothesis import|^\s*import hypothesis\b|@given\(", re.MULTILINE),
)


def _script(argv: tuple[str, ...]) -> str | None:
    """The script `python` runs: its first argument that is not an option (or an option's value); None when it
    runs a module or a command (`-m`, `-c`) instead."""
    words = iter(argv[1:])
    for word in words:
        if word in _INTERPRETER_VALUES:
            next(words, None)
        elif word.startswith(("-m", "-c")):
            return None
        elif not word.startswith("-"):
            return _whole_expression(word, words)
    return None


def _whole_expression(word: str, rest: Iterator[str]) -> str:
    """`word`, with the words after it that the shell split an expression (`${{ matrix.target }}`) into."""
    found = [word]
    while "${{" in " ".join(found) and "}}" not in found[-1]:
        following = next(rest, None)
        if following is None:
            break
        found.append(following)
    return " ".join(found)


def _normalised(command: Command, path: str) -> str:
    joined = PurePosixPath(command.directory or ".") / path
    return PurePosixPath(*[part for part in joined.parts if part != "."]).as_posix() or "."


def _runs_target(command: Command, facts: Facts) -> Run | None:
    """`python <fuzz target>.py ...`: the script is a fuzz target's file. A path holding an expression the validator
    cannot evaluate is taken to be one, as a heuristic, only when it names fuzzing (`fuzz` in the path)."""
    argv = resolved(command)
    if not argv or not _PYTHON.fullmatch(program(argv)):
        return None
    script = _script(argv)
    if script is None:
        return None
    if "${" in script or "$(" in script:
        return fuzzed(heuristic=True) if "fuzz" in script.lower() else None
    path = _normalised(command, script.replace("\\", "/"))
    targets = {test.origin.path for test in facts.of(TestFile) if test.kind in fuzz_kinds()}
    return fuzzed() if path in targets else None


ATHERIS = fuzzer(
    name="atheris",
    languages=PYTHON_ONLY,
    how="python <fuzz target>.py",
    runs=_runs_target,
    targets=(PYTHON_FUZZ_TARGETS,),
)
