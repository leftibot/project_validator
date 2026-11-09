"""Policy: how answers (see `project_validator.questions`) are judged, one module per practice. Built in, apart from
`--allow-unknown`; kept apart from the questions so that it can be made configurable without touching extraction.

An unknown answer is a gap in the validator's tooling (configuration it cannot read), not a finding about the
project, so it is an error unless the user allows unknowns; then it is judged by what could be read.
"""

from collections.abc import Iterable
from typing import Protocol

from project_validator.core import Result, Status
from project_validator.questions import Answer
from project_validator.questions.tooling import ToolAnswer

_ALLOW_UNKNOWN = "--allow-unknown judges only what could be read"


class Judge[A](Protocol):
    """A policy: the judgement of one answer, erring on an unknown one unless `allow_unknown`."""

    def __call__(self, answer: A, /, *, allow_unknown: bool = ...) -> Result: ...


def unknown(message: str, unknowns: Iterable[str], *details: str) -> Result:
    """The error an unknown answer is: what could not be read, then what could."""
    return Result(
        status=Status.ERROR,
        message=f"{message} is unknown: some of what it runs could not be read",
        details=(*(f"not read: {found}" for found in unknowns), *details, _ALLOW_UNKNOWN),
    )


def skipped_or_unknown(
    answer: Answer,
    unknowns: Iterable[str],
    *,
    impossible: str,
    asks: str,
    hint: str | None = None,
    allow_unknown: bool,
) -> Result | None:
    """What settles an answer before a policy judges it: skipped when no known tool could provide it (`impossible`
    says so), an error when it is unknown and unknowns are not allowed (`asks` is what is left open, `hint` how to
    meet it); None when the policy is to judge it."""
    if answer is Answer.IMPOSSIBLE:
        return Result.skipped(impossible)
    if answer is Answer.UNKNOWN and not allow_unknown:
        return unknown(asks, unknowns, *(() if hint is None else (hint,)))
    return None


def either(items: Iterable[str]) -> str:
    """`a`, `a or b`, `a, b or c`."""
    items = list(items)
    return ", ".join(items[:-1]) + (" or " if len(items) > 1 else "") + (items[-1] if items else "")


def both(items: Iterable[str]) -> str:
    """`a`, `a and b`, `a, b and c`."""
    items = list(items)
    return ", ".join(items[:-1]) + (" and " if len(items) > 1 else "") + (items[-1] if items else "")


def files(paths: Iterable[str], shown: int = 3) -> str:
    """`a, b, c`, or the first `shown` and how many more."""
    paths = list(paths)
    more = len(paths) - shown
    return ", ".join(paths) if more <= 0 else f"{', '.join(paths[:shown])} and {more} more"


def alternatives(ways: Iterable[str]) -> str:
    """`a`, or `a (or b, c)`: the first way, and the others."""
    ways = list(ways)
    return ways[0] + (f" (or {either(ways[1:])})" if len(ways) > 1 else "") if ways else ""


def named_tool(answer: ToolAnswer, tool: str) -> str:
    """A tool, with the files that define it."""
    defined = answer.definitions((tool,))
    return f"{tool} ({files(defined)})" if defined else tool


def tools_ran(answer: ToolAnswer) -> str:
    """`a runs`, `a and b run`: the tools CI runs, each with the files that define it."""
    running = [named_tool(answer, tool) for tool in answer.providing()]
    return f"{both(running)} {'runs' if len(running) == 1 else 'run'}"


__all__ = [
    "Judge",
    "alternatives",
    "both",
    "either",
    "files",
    "named_tool",
    "skipped_or_unknown",
    "tools_ran",
    "unknown",
]
