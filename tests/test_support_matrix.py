import unittest

from project_validator.ecosystems import BUILT_IN, isolated_registry
from project_validator.plugins import discover
from project_validator.support_matrix import (
    LEGEND,
    REGENERATE,
    Cell,
    Row,
    SupportMatrix,
    as_dict,
    render,
    support_matrix,
)
from tests.support import ECOSYSTEM_PLUGIN, temp_project

SMALL = SupportMatrix(
    ecosystems=("A", "B"),
    rows=(
        Row(check="x", description="d", cells=(("t1", "t2"), None)),
        Row(check="y", description="e", cells=((), ())),
    ),
    everywhere=("z",),
)


class SupportMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(isolated_registry())
        with temp_project({"zig.py": ECOSYSTEM_PLUGIN}) as directory:
            plugins = discover([directory])
        self.matrix = support_matrix(plugins.checks)

    def _row(self, matrix: SupportMatrix, name: str) -> Row:
        return next(row for row in matrix.rows if row.check == name)

    def _cell(self, name: str, ecosystem: str) -> Cell:
        return self._row(self.matrix, name).cells[self.matrix.ecosystems.index(ecosystem)]

    def test_columns_are_the_registered_ecosystems_built_in_first(self) -> None:
        self.assertEqual(self.matrix.ecosystems, (*(e.label for e in BUILT_IN), "Zig"))

    def test_a_cell_names_the_tools_of_the_check_aspect_for_the_ecosystem(self) -> None:
        self.assertEqual(self._cell("code-formatting", "Zig"), ("zig fmt",))
        self.assertEqual(self._cell("code-formatting", "Python"), ("ruff format", "black"))

    def test_a_check_without_an_aspect_applies_without_tools(self) -> None:
        self.assertEqual(self._cell("committed-artifacts", "Python"), ())

    def test_a_check_that_does_not_apply_has_no_cell(self) -> None:
        self.assertIsNone(self._cell("ci-build-types", "Python"))
        self.assertEqual(self._cell("ci-build-types", "C/C++"), ())

    def test_checks_of_every_project_are_listed_apart(self) -> None:
        self.assertIn("ci-present", self.matrix.everywhere)
        self.assertNotIn("ci-present", [row.check for row in self.matrix.rows])

    def test_a_tool_with_several_aspects_is_named_once(self) -> None:
        ruby = self._cell("code-formatting", "Ruby")
        self.assertIsNotNone(ruby)
        names = ruby or ()
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("RuboCop", names)

    def test_rendering(self) -> None:
        self.assertIn(REGENERATE, LEGEND)
        self.assertEqual(
            render(SMALL),
            "# Support matrix\n\n"
            + LEGEND
            + "\n| Check | A | B |\n|---|---|---|\n| `x` | t1, t2 | — |\n| `y` | ✓ | ✓ |\n\n"
            + "Checks of every project, whatever its languages: `z`.\n",
        )

    def test_a_pipe_in_a_cell_is_escaped(self) -> None:
        matrix = SupportMatrix(
            ecosystems=("A",), rows=(Row(check="x", description="d", cells=(("a|b",),)),), everywhere=("z",)
        )
        self.assertIn("| `x` | a\\|b |\n", render(matrix))

    def test_without_checks_of_every_project_the_page_ends_with_the_table(self) -> None:
        matrix = SupportMatrix(ecosystems=("A",), rows=(Row(check="x", description="d", cells=((),)),), everywhere=())
        self.assertTrue(render(matrix).endswith("| `x` | ✓ |\n"))

    def test_as_dict(self) -> None:
        self.assertEqual(
            as_dict(SMALL),
            {
                "ecosystems": ["A", "B"],
                "rows": [
                    {"check": "x", "description": "d", "cells": {"A": ["t1", "t2"], "B": None}},
                    {"check": "y", "description": "e", "cells": {"A": [], "B": []}},
                ],
                "everywhere": ["z"],
            },
        )
