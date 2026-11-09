"""The fuzz aspect of tools (see `project_validator.facts.tools`): a fuzzer's run fuzzes the project's code.

Fuzz targets (a libFuzzer `LLVMFuzzerTestOneInput`, a Go `FuzzXxx`, an atheris or cargo-fuzz harness) and property-based
tests (Hypothesis, proptest, fast-check) are kinds of test file: a `FuzzTargets` or `PropertyTests` component says so,
and each file it matches is a `TestFile` fact. A fuzzer's `Definition` is where its fuzz targets are defined: the
`TestFile` facts of the fuzz-target kinds of its languages. Fuzzers are ordinary `Tool`s; `fuzzer` and `fuzzed` only
spell them.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import partial

from project_validator.components import known
from project_validator.facts import Facts, Setting
from project_validator.facts.testing import TestFile, TestFiles
from project_validator.facts.tools import Claim, Definition, Run, Tool, provided

FUZZ = "fuzz"
RUNS = "runs"


@dataclass(frozen=True, slots=True, kw_only=True)
class FuzzTargets(TestFiles):
    """A kind of test file that is a fuzz target: a harness a fuzzer runs on generated inputs."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PropertyTests(TestFiles):
    """A kind of test file of property-based tests: properties checked on generated inputs, not fuzzing targets."""


def known_fuzz_targets() -> tuple[FuzzTargets, ...]:
    return known(FuzzTargets)


def known_property_tests() -> tuple[PropertyTests, ...]:
    return known(PropertyTests)


def fuzz_kinds() -> frozenset[str]:
    """The names of the known kinds of fuzz target."""
    return frozenset(kind.name for kind in known_fuzz_targets())


def property_kinds() -> frozenset[str]:
    """The names of the known kinds of property-based test."""
    return frozenset(kind.name for kind in known_property_tests())


def _described(languages: frozenset[str], chosen: frozenset[str] | None) -> str:
    """The kinds a fuzzer is defined by, for findings: the known fuzz-target kinds of `languages`, as known now (a
    profile defines its kinds in its own modules), or `chosen`."""
    names = (
        sorted(kind.name for kind in known_fuzz_targets() if kind.languages & languages)
        if chosen is None
        else sorted(chosen)
    )
    return " or ".join(names) or "fuzz targets"


def _fuzz_targets(languages: frozenset[str], chosen: frozenset[str] | None, facts: Facts) -> Iterator[str]:
    """The paths of the test files of the fuzz-target kinds (`chosen`, else the known ones) of `languages`."""
    names = fuzz_kinds() if chosen is None else chosen
    return (test.origin.path for test in facts.of(TestFile) if test.kind in names and test.language in languages)


def fuzzer(
    *,
    name: str,
    languages: frozenset[str],
    how: str,
    runs: Claim,
    reads: tuple[str, ...] = (),
    kinds: Iterable[str] | None = None,
) -> Tool:
    """A fuzzer of `languages`: `how` to run it, and the fuzz targets it runs are the test files of the fuzz-target
    kinds of those languages. `kinds` (names of kinds) replaces the known fuzz-target kinds when given, for a fuzzer
    whose kinds a profile does not define."""
    chosen = None if kinds is None else frozenset(kinds)
    return Tool(
        name=name,
        languages=languages,
        can={FUZZ: {RUNS: how}},
        claims=runs,
        reads=reads,
        definitions={
            FUZZ: Definition(
                found=partial(_fuzz_targets, languages, chosen),
                default=False,
                describe=_described(languages, chosen),
                from_test_units=True,
            )
        },
    )


def fuzzed(*, read: Iterable[Setting | str] = (), heuristic: bool = False) -> Run:
    return provided(FUZZ, RUNS, read=read, heuristic=heuristic)


__all__ = [
    "FUZZ",
    "RUNS",
    "FuzzTargets",
    "PropertyTests",
    "fuzz_kinds",
    "fuzzed",
    "fuzzer",
    "known_fuzz_targets",
    "known_property_tests",
    "property_kinds",
]
