"""Rust's mutation testing tool: cargo-mutants, configured in `.cargo/mutants.toml`."""

from project_validator.ecosystems.rust import RUST_LANGUAGE
from project_validator.facts.mutation import incremental_when, mutation_tool
from project_validator.facts.settings import file_reader
from project_validator.facts.tools import defined_by

CARGO_MUTANTS_SETTINGS = file_reader("cargo-mutants", (".cargo/mutants.toml",))


# `cargo mutants` mutates the changes in a diff only when given `--in-diff`.
_CARGO_MUTANTS = incremental_when("cargo", "mutants", options=("--in-diff",))


CARGO_MUTANTS = mutation_tool(
    name="cargo-mutants",
    languages=RUST_LANGUAGE,
    how="cargo mutants",
    runs=_CARGO_MUTANTS,
    defined=defined_by(files=(CARGO_MUTANTS_SETTINGS.name,)),
    incremental_how="cargo mutants --in-diff <changes.diff>",
)
