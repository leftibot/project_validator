"""The fuzz-testing question: for each language, in each unit of the project that has it, are there fuzz targets, and
does CI run them?"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from project_validator.build_systems.cmake.conditions import LANGUAGE_NAMES
from project_validator.build_systems.cmake.ctest import CTEST
from project_validator.facts import ActionStep, Command, Facts, Setting, resolved
from project_validator.facts.arguments import option_values, starts_with
from project_validator.facts.fuzzing import FUZZ, LIBFUZZER_OPTION, RUNS, property_kinds
from project_validator.facts.testing import TestFile
from project_validator.facts.tools import known_tools, within
from project_validator.questions import Answer, LanguageAnswers, Question, answer_dict, per_unit
from project_validator.questions.tooling import ToolAnswer, tool_answer

CMAKE_LANGUAGES = frozenset(LANGUAGE_NAMES.values())
_CLUSTERFUZZLITE = "google/clusterfuzzlite/actions/run_fuzzers"


@dataclass(frozen=True, slots=True, kw_only=True)
class FuzzAnswer:
    """Whether fuzz targets exist for one language in one unit and CI runs them. `tools`: what the known fuzzers
    run and define. `property_files`: the property-based test files (not fuzz targets). `other_runs`: runs of fuzzers
    that are not tools (a ClusterFuzzLite action), each as written where it runs."""

    tools: ToolAnswer
    property_files: tuple[str, ...]
    other_runs: tuple[str, ...]

    @property
    def language(self) -> str:
        return self.tools.language

    @property
    def unit(self) -> str:
        return self.tools.unit

    @property
    def answer(self) -> Answer:
        if self.tools.answer is Answer.YES or (self.other_runs and self.tools.definitions()):
            return Answer.YES
        return self.tools.answer

    def as_dict(self) -> dict[str, object]:
        return answer_dict(
            self,
            self.answer,
            tools=self.tools.as_dict(),
            property_files=list(self.property_files),
            other_runs=list(self.other_runs),
        )


_LIBFUZZER_EXPRESSION = re.compile(
    r"\$.*(?:max_total_time|runs|max_len|jobs)|(?:max_total_time|runs|max_len|jobs)=.*\$"
)
_INCLUDING = ("-R", "--tests-regex", "-L", "--label-regex")
_EXCLUDING = ("-E", "--exclude-regex", "-LE", "--label-exclude")


def _fuzzes(words: tuple[str, ...]) -> bool:
    """Whether a registered test's command words pass a libFuzzer option (`-max_total_time=10`), or an expression
    (`${FUZZ_ARGS}` is not one; `-max_total_time=${SECONDS}` and `${max_total_time}` are) that names one."""
    return any(LIBFUZZER_OPTION.fullmatch(word) or _LIBFUZZER_EXPRESSION.search(word) for word in words)


def _matches(regex: str, name: str) -> bool:
    """Whether ctest's regular expression finds `name`; one that cannot be read, or that names a variable, is taken
    to match, as the filter cannot be told."""
    if "$" in regex:
        return True
    try:
        return re.search(regex, name) is not None
    except re.error:
        return True


def _runs_test(command: Command, name: str) -> bool:
    """Whether a command that runs ctest runs the test `name`: `-R` and `-L` regexes (each) must find its name (the
    labels are not read, so `-L` is taken to name the test too), and `-E` and `-LE` regexes must not."""
    argv = resolved(command)
    if not starts_with(argv, ("ctest",)):
        return True  # cmake --build --target test, or a workflow: no filter is read
    including = option_values(argv, *_INCLUDING)
    excluding = option_values(argv, *_EXCLUDING)
    return all(_matches(regex, name) for regex in including) and not any(
        "$" not in regex and _matches(regex, name) for regex in excluding
    )


def _ctest_commands(facts: Facts) -> tuple[Command, ...]:
    """The commands CI runs that run ctest."""
    return tuple(command for command in facts.of(Command) if CTEST.claims(command, facts) is not None)


def _ctest_fuzz_tests(facts: Facts, unit: str) -> Iterator[str]:
    """The CTest tests (registered by `add_test` in a CMake file of `unit`) that pass a libFuzzer option to their
    command, when a CI command runs ctest and its filters do not leave the test out. A heuristic: the registration
    may be behind a CMake option CI does not turn on."""
    commands = _ctest_commands(facts)
    if not commands:
        return
    for setting in facts.where(Setting, tool="CTest", key="test"):
        words = setting.value if isinstance(setting.value, tuple) else ()
        if (
            words
            and within(setting.origin.path, unit)
            and _fuzzes(tuple(str(word) for word in words[1:]))
            and any(_runs_test(command, str(words[0])) for command in commands)
        ):
            yield f"CTest ({setting.origin.path}): {words[0]}"


def _other_runs(facts: Facts, unit: str, language: str) -> tuple[str, ...]:
    """The runs of fuzzers that are not tools, each as written where it runs: each ClusterFuzzLite step CI has (which
    fuzzes any language, so it filters nothing), and, for a language CMake builds, each CTest fuzz test of `unit`'s
    CMake files when CI runs ctest (ctest runs the tests of only the languages CMake builds)."""
    steps = (step for step in facts.of(ActionStep) if step.uses.startswith(_CLUSTERFUZZLITE))
    found = (f"ClusterFuzzLite ({step.origin.path})" for step in steps)
    ctest = _ctest_fuzz_tests(facts, unit) if language in CMAKE_LANGUAGES else ()
    return tuple(dict.fromkeys((*found, *ctest)))


def _property_files(language: str, facts: Facts, unit: str) -> tuple[str, ...]:
    kinds = property_kinds()
    found = (
        test.origin.path
        for test in facts.of(TestFile)
        if test.language == language and test.kind in kinds and within(test.origin.path, unit)
    )
    return tuple(dict.fromkeys(found))


def fuzzing(language: str, facts: Facts) -> LanguageAnswers[FuzzAnswer]:
    tools = known_tools()
    return per_unit(
        language,
        facts,
        lambda unit: FuzzAnswer(
            tools=tool_answer(FUZZ, RUNS, language, facts, tools, unit),
            property_files=_property_files(language, facts, unit),
            other_runs=_other_runs(facts, unit, language),
        ),
    )


FUZZ_QUESTION = Question(
    name="fuzz-testing",
    description="Are there fuzz targets for each language in each unit, and does CI run them?",
    answer=fuzzing,
)

__all__ = ["FUZZ_QUESTION", "FuzzAnswer", "fuzzing"]
