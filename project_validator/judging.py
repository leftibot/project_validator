"""Checks made of a question and its policy: each language the project uses is judged in each unit that has it, and
the results are named by language, by unit, or by both, as far as they differ.

One result stands for several (`combined`): what was skipped is left out unless everything was, one result is
said once when all agree, and otherwise each is labelled and the worst status wins.
"""

from collections.abc import Callable, Mapping
from dataclasses import replace

from project_validator.core import Check, Context, Placed, Result, Status
from project_validator.ecosystems import Ecosystem, ecosystems_for, registered
from project_validator.facts import Facts
from project_validator.facts.tools import handling
from project_validator.policy import Judge
from project_validator.questions import LanguageAnswers, RanTools, UnitAnswer


def labelled(results: Mapping[str, Result]) -> Result:
    """One result for several subjects, each named by its label: the worst status wins."""
    return Result(
        status=max((result.status for result in results.values()), key=lambda status: status.severity),
        message="; ".join(f"{label}: {result.message}" for label, result in results.items()),
        details=tuple(f"{label}: {detail}" for label, result in results.items() for detail in result.details),
    )


def combined[K](results: Mapping[K, Result], *, label: Callable[[K, tuple[K, ...]], str], none: str) -> Result:
    """One result for several subjects: skipped with `none` when there are none; the skipped ones left out, unless
    all are; the one result when all agree; otherwise each labelled (`label` is given the subject and every subject
    kept, to name it as far as it differs from the others) and the worst status wins."""
    if not results:
        return Result.skipped(none)
    if judged_ := {key: result for key, result in results.items() if result.status is not Status.SKIP}:
        results = judged_
    if len(set(results.values())) == 1:
        return next(iter(results.values()))
    kept = tuple(results)
    return labelled({label(key, kept): result for key, result in results.items()})


def by_ecosystem(results: Mapping[Ecosystem, Result]) -> Result:
    """One result for several ecosystems, labelled by ecosystem where they differ."""
    folded = combined(
        results, label=lambda ecosystem, _: ecosystem.label, none="no recognised ecosystem in the project"
    )
    places = tuple(
        replace(place, ecosystem=ecosystem.label)
        for ecosystem, result in results.items()
        for place in result.places or (Placed(ecosystem="", unit="", result=result),)
    )
    return replace(folded, places=places)


def check_each_ecosystem[Rules](
    context: Context, rules: Mapping[Ecosystem, Rules], judge: Callable[[Rules, Context], Result]
) -> Result:
    """Judge each ecosystem the project uses by its rules: the worst result wins, and findings are labelled."""
    used = ecosystems_for(context.structure.languages, rules)
    return by_ecosystem({ecosystem: judge(rules[ecosystem], context) for ecosystem in used})


type _Place = tuple[str, str]  # (language, unit)


def _label(place: _Place, places: tuple[_Place, ...]) -> str:
    """How a result is named among the others: by language, by unit, or by both, as far as they differ."""
    language, unit = place
    languages, units = {language for language, _ in places}, {unit for _, unit in places}
    where = "the root" if unit == "." else unit
    if len(units) == 1:
        return language
    return where if len(languages) == 1 else f"{language} in {where}"


def judged[A: UnitAnswer](
    languages: frozenset[str],
    context: Context,
    answers: Callable[[str, Facts], LanguageAnswers[A]],
    judge: Judge[A],
) -> Result:
    """The policy's judgement of each of `languages` the project uses, in each unit that has it; one result when they
    agree. A language the practice does not apply to (C in a C++ project) says nothing beside those it does.
    Places are named by `by_ecosystem`; a result returned from here alone has unnamed places."""
    found = [
        answer
        for language in sorted(languages & context.structure.languages)
        for answer in answers(language, context.facts).units
    ]
    results = {
        (answer.language, answer.unit): judge(answer, allow_unknown=context.options.allow_unknown) for answer in found
    }
    folded = combined(
        results, label=_label, none="only the docs, tooling, examples or test fixtures use these languages"
    )
    units = dict.fromkeys(unit for _, unit in results)
    return replace(folded, places=tuple(_placed(unit, results, found) for unit in units))


def _tools_ran(answer: object) -> tuple[str, ...]:
    """The tools CI ran for an answer, when it says (not every answer is about tools)."""
    return answer.tools_ran() if isinstance(answer, RanTools) else ()


def _placed[A: UnitAnswer](unit: str, results: Mapping[_Place, Result], found: list[A]) -> Placed:
    """One unit's result across the languages judged there, with the tools that ran for the practice in it."""
    here = {language: result for (language, where), result in results.items() if where == unit}
    return Placed(
        ecosystem="",
        unit=unit,
        result=combined(here, label=lambda language, _: language, none=""),
        tools=tuple(dict.fromkeys(tool for answer in found if answer.unit == unit for tool in _tools_ran(answer))),
    )


def answered_check[A: UnitAnswer](
    *,
    name: str,
    description: str,
    answers: Callable[[str, Facts], LanguageAnswers[A]],
    judge: Judge[A],
    aspect: str | None = None,
    languages: Callable[[], frozenset[str]] | None = None,
    aliases: tuple[str, ...] = (),
) -> Check:
    """A check that judges a question's answers by a policy, for each ecosystem the project uses (its findings
    labelled by ecosystem as other checks' are). It applies to the languages its known tools handle (`aspect`), or to
    `languages`."""
    if languages is None:
        if aspect is None:
            raise TypeError("answered_check needs an aspect or languages")
        languages = handling(aspect)
    handled = languages

    def run(context: Context) -> Result:
        now = handled()
        by_ecosystem_ = {e: e.languages & now for e in registered() if e.languages & now}
        return check_each_ecosystem(
            context, by_ecosystem_, lambda judged_languages, found: judged(judged_languages, found, answers, judge)
        )

    return Check(name=name, description=description, run=run, languages_from=handled, aspect=aspect, aliases=aliases)


__all__ = ["answered_check", "by_ecosystem", "check_each_ecosystem", "combined", "judged", "labelled"]
