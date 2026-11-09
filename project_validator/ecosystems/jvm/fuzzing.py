"""JVM fuzzing: Jazzer fuzz tests (JUnit `@FuzzTest` or `fuzzerTestOneInput`), and jqwik and junit-quickcheck property
tests."""

import re

from project_validator.ecosystems.jvm import JVM_LANGUAGES, build_steps
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.arguments import has_option
from project_validator.facts.fuzzing import FuzzTargets, PropertyTests, env_enabled, fuzzed, fuzzer
from project_validator.facts.tools import Run, starts

JVM_FUZZ_TARGETS = FuzzTargets(
    name="Jazzer fuzz tests (@FuzzTest or fuzzerTestOneInput)",
    languages=JVM_LANGUAGES,
    path=re.compile(r"\.(?:java|kt)$"),
    contains=re.compile(r"\bfuzzerTestOneInput\(|@FuzzTest\b"),
)
JVM_PROPERTY_TESTS = PropertyTests(
    name="jqwik and junit-quickcheck tests",
    languages=JVM_LANGUAGES,
    path=re.compile(r"\.(?:java|kt)$"),
    contains=re.compile(r"@Property\b|net\.jqwik|com\.pholser\.junit\.quickcheck"),
)

_TEST_STEPS = {"maven": {"test", "verify", "install"}, "gradle": {"test", "check", "build"}}


def _names_a_class_or_jar(command: Command) -> bool:
    """Whether a `jazzer` command is the JVM one: it names a target class or classpath, or a jar (Jazzer.js is given
    a JavaScript file)."""
    argv = resolved(command)
    return has_option(argv, "--target_class", "--cp", "-cp", "--classpath") or any(
        word.endswith(".jar") for word in argv[1:]
    )


def _jazzer(command: Command, _facts: Facts) -> Run | None:
    """The `jazzer` CLI, or a Maven or Gradle command that runs tests with `JAZZER_FUZZ` on (Jazzer's JUnit
    integration then fuzzes its `@FuzzTest` methods, which otherwise run their seed inputs only)."""
    if starts(("jazzer",))(command):
        return fuzzed() if _names_a_class_or_jar(command) else None
    steps = build_steps(command)
    if steps is None or not env_enabled(command, "JAZZER_FUZZ"):
        return None
    return fuzzed() if set(steps[1]) & _TEST_STEPS[steps[0]] else None


JAZZER = fuzzer(
    name="Jazzer",
    languages=JVM_LANGUAGES,
    how="mvn test or gradle test with JAZZER_FUZZ=1 (or the jazzer CLI)",
    runs=_jazzer,
    targets=(JVM_FUZZ_TARGETS,),
)
