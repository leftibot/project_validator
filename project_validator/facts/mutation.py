"""The mutation aspect of tools (see `project_validator.facts.tools`): a run mutates the project's code and runs its
tests against the mutants, and incrementally when it can run only the code that changed. Mutation tools are ordinary
`Tool`s; `mutation_tool` and `mutated` only spell them."""

from collections.abc import Iterable

from project_validator.facts import NOTHING, Command, Facts, Setting, resolved
from project_validator.facts.arguments import has_option
from project_validator.facts.tools import Claim, Definition, Run, Tool, provided, starts

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


def incremental_when(*prefix: str, options: tuple[str, ...]) -> Claim:
    """A claim of the commands that start with `prefix`: a run, incrementally when one of `options` is given, alone,
    with a value (`--name=value`) or as `--name:value`."""
    starting = starts(prefix)

    def claim(command: Command, _facts: Facts) -> Run | None:
        if not starting(command):
            return None
        argv = resolved(command)
        return mutated(
            incremental=has_option(argv, *options) or any(word.partition(":")[0] in options for word in argv)
        )

    return claim


__all__ = ["INCREMENTAL", "MUTATION", "RUNS", "incremental_when", "mutated", "mutation_tool"]
