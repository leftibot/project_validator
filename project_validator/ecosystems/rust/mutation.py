"""Rust's mutation testing tool: cargo-mutants, configured in `.cargo/mutants.toml`."""

from project_validator.ecosystems.rust import RUST_LANGUAGE
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.arguments import has_option
from project_validator.facts.mutation import mutated, mutation_tool
from project_validator.facts.settings import file_reader
from project_validator.facts.tools import Run, defined_by, starts

CARGO_MUTANTS_SETTINGS = file_reader("cargo-mutants", (".cargo/mutants.toml",))


def _cargo_mutants(command: Command, _facts: Facts) -> Run | None:
    """`cargo mutants`, which mutates the changes in a diff only when given `--in-diff`."""
    if not starts(("cargo", "mutants"))(command):
        return None
    return mutated(incremental=has_option(resolved(command), "--in-diff"))


CARGO_MUTANTS = mutation_tool(
    name="cargo-mutants",
    languages=RUST_LANGUAGE,
    how="cargo mutants",
    runs=_cargo_mutants,
    defined=defined_by(files=(CARGO_MUTANTS_SETTINGS.name,)),
    incremental_how="cargo mutants --in-diff <changes.diff>",
)
