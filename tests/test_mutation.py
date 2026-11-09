"""The mutation aspect of tools: a mutation tool's run runs the project's code under mutation, and incrementally when it
can."""

import unittest
from collections.abc import Mapping

from project_validator.ecosystems.python.mutation import COSMIC_RAY, MUTATEST, MUTMUT
from project_validator.facts import Facts
from project_validator.facts.mutation import INCREMENTAL, MUTATION, RUNS, mutated, mutation_tool
from project_validator.facts.tools import Run, ToolRun
from tests.support import command, github_job, make_context, temp_project


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


def ci_tool_runs(files: dict[str, str]) -> tuple[ToolRun, ...]:
    with temp_project(files) as root:
        return make_context(root).facts.of(ToolRun)


def settings_facts_of(files: dict[str, str]) -> Facts:
    with temp_project(files) as root:
        return make_context(root).facts


def provided(run: Run | None) -> Mapping[str, frozenset[str]]:
    if run is None:
        raise AssertionError("no run claimed")
    return run.provides


class PythonMutationTests(unittest.TestCase):
    def test_mutmut_run_is_a_run(self) -> None:
        run = MUTMUT.claims(command("mutmut run"), Facts())
        self.assertEqual(provided(run), {MUTATION: frozenset({RUNS})})

    def test_mutmut_run_with_mutant_names_is_incremental_and_heuristic(self) -> None:
        run = MUTMUT.claims(command("mutmut run 'project_validator.text.*'"), Facts())
        self.assertEqual(provided(run)[MUTATION], frozenset({RUNS, INCREMENTAL}))
        self.assertTrue(run and run.heuristic)
        for line in ("mutmut run --max-children 4", "mutmut run --max-children=4"):
            plain = MUTMUT.claims(command(line), Facts())
            self.assertEqual(provided(plain)[MUTATION], frozenset({RUNS}), line)

    def test_mutmut_other_subcommands_are_not_runs(self) -> None:
        for line in ("mutmut results", "mutmut show 3", "mutmut browse"):
            self.assertIsNone(MUTMUT.claims(command(line), Facts()), line)

    def test_mutmut_through_a_launcher(self) -> None:
        self.assertIsNotNone(MUTMUT.claims(command("mutmut run", env={}), Facts()))
        files = {**github_job("ubuntu-latest", "uv run mutmut run"), "pyproject.toml": "[project]\nname='a'\n"}
        self.assertIn("mutmut", {run.tool for run in ci_tool_runs(files)})

    def test_cosmic_ray_and_mutatest(self) -> None:
        self.assertIsNotNone(COSMIC_RAY.claims(command("cosmic-ray exec config.toml session.sqlite"), Facts()))
        self.assertIsNone(COSMIC_RAY.claims(command("cosmic-ray init config.toml session.sqlite"), Facts()))
        self.assertIsNotNone(MUTATEST.claims(command("mutatest -s src -n 50"), Facts()))

    def test_mutmut_is_defined_by_its_pyproject_table_or_setup_cfg_section(self) -> None:
        facts = settings_facts_of({"pyproject.toml": "[tool.mutmut]\nsource_paths = ['src']\n"})
        self.assertEqual(MUTMUT.defined(MUTATION, facts), ("pyproject.toml",))
        facts = settings_facts_of({"setup.cfg": "[mutmut]\npaths_to_mutate=src\n"})
        self.assertEqual(MUTMUT.defined(MUTATION, facts), ("setup.cfg",))
