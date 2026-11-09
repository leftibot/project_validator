"""Python's mutation testing tools (mutmut, cosmic-ray, mutatest), and the settings that configure mutmut."""

from collections.abc import Iterable

from project_validator.ecosystems.python import PYTHON_ONLY
from project_validator.facts import Command, Fact, Facts, resolved
from project_validator.facts.mutation import mutated, mutation_tool
from project_validator.facts.settings import SettingsReader, ini_settings, toml_settings
from project_validator.facts.tools import Run, defined_by, starts, when


def _read_mutmut(path: str, text: str) -> Iterable[Fact]:
    if path.endswith("pyproject.toml"):
        return toml_settings("mutmut", path, text, "tool", "mutmut")
    return ini_settings("mutmut", path, text, lambda section: "" if section == "mutmut" else None)


MUTMUT_SETTINGS = SettingsReader(name="mutmut", files=("pyproject.toml", "setup.cfg"), read=_read_mutmut)


def _names_mutants(argv: tuple[str, ...]) -> bool:
    """Whether `mutmut run`'s arguments name mutants: a word that is neither an option nor the value of the option
    before it (`--max-children 4`; only that one takes a value in mutmut 3, but any `--opt value` pair is read so)."""
    words = argv[2:]
    return any(
        not word.startswith("-") and not (index and words[index - 1].startswith("-") and "=" not in words[index - 1])
        for index, word in enumerate(words)
    )


def _mutmut(command: Command, _facts: Facts) -> Run | None:
    if not starts(("mutmut", "run"))(command):
        return None
    incremental = _names_mutants(resolved(command))
    return mutated(incremental=incremental, heuristic=incremental)


MUTMUT = mutation_tool(
    name="mutmut",
    languages=PYTHON_ONLY,
    how="mutmut run",
    runs=_mutmut,
    reads=("mutmut",),
    defined=defined_by(settings=("mutmut",)),
    incremental_how="mutmut run <module>.* for the changed modules",
)
COSMIC_RAY = mutation_tool(
    name="cosmic-ray",
    languages=PYTHON_ONLY,
    how="cosmic-ray exec",
    runs=when(starts(("cosmic-ray", "exec")), mutated),
)
MUTATEST = mutation_tool(
    name="mutatest", languages=PYTHON_ONLY, how="mutatest", runs=when(starts(("mutatest",)), mutated)
)
