"""The fuzz-testing question: for each language, in each unit of the project that has it, are there fuzz targets, and
does CI run them?"""

from collections.abc import Iterator
from dataclasses import dataclass

from project_validator.build_systems.cmake.conditions import LANGUAGE_NAMES
from project_validator.facts import ActionStep, Facts, Setting
from project_validator.facts.fuzzing import FUZZ, RUNS, property_kinds
from project_validator.facts.testing import TestFile
from project_validator.facts.tools import ToolRun, known_tools, within
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


def _ctest_fuzz_tests(facts: Facts, unit: str) -> Iterator[str]:
    """The CTest tests (registered by `add_test` in a CMake file of `unit`) whose name or command says `fuzz`, when
    CI runs ctest. A heuristic: ctest is not told which tests it runs, and a test is taken to fuzz by its words."""
    if not any(run.tool == "ctest" for run in facts.of(ToolRun)):
        return
    for setting in facts.where(Setting, tool="CTest", key="test"):
        words = setting.value if isinstance(setting.value, tuple) else ()
        if words and within(setting.origin.path, unit) and any("fuzz" in str(word).lower() for word in words):
            yield f"CTest ({setting.origin.path}): {words[0]}"


def _other_runs(facts: Facts, unit: str, language: str) -> tuple[str, ...]:
    """The runs of fuzzers that are not tools, each as written where it runs: each ClusterFuzzLite step CI has (which
    fuzzes any language, so it filters nothing), and, for a language CMake builds, each CTest fuzz test of `unit`'s
    CMake files when CI runs ctest (ctest runs the tests of whatever CMake builds, and no other language)."""
    steps = (step for step in facts.of(ActionStep) if step.uses.startswith(_CLUSTERFUZZLITE))
    found = (f"CI ({step.origin.path}): {step.uses}" for step in steps)
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
