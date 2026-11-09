"""The fuzz aspect of tools (see `project_validator.facts.tools`): a fuzzer's run fuzzes the project's code.

Fuzz targets (a libFuzzer `LLVMFuzzerTestOneInput`, a Go `FuzzXxx`, an atheris or cargo-fuzz harness) and property-based
tests (Hypothesis, proptest, fast-check) are kinds of test file: a `FuzzTargets` or `PropertyTests` component says so,
and each file it matches is a `TestFile` fact. A fuzzer's `Definition` is where its fuzz targets are defined: the
`TestFile` facts of the fuzz-target kinds the profile passes to `fuzzer` (as `test_runner` takes its `tests`). Fuzzers
are ordinary `Tool`s; `fuzzer` and `fuzzed` only spell them.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import partial

from project_validator.components import known
from project_validator.facts import Command, Facts, Setting
from project_validator.facts.testing import TestFile, TestFiles
from project_validator.facts.tools import Claim, Definition, Run, Tool, provided

FUZZ = "fuzz"
RUNS = "runs"
LIBFUZZER_OPTION = re.compile(r"-(?:max_total_time|runs|max_len|jobs)=\d+")


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


def _fuzz_targets(names: frozenset[str], facts: Facts) -> Iterator[str]:
    """The paths of the test files of the fuzz-target kinds `names`."""
    return (test.origin.path for test in facts.of(TestFile) if test.kind in names)


def fuzzer(
    *,
    name: str,
    languages: frozenset[str],
    how: str,
    runs: Claim,
    targets: Iterable[FuzzTargets],
    reads: tuple[str, ...] = (),
) -> Tool:
    """A fuzzer of `languages`: `how` to run it, and the fuzz targets it runs are the test files of the fuzz-target
    kinds `targets`, which the profile passes (the registry is not consulted here: profiles call this at import)."""
    kinds = tuple(targets)
    names = frozenset(kind.name for kind in kinds)

    return Tool(
        name=name,
        languages=languages,
        can={FUZZ: {RUNS: how}},
        claims=runs,
        reads=reads,
        definitions={
            FUZZ: Definition(
                found=partial(_fuzz_targets, names),
                default=False,
                describe=" or ".join(kind.name for kind in kinds),
                from_test_units=True,
            )
        },
    )


_FALSE = frozenset({"", "0", "false", "no", "off"})


def env_enabled(command: Command, name: str) -> bool:
    """Whether the command's environment turns the variable `name` on (set to anything but a false value)."""
    return command.env.get(name, "0").strip().lower() not in _FALSE


def fuzzed(*, read: Iterable[Setting | str] = (), heuristic: bool = False) -> Run:
    return provided(FUZZ, RUNS, read=read, heuristic=heuristic)


__all__ = [
    "FUZZ",
    "RUNS",
    "FuzzTargets",
    "PropertyTests",
    "env_enabled",
    "fuzz_kinds",
    "fuzzed",
    "fuzzer",
    "known_fuzz_targets",
    "known_property_tests",
    "property_kinds",
]
