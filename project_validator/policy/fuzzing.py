"""The fuzz-testing policy: the project has fuzz targets, and CI runs them."""

from project_validator.core import Result
from project_validator.facts.fuzzing import RUNS
from project_validator.policy import both, either, files, unknown
from project_validator.questions import Answer
from project_validator.questions.fuzzing import FuzzAnswer


def _no_targets(answer: FuzzAnswer) -> Result:
    """The result when no fuzz target is defined: a fuzzer CI runs without any recognised, property-based tests alone,
    or nothing."""
    hint = f"consider adding {either(answer.tools.how(RUNS))}"
    kinds = dict.fromkeys(tool.describe for tool in answer.tools.known if tool.describe)
    ran = (*answer.tools.providing(), *answer.other_runs)
    if ran:
        return Result.warned(
            f"CI runs {both(ran)}, but no fuzz targets were recognised ({either(kinds)})",
            f"consider adding a fuzz target ({either(kinds)})",
        )
    if answer.property_files:
        return Result.warned(f"only property-based tests ({files(answer.property_files)}); no fuzz targets", hint)
    return Result.failed(f"no fuzz targets found ({either(kinds)})" if kinds else "no fuzz targets found", hint)


def judge_fuzzing(answer: FuzzAnswer, *, allow_unknown: bool = False) -> Result:
    """Fuzz targets must exist (as each language's fuzzers define them) and CI must run them; targets CI never runs,
    or only property-based tests, warn. An unknown answer is an error unless `allow_unknown`."""
    tools = answer.tools
    if tools.answer is Answer.IMPOSSIBLE:
        return Result.skipped(f"no known fuzzer runs {answer.language}")
    targets = tools.definitions()
    if not targets and tools.unknown_definitions and not allow_unknown:
        return unknown("whether there are fuzz targets", tools.unknown_definitions)
    if not targets:
        return _no_targets(answer)
    found = f"fuzz targets in {len(targets)} file(s)"
    if answer.answer is Answer.YES:
        return Result.passed(f"{found}, run by {both((*tools.providing(), *answer.other_runs))}")
    if answer.answer is Answer.UNKNOWN and not allow_unknown:
        return unknown("whether CI runs the fuzz targets", tools.unknowns)
    return Result.warned(f"{found}, but no CI configuration runs {either(tools.how(RUNS))}")


__all__ = ["judge_fuzzing"]
