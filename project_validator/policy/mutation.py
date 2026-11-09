"""The mutation testing policy: CI runs a mutation testing tool; running it on a pull request's changes only is a
bonus."""

from project_validator.core import Result
from project_validator.facts.mutation import INCREMENTAL, RUNS
from project_validator.policy import either, skipped_or_unknown, tools_ran
from project_validator.policy import files as files_listed
from project_validator.questions import Answer
from project_validator.questions.tooling import ToolAnswer


def _passed(answer: ToolAnswer) -> Result:
    ran = tools_ran(answer)
    if answer.providing(INCREMENTAL):
        return Result.passed(f"{ran}; on the pull request's changes only (bonus)")
    if ways := answer.how(INCREMENTAL):
        return Result.passed(ran, f"consider running it on the pull request's changes only: {either(ways)}")
    return Result.passed(ran)


def judge_mutation(answer: ToolAnswer, *, allow_unknown: bool = False) -> Result:
    """Mutation testing passes when CI runs a tool, with a bonus for the pull request's changes only; configured but
    not run, or no tool, warns. An unknown answer is an error unless `allow_unknown`."""
    hint = f"consider running {either(answer.how(RUNS))} in CI"
    settled = skipped_or_unknown(
        answer.answer,
        answer.unknowns,
        impossible=f"no known mutation testing tool handles {answer.language}",
        asks="whether CI runs mutation testing",
        hint=hint,
        allow_unknown=allow_unknown,
    )
    if settled is not None:
        return settled
    if answer.answer is Answer.YES:
        return _passed(answer)
    if configured := [name for name, _ in answer.defined]:
        idle = (
            f"{tool} is configured ({files_listed(answer.definitions((tool,)))}) but does not run"
            for tool in configured
        )
        return Result.warned("; ".join(idle), hint)
    return Result.warned("no mutation testing runs", hint)


__all__ = ["judge_mutation"]
