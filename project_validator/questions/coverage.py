"""The coverage question: for each language, in each unit of the project that has it, what coverage does CI report,
at each granularity?"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from project_validator.facts import Facts
from project_validator.facts.coverage import COVERAGE, Granularity
from project_validator.facts.tools import Tool, ToolRun, known_tools
from project_validator.questions import Answer, LanguageAnswers, Question, answer_dict, per_unit, runs_of, unknowns_for


@dataclass(frozen=True, slots=True, kw_only=True)
class GranularityAnswer:
    """`tools`: those CI runs that report it (for yes). `known`: how the known tools report it."""

    answer: Answer
    tools: tuple[str, ...] = ()
    known: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class CoverageAnswer:
    """The coverage of one language in one unit ("." for the project's root unit)."""

    language: str
    unit: str = "."
    granularities: Mapping[Granularity, GranularityAnswer]
    # What could not be read, for unknown answers: `subject: reason (origin)`.
    unknowns: tuple[str, ...] = ()

    def __getitem__(self, granularity: Granularity) -> GranularityAnswer:
        return self.granularities[granularity]

    def possible(self) -> tuple[Granularity, ...]:
        """The granularities a known tool can measure for the language, coarsest first."""
        return tuple(found for found, answer in self.granularities.items() if answer.answer is not Answer.IMPOSSIBLE)

    def tools_ran(self) -> tuple[str, ...]:
        """The names of every tool CI ran that reports some granularity, each once, in order."""
        return tuple(dict.fromkeys(tool for found in self.granularities.values() for tool in found.tools))

    def as_dict(self) -> dict[str, object]:
        return answer_dict(
            self,
            **{
                str(granularity): {"answer": str(found.answer), "tools": list(found.tools), "known": list(found.known)}
                for granularity, found in self.granularities.items()
            },
            unknowns=list(self.unknowns),
        )


type LanguageCoverage = LanguageAnswers[CoverageAnswer]


def measures_coverage(tool: Tool) -> bool:
    return COVERAGE in tool.can


def _answer(
    granularity: Granularity, runs: tuple[ToolRun, ...], known: tuple[Tool, ...], unread: bool
) -> GranularityAnswer:
    level = str(granularity)
    able = tuple(dict.fromkeys(tool.can[COVERAGE][level] for tool in known if level in tool.can[COVERAGE]))
    if not able:
        return GranularityAnswer(answer=Answer.IMPOSSIBLE)
    if tools := tuple(dict.fromkeys(run.tool for run in runs if level in run.provides[COVERAGE])):
        return GranularityAnswer(answer=Answer.YES, tools=tools, known=able)
    return GranularityAnswer(answer=Answer.UNKNOWN if unread else Answer.NO, known=able)


def coverage_answer(language: str, facts: Facts, tools: Iterable[Tool], unit: str = ".") -> CoverageAnswer:
    """What coverage CI reports for `language` in `unit`, by the facts, and what the known `tools` could report."""
    known = tuple(tool for tool in tools if measures_coverage(tool) and language in tool.languages)
    runs = runs_of(COVERAGE, language, unit, facts)
    unknowns = unknowns_for(known, facts)
    return CoverageAnswer(
        language=language,
        unit=unit,
        granularities={granularity: _answer(granularity, runs, known, bool(unknowns)) for granularity in Granularity},
        unknowns=unknowns,
    )


def language_coverage(language: str, facts: Facts) -> LanguageCoverage:
    tools = known_tools()
    return per_unit(language, facts, lambda unit: coverage_answer(language, facts, tools, unit))


COVERAGE_QUESTION = Question(
    name="coverage",
    description="What coverage does CI report for each language in each unit, at each granularity (line to path)?",
    answer=language_coverage,
)

__all__ = [
    "COVERAGE_QUESTION",
    "CoverageAnswer",
    "GranularityAnswer",
    "LanguageCoverage",
    "coverage_answer",
    "language_coverage",
    "measures_coverage",
]
