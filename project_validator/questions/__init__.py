"""Questions: queries over the fact database, each answering one thing about the project per language, in each unit
of the project that has the language.

Answers are the stable, machine-readable interface (`--answers`); checks judge them by a policy and never read
extractors (see docs/architecture.md). What every question needs (the units of a language, the runs of an aspect in
a unit, the unknowns that matter to some tools) is here, once.
"""

import enum
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from project_validator.components import known
from project_validator.facts import Facts, Unknown
from project_validator.facts.roles import AUXILIARY, role
from project_validator.facts.structure import Unit
from project_validator.facts.tools import Tool, ToolRun


class Answer(enum.StrEnum):
    """`impossible`: no known tool can provide it for the language. `unknown`: something that could provide it was
    not read (see `project_validator.facts.Unknown`)."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"
    IMPOSSIBLE = "impossible"


class Answered(Protocol):
    def as_dict(self) -> dict[str, object]: ...


@runtime_checkable
class RanTools(Protocol):
    def tools_ran(self) -> tuple[str, ...]:
        """The names of every tool CI ran for the practice in this unit, each once, in order."""
        ...


class UnitAnswer(Answered, Protocol):
    @property
    def unit(self) -> str: ...

    @property
    def language(self) -> str: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class LanguageAnswers[A: UnitAnswer]:
    """A question's answers for one language, one per unit of the project that has it."""

    language: str
    units: tuple[A, ...]

    def as_dict(self) -> dict[str, object]:
        return {"language": self.language, "units": [unit.as_dict() for unit in self.units]}


def units_of(language: str, facts: Facts) -> tuple[str, ...]:
    """The product units of the project that have `language`: none when the language is only in its docs, tooling,
    examples, benchmarks or test fixtures. A project with no product unit at all (only scripts, say) is all product;
    a project with no units is one, its root."""
    units = facts.of(Unit)
    product = [unit for unit in units if unit.role == "product"] or [unit for unit in units if unit.role != "vendored"]
    return tuple(unit.directory for unit in product if language in unit.languages) if units else (".",)


def per_unit[A: UnitAnswer](language: str, facts: Facts, answer: Callable[[str], A]) -> LanguageAnswers[A]:
    """The answer for `language` in each unit that has it."""
    return LanguageAnswers(language=language, units=tuple(answer(unit) for unit in units_of(language, facts)))


def _auxiliary(run: ToolRun, unit_role: str) -> bool:
    """Whether a run is only in auxiliary code (tsc in `examples/app`), which says nothing about a unit of another
    role."""
    roles = {role(scope, directory=True) for scope in run.scope}
    return bool(roles) and roles <= AUXILIARY and unit_role not in roles


def runs_of(aspect: str, language: str, unit: str, facts: Facts) -> tuple[ToolRun, ...]:
    """The runs CI makes of tools that provide `aspect` for `language` in `unit` (see `ToolRun.covers`), but runs
    only in its auxiliary code (examples, docs, tooling)."""
    units = [found.directory for found in facts.of(Unit)] or ["."]
    unit_role = next((found.role for found in facts.of(Unit) if found.directory == unit), "product")
    return tuple(
        run
        for run in facts.of(ToolRun)
        if aspect in run.provides
        and language in run.languages
        and run.covers(unit, units)
        and not _auxiliary(run, unit_role)
    )


def unknowns_for(
    tools: Iterable[Tool],
    facts: Facts,
    *,
    hiding: Iterable[str] = ("jobs", "commands", "settings"),
    reads: Iterable[str] = (),
) -> tuple[str, ...]:
    """What was not read that may hide a run (a job or a command), or the settings the `tools` read (or those of
    `reads`, for a question that reads settings without a tool), as `subject: reason (origin)`; only what may hide one
    of `hiding`."""
    read = {name for tool in tools for name in (tool.name, *tool.reads)} | set(reads)
    kinds = frozenset(hiding)
    return tuple(
        f"{fact.subject}: {fact.reason} ({fact.origin})"
        for fact in facts.of(Unknown)
        if fact.hides in kinds and (fact.hides != "settings" or read & set(fact.tools))
    )


def answer_dict(answer: UnitAnswer, verdict: Answer | None = None, /, **fields: object) -> dict[str, object]:
    """An answer as JSON-ready data: its language and unit, its verdict when it has one, then its own `fields`."""
    found: dict[str, object] = {"language": answer.language, "unit": answer.unit}
    if verdict is not None:
        found["answer"] = str(verdict)
    return {**found, **fields}


@dataclass(frozen=True, slots=True, kw_only=True)
class Question:
    """A question about the project, answered per language from the facts. Questions are found, never listed."""

    name: str
    description: str
    answer: Callable[[str, Facts], Answered]


def known_questions() -> tuple[Question, ...]:
    """Every question defined by a module of `project_validator.questions`."""
    return known(Question)


__all__ = [
    "Answer",
    "Answered",
    "LanguageAnswers",
    "Question",
    "RanTools",
    "UnitAnswer",
    "answer_dict",
    "known_questions",
    "per_unit",
    "runs_of",
    "units_of",
    "unknowns_for",
]
