"""JavaScript and TypeScript fuzzing: Jazzer.js fuzz targets, and fast-check property tests."""

import re

from project_validator.ecosystems.javascript import JS_LANGUAGES
from project_validator.facts import Command
from project_validator.facts.fuzzing import FuzzTargets, PropertyTests, env_enabled, fuzzed, fuzzer
from project_validator.facts.tools import any_of, starts, when

JS_FUZZ_TARGETS = FuzzTargets(
    name="Jazzer.js fuzz targets (an exported fuzz function or .fuzz())",
    languages=JS_LANGUAGES,
    path=re.compile(r"\.(?:js|mjs|cjs|ts)$"),
    contains=re.compile(r"module\.exports\.fuzz\b|export\s+(?:async\s+)?function\s+fuzz\b|\.fuzz\("),
)
JS_PROPERTY_TESTS = PropertyTests(
    name="fast-check tests",
    languages=JS_LANGUAGES,
    path=re.compile(r"\.(?:js|mjs|cjs|ts|tsx|jsx)$"),
    contains=re.compile(r"fast-check|fc\.assert\("),
)


def _jest_fuzzing(command: Command) -> bool:
    """jest with `JAZZER_FUZZ` on: its `it.fuzz` tests then fuzz, rather than run their seed inputs."""
    return starts(("jest",))(command) and env_enabled(command, "JAZZER_FUZZ")


JAZZER_JS = fuzzer(
    name="Jazzer.js",
    languages=JS_LANGUAGES,
    how="npx jazzer <target> -- -max_total_time=30 (or jest with JAZZER_FUZZ=1)",
    runs=when(any_of(starts(("jazzer",)), _jest_fuzzing), fuzzed),
    targets=(JS_FUZZ_TARGETS,),
)
