"""The mutation aspect of tools (see `project_validator.facts.tools`): a run mutates the project's code and runs its
tests against the mutants, and incrementally when it can run only the code that changed. Mutation tools are ordinary
`Tool`s; `mutation_tool` and `mutated` only spell them."""

from collections.abc import Iterable

from project_validator.facts import NOTHING, Setting
from project_validator.facts.tools import Claim, Definition, Run, Tool, provided

MUTATION = "mutation"
RUNS = "runs"
INCREMENTAL = "incremental"


def mutation_tool(
    *,
    name: str,
    languages: frozenset[str],
    how: str,
    runs: Claim,
    reads: tuple[str, ...] = (),
    defined: Definition | None = None,
    incremental_how: str = "",
) -> Tool:
    """A mutation tool of `languages`: `how` to run it, and `incremental_how` to run it on the changed code only."""
    levels = {RUNS: how, **({INCREMENTAL: incremental_how} if incremental_how else {})}
    return Tool(
        name=name,
        languages=languages,
        can={MUTATION: levels},
        claims=runs,
        reads=reads,
        definitions={MUTATION: defined} if defined else NOTHING,
    )


def mutated(*, incremental: bool = False, read: Iterable[Setting | str] = (), heuristic: bool = False) -> Run:
    return provided(MUTATION, RUNS, INCREMENTAL if incremental else None, read=read, heuristic=heuristic)


__all__ = ["INCREMENTAL", "MUTATION", "RUNS", "mutated", "mutation_tool"]
