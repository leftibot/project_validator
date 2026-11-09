"""The mutation aspect of tools: a mutation tool's run runs the project's code under mutation, and incrementally when it
can."""

import unittest
from collections.abc import Mapping

from project_validator.ecosystems.c_cpp.mutation import DEXTOOL, MULL
from project_validator.ecosystems.go import GO_MUTESTING, GREMLINS
from project_validator.ecosystems.python.mutation import COSMIC_RAY, MUTATEST, MUTMUT
from project_validator.ecosystems.rust.mutation import CARGO_MUTANTS
from project_validator.facts import Facts, Origin
from project_validator.facts.build import Applies, CompilerOption
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


class CMutationTests(unittest.TestCase):
    def test_mull_runner_and_mull_cxx_are_runs(self) -> None:
        for line in ("mull-runner build/tests", "mull-cxx -test-framework=GoogleTest a.out"):
            self.assertEqual(provided(MULL.claims(command(line), Facts())), {MUTATION: frozenset({RUNS})}, line)
        self.assertIsNone(MULL.claims(command("cmake --build build"), Facts()))

    def test_a_mull_compiler_plugin_in_the_build_is_a_run(self) -> None:
        option = CompilerOption(
            origin=Origin(path="CMakeLists.txt"),
            build_system="CMake",
            option="-fpass-plugin=/usr/lib/mull-ir-frontend-18",
            applies=Applies(),
        )
        facts = Facts([option])
        for line in ("cmake --build build", "make", "ninja -C build"):
            run = MULL.claims(command(line), facts)
            self.assertEqual(provided(run), {MUTATION: frozenset({RUNS})}, line)
            self.assertTrue(run and run.heuristic, line)
        self.assertIsNone(MULL.claims(command("ctest"), facts))

    def test_dextool_mutate_is_a_run(self) -> None:
        self.assertIsNotNone(DEXTOOL.claims(command("dextool mutate test"), Facts()))
        self.assertIsNone(DEXTOOL.claims(command("dextool admin"), Facts()))

    def test_mull_is_defined_by_mull_yml(self) -> None:
        facts = settings_facts_of({"mull.yml": "mutators: [cxx_add_to_sub]\n", ".dextool_mutate.toml": "[x]\n"})
        self.assertEqual(MULL.defined(MUTATION, facts), ("mull.yml",))
        self.assertEqual(DEXTOOL.defined(MUTATION, facts), (".dextool_mutate.toml",))


class RustMutationTests(unittest.TestCase):
    def test_cargo_mutants_is_a_run(self) -> None:
        run = CARGO_MUTANTS.claims(command("cargo mutants"), Facts())
        self.assertEqual(provided(run), {MUTATION: frozenset({RUNS})})
        self.assertIsNone(CARGO_MUTANTS.claims(command("cargo test"), Facts()))

    def test_in_diff_is_incremental(self) -> None:
        for line in ("cargo mutants --in-diff changes.diff", "cargo mutants --in-diff=changes.diff"):
            run = CARGO_MUTANTS.claims(command(line), Facts())
            self.assertEqual(provided(run)[MUTATION], frozenset({RUNS, INCREMENTAL}), line)
            self.assertFalse(run and run.heuristic, line)

    def test_cargo_mutants_is_defined_by_cargo_mutants_toml(self) -> None:
        facts = settings_facts_of({"Cargo.toml": "[package]\nname='a'\n", ".cargo/mutants.toml": "timeout = 60\n"})
        self.assertEqual(CARGO_MUTANTS.defined(MUTATION, facts), (".cargo/mutants.toml",))
        self.assertEqual(CARGO_MUTANTS.defined(MUTATION, settings_facts_of({"mutants.toml": ""})), ())


class GoMutationTests(unittest.TestCase):
    def test_gremlins_unleash_is_a_run(self) -> None:
        self.assertEqual(provided(GREMLINS.claims(command("gremlins unleash"), Facts())), {MUTATION: frozenset({RUNS})})
        self.assertIsNone(GREMLINS.claims(command("gremlins run"), Facts()))
        line = "go run github.com/go-gremlins/gremlins/cmd/gremlins@latest unleash"
        self.assertIn("gremlins", {run.tool for run in ci_tool_runs(github_job("ubuntu-latest", line))})

    def test_gremlins_diff_is_incremental(self) -> None:
        run = GREMLINS.claims(command("gremlins unleash --diff origin/main"), Facts())
        self.assertEqual(provided(run)[MUTATION], frozenset({RUNS, INCREMENTAL}))

    def test_go_mutesting_is_a_run(self) -> None:
        self.assertIsNotNone(GO_MUTESTING.claims(command("go-mutesting ./..."), Facts()))
        self.assertIsNone(GO_MUTESTING.claims(command("go test ./..."), Facts()))
