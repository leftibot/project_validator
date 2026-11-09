"""The mutation aspect of tools: a mutation tool's run runs the project's code under mutation, and incrementally when it
can."""

import unittest

from project_validator.facts import Facts
from project_validator.facts.mutation import INCREMENTAL, MUTATION, RUNS, mutated, mutation_tool


class MutationAspectTests(unittest.TestCase):
    def test_a_tool_can_run_and_optionally_run_incrementally(self) -> None:
        tool = mutation_tool(name="x", languages=frozenset({"Python"}), how="x run", runs=lambda c, f: None)
        self.assertEqual(tool.can, {MUTATION: {RUNS: "x run"}})
        tool = mutation_tool(
            name="x",
            languages=frozenset({"Python"}),
            how="x run",
            runs=lambda c, f: None,
            incremental_how="x run --since",
        )
        self.assertEqual(tool.can[MUTATION], {RUNS: "x run", INCREMENTAL: "x run --since"})

    def test_a_tool_without_a_definition_defines_nothing(self) -> None:
        tool = mutation_tool(name="x", languages=frozenset({"Python"}), how="x", runs=lambda c, f: None)
        self.assertEqual(tool.defined(MUTATION, Facts()), ())

    def test_a_run_provides_runs_and_optionally_incremental(self) -> None:
        self.assertEqual(mutated().provides, {MUTATION: frozenset({RUNS})})
        self.assertEqual(mutated(incremental=True).provides, {MUTATION: frozenset({RUNS, INCREMENTAL})})
        self.assertTrue(mutated(heuristic=True).heuristic)
