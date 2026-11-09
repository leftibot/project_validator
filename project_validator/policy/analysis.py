"""The static analysis and type checking policies: CI runs an analyzer (every required one, with its checks defined)
and a type checker; strict type checking is a bonus."""

from project_validator.core import Result
from project_validator.facts.analysis import CHECKS, Strictness
from project_validator.policy import both, either, skipped_or_unknown, tools_ran
from project_validator.policy import files as files_listed
from project_validator.questions import Answer
from project_validator.questions.tooling import ToolAnswer


def _idle(answer: ToolAnswer, tools: tuple[str, ...]) -> list[str]:
    """Each of `tools`, which CI does not run, as configured or not."""
    return [
        f"{tool} is configured ({files_listed(files)}) but does not run"
        if (files := answer.definitions((tool,)))
        else f"{tool} does not run"
        for tool in tools
    ]


def _analysis_hint(answer: ToolAnswer) -> str:
    ways = answer.how(CHECKS)
    joined = both(ways) if any(tool.required for tool in answer.known) else either(ways)
    return f"consider running {joined} in CI"


def judge_analysis(answer: ToolAnswer, *, allow_unknown: bool = False) -> Result:
    """Static analysis passes when CI runs an analyzer, and every required one, with its checks defined where it has
    no defaults of its own; defined but not run warns. An unknown answer is an error unless `allow_unknown`."""
    hint = _analysis_hint(answer)
    settled = skipped_or_unknown(
        answer.answer,
        answer.unknowns,
        impossible=f"no known static analyzer handles {answer.language}",
        asks="whether CI runs a static analyzer",
        hint=hint,
        allow_unknown=allow_unknown,
    )
    if settled is not None:
        return settled
    if answer.answer is Answer.YES:
        undefined = answer.undefined()
        defaults = (f"{tool} has no configuration of its checks, so it runs only its defaults" for tool in undefined)
        problems = [*_idle(answer, answer.required_idle()), *defaults]
        if problems:
            return Result.warned(f"{tools_ran(answer)}, but {'; '.join(problems)}", hint)
        return Result.passed(tools_ran(answer))
    if configured := [name for name, _ in answer.defined]:
        return Result.warned("; ".join(_idle(answer, tuple(configured))), hint)
    return Result.failed("no static analyzer runs", hint)


def judge_type_checking(answer: ToolAnswer, *, allow_unknown: bool = False) -> Result:
    """Type checking passes when CI runs a type checker, and strict mode is a bonus; configured but not run warns. An
    unknown answer is an error unless `allow_unknown`."""
    hint = f"consider running a type checker in CI: {either(answer.how(Strictness.CHECKS))}"
    settled = skipped_or_unknown(
        answer.answer,
        answer.unknowns,
        impossible=f"no known type checker handles {answer.language}",
        asks="whether CI runs a type checker",
        hint=hint,
        allow_unknown=allow_unknown,
    )
    if settled is not None:
        return settled
    if answer.answer is Answer.YES:
        if strict := answer.providing(Strictness.STRICT):
            where = (f"{tool} ({files_listed(read)})" if (read := answer.read_by(tool)) else tool for tool in strict)
            return Result.passed(f"{tools_ran(answer)}; strict mode bonus: {', '.join(where)}")
        return Result.passed(
            tools_ran(answer), f"consider enabling strict mode: {either(answer.how(Strictness.STRICT))}"
        )
    if configured := [name for name, _ in answer.defined]:
        return Result.warned("; ".join(_idle(answer, tuple(configured))), hint)
    return Result.failed("no type checker runs", hint)


__all__ = ["judge_analysis", "judge_type_checking"]
