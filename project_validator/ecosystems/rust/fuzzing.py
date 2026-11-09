"""Rust fuzzing: cargo-fuzz (libFuzzer) and AFL.rs fuzz targets, and proptest and quickcheck property tests."""

import re

from project_validator.ecosystems.rust import RUST_LANGUAGE
from project_validator.ecosystems.rust.tools import _cargo
from project_validator.facts import Command, Facts
from project_validator.facts.fuzzing import FuzzTargets, PropertyTests, fuzzed, fuzzer
from project_validator.facts.tools import Run

RUST_FUZZ_TARGETS = FuzzTargets(
    name="cargo-fuzz or AFL.rs fuzz targets (fuzz_target! or afl::fuzz!)",
    languages=RUST_LANGUAGE,
    path=re.compile(r"\.rs$"),
    contains=re.compile(r"\bfuzz_target!\s*\(|\bafl::fuzz!\s*\("),
)
RUST_PROPERTY_TESTS = PropertyTests(
    name="proptest and quickcheck tests",
    languages=RUST_LANGUAGE,
    path=re.compile(r"\.rs$"),
    contains=re.compile(r"\bproptest!|#\[quickcheck\]"),
)


def _cargo_fuzz(command: Command, _facts: Facts) -> Run | None:
    """`cargo fuzz run <target>` and `cargo afl fuzz`, with or without a `+toolchain`."""
    fuzz = _cargo(command, "fuzz") or ()
    afl = _cargo(command, "afl") or ()
    return fuzzed() if fuzz[1:2] == ("run",) or afl[1:2] == ("fuzz",) else None


CARGO_FUZZ = fuzzer(
    name="cargo-fuzz",
    languages=RUST_LANGUAGE,
    how="cargo fuzz run <target> -- -max_total_time=60",
    runs=_cargo_fuzz,
    targets=(RUST_FUZZ_TARGETS,),
)
