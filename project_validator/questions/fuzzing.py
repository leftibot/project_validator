"""The fuzz-testing question: for each language, in each unit of the project that has it, are there fuzz targets, and
does CI run them?"""

from dataclasses import dataclass

from project_validator.facts import ActionStep, Facts
from project_validator.facts.fuzzing import FUZZ, RUNS, property_kinds
from project_validator.facts.testing import TestFile
from project_validator.facts.tools import known_tools, within
from project_validator.questions import Answer, LanguageAnswers, Question, answer_dict, per_unit
from project_validator.questions.tooling import ToolAnswer, tool_answer

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


def _other_runs(facts: Facts, unit: str) -> tuple[str, ...]:
    """The runs of fuzzers that are not tools: each ClusterFuzzLite step CI has. `unit` filters nothing: a step is
    credited to every unit and language (Task 3 may refine this)."""
    steps = (step for step in facts.of(ActionStep) if step.uses.startswith(_CLUSTERFUZZLITE))
    return tuple(dict.fromkeys(f"CI ({step.origin.path}): {step.uses}" for step in steps))


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
            other_runs=_other_runs(facts, unit),
        ),
    )


FUZZ_QUESTION = Question(
    name="fuzz-testing",
    description="Are there fuzz targets for each language in each unit, and does CI run them?",
    answer=fuzzing,
)

__all__ = ["FUZZ_QUESTION", "FuzzAnswer", "fuzzing"]
