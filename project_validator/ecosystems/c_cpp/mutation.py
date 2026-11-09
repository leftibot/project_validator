"""C and C++ mutation testing tools: Mull (`mull-runner` or `mull-cxx`) and dextool mutate.

Mull's compiler plugin only embeds the mutants, so a build with it alone is not a run."""

from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.facts.mutation import mutated, mutation_tool
from project_validator.facts.settings import file_reader
from project_validator.facts.tools import defined_by, starts, when

MULL_SETTINGS = file_reader("Mull", ("mull.yml",))
DEXTOOL_SETTINGS = file_reader("dextool mutate", (".dextool_mutate.toml",))

MULL = mutation_tool(
    name="Mull",
    languages=C_AND_CXX.languages,
    how="mull-runner",
    runs=when(starts(("mull-runner",), ("mull-cxx",)), mutated),
    defined=defined_by(files=(MULL_SETTINGS.name,)),
)
DEXTOOL = mutation_tool(
    name="dextool mutate",
    languages=C_AND_CXX.languages,
    how="dextool mutate",
    runs=when(starts(("dextool", "mutate")), mutated),
    defined=defined_by(files=(DEXTOOL_SETTINGS.name,)),
)
