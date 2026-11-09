"""The support matrix: what each check recognises for each ecosystem, generated from the registry.

It is printed by `--support-matrix` and kept in docs/support-matrix.md.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from project_validator.components import known
from project_validator.core import Check
from project_validator.ecosystems import applies_to, registered
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.tools import Tool

type Cell = tuple[str, ...] | None  # tool names (maybe none) where the check applies; None where it does not

REGENERATE = "python -m project_validator --support-matrix > docs/support-matrix.md"
LEGEND = f"""\
What project_validator checks for each ecosystem, and the tools it recognises for it. Generated: regenerate with
`{REGENERATE}` (a test fails while this page is stale). A
cell lists the tools the check recognises; `✓` means the check applies without naming tools; `—` means it does not
apply.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class Row:
    check: str
    description: str
    cells: tuple[Cell, ...]  # one per ecosystem of the matrix


@dataclass(frozen=True, slots=True, kw_only=True)
class SupportMatrix:
    ecosystems: tuple[str, ...]  # labels, registration order
    rows: tuple[Row, ...]  # checks with languages, in the order given
    everywhere: tuple[str, ...]  # checks of every project, in the order given


def _cell(check: Check, ecosystem: Ecosystem) -> Cell:
    if ecosystem.label not in applies_to(check):
        return None
    return tuple(tool.name for tool in known(Tool) if check.aspect in tool.can and tool.languages & ecosystem.languages)


def support_matrix(checks: Sequence[Check]) -> SupportMatrix:
    """The support matrix of `checks` over the ecosystems now registered."""
    ecosystems = registered()
    rows = tuple(
        Row(check=check.name, description=check.description, cells=tuple(_cell(check, e) for e in ecosystems))
        for check in checks
        if check.languages
    )
    return SupportMatrix(
        ecosystems=tuple(e.label for e in ecosystems),
        rows=rows,
        everywhere=tuple(check.name for check in checks if not check.languages),
    )


def _render_cell(cell: Cell) -> str:
    if cell is None:
        return "—"
    return ", ".join(cell) if cell else "✓"


def render(matrix: SupportMatrix) -> str:
    """The matrix as the Markdown page docs/support-matrix.md."""
    lines = [
        "| Check | " + " | ".join(matrix.ecosystems) + " |",
        "|---|" + "---|" * len(matrix.ecosystems),
        *(f"| `{row.check}` | " + " | ".join(_render_cell(c) for c in row.cells) + " |" for row in matrix.rows),
    ]
    everywhere = ", ".join(f"`{name}`" for name in matrix.everywhere)
    footer = f"Checks of every project, whatever its languages: {everywhere}.\n"
    return "# Support matrix\n\n" + LEGEND + "\n" + "\n".join(lines) + "\n\n" + footer


def as_dict(matrix: SupportMatrix) -> dict[str, object]:
    """The matrix as JSON-ready data."""
    return {
        "ecosystems": list(matrix.ecosystems),
        "rows": [
            {
                "check": row.check,
                "description": row.description,
                "cells": {
                    label: None if cell is None else list(cell)
                    for label, cell in zip(matrix.ecosystems, row.cells, strict=True)
                },
            }
            for row in matrix.rows
        ],
        "everywhere": list(matrix.everywhere),
    }
