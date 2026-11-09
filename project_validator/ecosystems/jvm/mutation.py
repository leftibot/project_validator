"""The JVM's mutation testing tool: PIT, run by its Maven goal or Gradle task, or by a build wiring it in."""

import re

from project_validator.ecosystems.jvm import JVM_LANGUAGES, Wiring, build_steps, plugin_definition, wired_run
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.arguments import has_option
from project_validator.facts.mutation import mutated, mutation_tool
from project_validator.facts.tools import Run

_WIRING = Wiring(
    report=re.compile(r"(?:org\.pitest:)?pitest(?:-maven)?(?::[^:]+)?:(?:scmM|m)utationCoverage|pitest"),
    maven_plugin="pitest-maven",
    bound_goal=re.compile(r"(?:scmM|m)utationCoverage"),
    # The plugin does not attach `pitest` to `check`; a project adds that link itself, which is recognised.
    gradle_plugin=None,
)
_INCREMENTAL_STEP = re.compile(r".*(?:scmMutationCoverage|withHistory)")


def _incremental(command: Command) -> bool:
    """`pitest:scmMutationCoverage` mutates the changed code only; `-DwithHistory` (Maven) skips the mutants whose
    code and tests are unchanged."""
    _kind, steps = build_steps(command) or ("", [])
    argv = resolved(command)
    return any(_INCREMENTAL_STEP.fullmatch(step) for step in steps) or has_option(argv, "-DwithHistory")


def _pit(command: Command, facts: Facts) -> Run | None:
    read = wired_run(_WIRING, command, facts)
    return None if read is None else mutated(incremental=_incremental(command), read=read)


PIT = mutation_tool(
    name="PIT",
    languages=JVM_LANGUAGES,
    how="pitest:mutationCoverage or the pitest Gradle task",
    runs=_pit,
    reads=("Maven", "Gradle"),
    defined=plugin_definition("pitest-maven", "info.solidsoft.pitest"),
    incremental_how="pitest:scmMutationCoverage",
)
