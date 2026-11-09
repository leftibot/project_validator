"""C and C++ mutation testing tools: Mull (its runners, or a build with its compiler plugin) and dextool mutate."""

from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.facts import Command, Facts
from project_validator.facts.build import CompilerOption
from project_validator.facts.mutation import mutated, mutation_tool
from project_validator.facts.settings import file_reader
from project_validator.facts.tools import Run, defined_by, starts, when

MULL_SETTINGS = file_reader("Mull", ("mull.yml",))
DEXTOOL_SETTINGS = file_reader("dextool mutate", (".dextool_mutate.toml",))

_MULL_PROGRAMS = starts(("mull-runner",), ("mull-cxx",))
_BUILDS = starts(("cmake", "--build"), ("make",), ("ninja",))


def _mull(command: Command, facts: Facts) -> Run | None:
    """`mull-runner` or `mull-cxx`; or a build, when the build compiles with Mull's plugin (`-fpass-plugin=...
    mull-ir-frontend...`), which then mutates and runs the tests as it builds (a heuristic)."""
    if _MULL_PROGRAMS(command):
        return mutated()
    if _BUILDS(command) and any("mull-ir-frontend" in option.option for option in facts.of(CompilerOption)):
        return mutated(heuristic=True)
    return None


MULL = mutation_tool(
    name="Mull",
    languages=C_AND_CXX.languages,
    how="mull-runner",
    runs=_mull,
    reads=("CMake",),
    defined=defined_by(files=(MULL_SETTINGS.name,)),
)
DEXTOOL = mutation_tool(
    name="dextool mutate",
    languages=C_AND_CXX.languages,
    how="dextool mutate",
    runs=when(starts(("dextool", "mutate")), mutated),
    defined=defined_by(files=(DEXTOOL_SETTINGS.name,)),
)
