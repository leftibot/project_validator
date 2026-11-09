"""What every question about an aspect of the shared tool model asks, for one language in one unit: which known tools
provide the aspect, which of them CI runs and at which levels, where the project defines how they provide it, and what
could not be read. A practice's question is a declaration over this (see `aspect_answers`); its policy reads the
answer.

Coverage, whose levels are granularities with a ranking of their own, has its own answer
(`project_validator.questions.coverage`).
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from project_validator.facts import Facts
from project_validator.facts.roles import AUXILIARY, role
from project_validator.facts.structure import Unit
from project_validator.facts.tools import Tool, known_tools, owner, within
from project_validator.questions import Answer, LanguageAnswers, answer_dict, per_unit, runs_of, unknowns_for


@dataclass(frozen=True, slots=True, kw_only=True)
class KnownTool:
    """A known tool of the aspect: how it provides each level, whether it needs the project to define how (a style,
    its rules) because it has no default worth running, and whether it is required alongside the others (it finds
    what they do not)."""

    name: str
    can: Mapping[str, str]
    needs_definition: bool = False
    required: bool = False
    # What defines how it provides the aspect (`Test functions in *_test.go files`).
    describe: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class Ran:
    """A tool CI runs: the levels its runs provide, and the settings files they read to decide."""

    name: str
    levels: frozenset[str]
    read: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolAnswer:
    """Whether CI provides `aspect` at `level` for one language in one unit ("." for the project's root unit).

    `runs`: the tools CI runs, with the levels each provides there. `defined`: the files that define how a known tool
    provides the aspect (tool -> files), CI running it or not. `known`: every known tool of the aspect for the
    language."""

    aspect: str
    language: str
    unit: str = "."
    level: str
    answer: Answer
    runs: tuple[Ran, ...] = ()
    defined: tuple[tuple[str, tuple[str, ...]], ...] = ()
    known: tuple[KnownTool, ...] = ()
    unknowns: tuple[str, ...] = ()
    # The unknowns that may hide where a known tool is defined (settings that could not be read).
    unknown_definitions: tuple[str, ...] = ()

    def providing(self, level: str | None = None) -> tuple[str, ...]:
        """The tools CI runs that provide `level` (by default, the answer's)."""
        wanted = self.level if level is None else level
        return tuple(ran.name for ran in self.runs if wanted in ran.levels)

    def tools_ran(self) -> tuple[str, ...]:
        """The names of every tool CI ran for the aspect, each once, in order."""
        return tuple(dict.fromkeys(ran.name for ran in self.runs))

    def others(self) -> tuple[str, ...]:
        """The tools CI runs that do not provide the answer's level (a formatter that only rewrites files)."""
        return tuple(ran.name for ran in self.runs if self.level not in ran.levels)

    def read_by(self, tool: str) -> tuple[str, ...]:
        """The settings files CI's runs of `tool` read to decide what they provide."""
        return next((ran.read for ran in self.runs if ran.name == tool), ())

    def definitions(self, tools: Iterable[str] | None = None) -> tuple[str, ...]:
        """The files that define the aspect for `tools` (by default, every known tool)."""
        names = None if tools is None else set(tools)
        found = (path for name, paths in self.defined if names is None or name in names for path in paths)
        return tuple(dict.fromkeys(found))

    def undefined(self) -> tuple[str, ...]:
        """The tools CI runs at the answer's level that need a definition the project lacks."""
        needing = {tool.name for tool in self.known if tool.needs_definition} - {name for name, _ in self.defined}
        return tuple(name for name in self.providing() if name in needing)

    def required_idle(self) -> tuple[str, ...]:
        """The required tools CI does not run at the answer's level, when one is required."""
        providing = set(self.providing())
        return tuple(tool.name for tool in self.known if tool.required and tool.name not in providing)

    def how(self, level: str | None = None) -> tuple[str, ...]:
        """How each known tool provides `level` (by default, the answer's)."""
        wanted = self.level if level is None else level
        return tuple(tool.can[wanted] for tool in self.known if wanted in tool.can)

    def names(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.known)

    def as_dict(self) -> dict[str, object]:
        return answer_dict(
            self,
            self.answer,
            level=self.level,
            runs={ran.name: {"levels": sorted(ran.levels), "read": list(ran.read)} for ran in self.runs},
            defined={name: list(paths) for name, paths in self.defined},
            known={
                tool.name: {"can": dict(tool.can), "needs_definition": tool.needs_definition, "required": tool.required}
                for tool in self.known
            },
            unknowns=list(self.unknowns),
            unknown_definitions=list(self.unknown_definitions),
        )


def _relevant(path: str, unit: str) -> bool:
    """Whether a definition file applies to code in `unit`: tools look for theirs in a file's directory and the
    directories above it, so one at or above the unit applies to all of it, and one inside it to part of it, unless
    that part is auxiliary (an example's or the docs' own configuration) or vendored."""
    directory = str(PurePosixPath(path).parent)
    if within(unit, directory):
        return True
    return within(directory, unit) and role(path) not in AUXILIARY


def _runs(aspect: str, language: str, unit: str, facts: Facts) -> tuple[Ran, ...]:
    levels: dict[str, set[str]] = {}
    read: dict[str, dict[str, None]] = {}
    for run in runs_of(aspect, language, unit, facts):
        levels.setdefault(run.tool, set()).update(run.provides[aspect])
        read.setdefault(run.tool, {}).update(dict.fromkeys(run.read))
    return tuple(Ran(name=name, levels=frozenset(found), read=tuple(read[name])) for name, found in levels.items())


def _known(tool: Tool, aspect: str) -> KnownTool:
    return KnownTool(
        name=tool.name,
        can=tool.can[aspect],
        needs_definition=tool.needs_definition(aspect),
        required=aspect in tool.required,
        describe=definition.describe if (definition := tool.definitions.get(aspect)) is not None else "",
    )


type _Defined = tuple[tuple[str, tuple[str, ...]], ...]


def _test_unit_files(facts: Facts) -> Callable[[str], bool]:
    """Whether a file is in a unit of tests (a separate test project)."""
    units = {found.directory: found.role for found in facts.of(Unit)}
    return lambda path: units.get(owner(path, units), "product") == "test"


def _defined(aspect: str, known: tuple[Tool, ...], facts: Facts, unit: str) -> _Defined:
    """Each known tool whose definition a file that applies to `unit` holds, with those files."""
    in_test_unit = _test_unit_files(facts)

    def applies(tool: Tool, path: str) -> bool:
        definition = tool.definitions.get(aspect)
        return _relevant(path, unit) or (definition is not None and definition.from_test_units and in_test_unit(path))

    found = ((tool.name, tuple(path for path in tool.defined(aspect, facts) if applies(tool, path))) for tool in known)
    return tuple((name, paths) for name, paths in found if paths)


def tool_answer(
    aspect: str, level: str, language: str, facts: Facts, tools: Iterable[Tool], unit: str = "."
) -> ToolAnswer:
    """Whether CI provides `aspect` at `level` for `language` in `unit`, by the facts, and what the known `tools`
    could."""
    known = tuple(tool for tool in tools if aspect in tool.can and language in tool.languages)
    if not known:
        return ToolAnswer(aspect=aspect, language=language, unit=unit, level=level, answer=Answer.IMPOSSIBLE)
    runs = _runs(aspect, language, unit, facts)
    unknowns = unknowns_for(known, facts)
    provided = any(level in ran.levels for ran in runs)
    return ToolAnswer(
        aspect=aspect,
        language=language,
        unit=unit,
        level=level,
        answer=Answer.YES if provided else Answer.UNKNOWN if unknowns else Answer.NO,
        runs=runs,
        defined=_defined(aspect, known, facts, unit),
        known=tuple(_known(tool, aspect) for tool in known),
        unknowns=unknowns,
        unknown_definitions=unknowns_for(known, facts, hiding=("settings",)),
    )


type LanguageToolAnswers = LanguageAnswers[ToolAnswer]


def aspect_answers(aspect: str, level: str) -> Callable[[str, Facts], LanguageToolAnswers]:
    """For a language: whether CI provides `aspect` at `level` in each unit that has the language."""

    def answer(language: str, facts: Facts) -> LanguageToolAnswers:
        tools = known_tools()
        return per_unit(language, facts, lambda unit: tool_answer(aspect, level, language, facts, tools, unit))

    return answer


__all__ = ["KnownTool", "LanguageToolAnswers", "Ran", "ToolAnswer", "aspect_answers", "tool_answer"]
