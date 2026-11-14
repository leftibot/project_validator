"""The coverage question, answered from facts, and the coverage policy that judges the answers."""

from __future__ import annotations

import time
import unittest
from typing import cast
from unittest import mock

from project_validator.checks.coverage import coverage
from project_validator.core import Result, Status
from project_validator.ecosystems import isolated_registry, register
from project_validator.facts import Command, Facts, Origin, Unknown
from project_validator.facts.coverage import COVERAGE, Granularity, Rung, coverage_tool, measured, reported, rung_of
from project_validator.facts.structure import Unit
from project_validator.facts.tools import Run, Tool, ToolRun
from project_validator.policy.coverage import judge_coverage, required_coverage
from project_validator.questions import FORMATS, LANGUAGES, Answer, answer_dict, known_questions, units_of, unknowns_for
from project_validator.questions.answers import answers
from project_validator.questions.coverage import coverage_answer
from tests.support import FORMAT_ECOSYSTEM, github_job, make_context, temp_project

ORIGIN = Origin(path="ci.yml", at=("jobs", "test"))


class AnswerDictTests(unittest.TestCase):
    def test_every_answer_starts_with_its_language_unit_and_verdict(self) -> None:
        answer = coverage_answer("Lang", Facts(), ())
        self.assertEqual(
            answer_dict(answer, Answer.YES, extra=[1]), {"language": "Lang", "unit": ".", "answer": "yes", "extra": [1]}
        )
        self.assertEqual(answer_dict(answer), {"language": "Lang", "unit": "."})


class UnknownsForTests(unittest.TestCase):
    def test_unknown_settings_count_for_what_is_read(self) -> None:
        settings = Unknown(origin=ORIGIN, subject="s", reason="not read", hides="settings", tools=("CMake",))
        commands = Unknown(origin=ORIGIN, subject="c", reason="not split")
        facts = Facts((settings, commands))
        self.assertEqual(unknowns_for((), facts), ("c: not split (ci.yml:jobs.test)",))
        self.assertEqual(len(unknowns_for((), facts, reads=("CMake",))), 2)
        self.assertEqual(len(unknowns_for((), facts, reads=("Meson",))), 1)


def _never(_: Command, __: Facts) -> Run | None:
    return None


def _tool(name: str, languages: set[str], *granularities: Granularity) -> Tool:
    return coverage_tool(
        name=name,
        languages=frozenset(languages),
        can={granularity: f"{name} --{granularity}" for granularity in granularities},
        measures=_never,
    )


def _measured(tool: str, *granularities: Granularity, scope: tuple[str, ...] = (".",)) -> ToolRun:
    return _run(tool, measured(*granularities), scope=scope)


def _run(tool: str, run: Run, scope: tuple[str, ...] = (".",)) -> ToolRun:
    return ToolRun(
        origin=ORIGIN, job="test", tool=tool, languages=frozenset({"Lang"}), provides=run.provides, scope=scope
    )


LINE, STATEMENT, BRANCH, PATH = Granularity.LINE, Granularity.STATEMENT, Granularity.BRANCH, Granularity.PATH
REPORT_HINT = "consider reporting branch coverage where it can be seen (a report CI publishes, a coverage service)"
GATE_HINT = "consider failing CI when branch coverage falls below a threshold"
TOOLS = (_tool("cov", {"Lang"}, LINE, BRANCH), _tool("paths", {"Lang"}, PATH), _tool("other", {"Other"}, BRANCH))


class CoverageRungTests(unittest.TestCase):
    """A run measures a granularity, reports it (a person or a service sees the numbers) or gates on it (CI fails
    under a threshold): three rungs, each including the ones below, kept as levels of the coverage aspect."""

    def test_the_rungs_are_levels_of_the_coverage_aspect(self) -> None:
        self.assertEqual(measured(LINE, BRANCH).provides, {COVERAGE: frozenset({"line", "branch"})})
        self.assertEqual(
            reported(LINE, BRANCH, gated=(BRANCH,)).provides,
            {COVERAGE: frozenset({"line", "branch", "line reported", "branch reported", "branch gated"})},
        )
        self.assertEqual(
            measured(LINE, reported=(BRANCH,)).provides,
            {COVERAGE: frozenset({"line", "branch", "branch reported"})},
        )
        self.assertEqual(measured(None, gated=(None,)).provides, {COVERAGE: frozenset()})

    def test_the_rung_a_run_reaches_for_a_granularity(self) -> None:
        levels = reported(LINE, gated=(BRANCH,)).provides[COVERAGE]
        self.assertEqual(rung_of(levels, LINE), Rung.REPORTED)
        self.assertEqual(rung_of(levels, BRANCH), Rung.GATED)
        self.assertIsNone(rung_of(levels, PATH))
        self.assertEqual(rung_of(measured(PATH).provides[COVERAGE], PATH), Rung.MEASURED)
        self.assertLess(Rung.MEASURED.rank, Rung.REPORTED.rank)
        self.assertLess(Rung.REPORTED.rank, Rung.GATED.rank)


class CoverageAnswerTests(unittest.TestCase):
    def test_the_answer_says_the_highest_rung_reached_and_the_tools_at_each(self) -> None:
        runs = (
            _run("cov", measured(BRANCH)),
            _run("report", reported(BRANCH)),
            _run("gate", reported(LINE, gated=(LINE,))),
        )
        answer = coverage_answer("Lang", Facts(runs), TOOLS)
        self.assertEqual((answer[BRANCH].rung, answer[BRANCH].tools), (Rung.REPORTED, ("cov", "report")))
        self.assertEqual((answer[BRANCH].reported, answer[BRANCH].gated), (("report",), ()))
        self.assertEqual(
            (answer[LINE].rung, answer[LINE].reported, answer[LINE].gated), (Rung.GATED, ("gate",), ("gate",))
        )
        self.assertEqual((answer[PATH].rung, answer[PATH].answer), (None, Answer.NO))
        as_dict = cast("dict[str, dict[str, object]]", answer.as_dict())
        self.assertEqual((as_dict["line"]["rung"], as_dict["path"]["rung"]), ("gated", None))

    def test_yes_no_and_impossible_by_what_the_known_tools_measure(self) -> None:
        answer = coverage_answer("Lang", Facts((_measured("cov", LINE),)), TOOLS)
        self.assertEqual(
            {granularity: found.answer for granularity, found in answer.granularities.items()},
            {
                LINE: Answer.YES,
                STATEMENT: Answer.IMPOSSIBLE,
                Granularity.REGION: Answer.IMPOSSIBLE,
                BRANCH: Answer.NO,
                PATH: Answer.NO,
            },
        )
        self.assertEqual(answer[LINE].tools, ("cov",))
        self.assertEqual(answer[BRANCH].known, ("cov --branch",))

    def test_what_could_not_be_read_makes_no_unknown(self) -> None:
        unread = Unknown(origin=ORIGIN, subject="the jobs", reason="a matrix computed by an expression")
        answer = coverage_answer("Lang", Facts((unread, _measured("cov", BRANCH))), TOOLS)
        self.assertEqual((answer[BRANCH].answer, answer[PATH].answer), (Answer.YES, Answer.UNKNOWN))
        self.assertEqual(answer.unknowns, ("the jobs: a matrix computed by an expression (ci.yml:jobs.test)",))

    def test_answers_are_json_ready(self) -> None:
        found = coverage_answer("Lang", Facts((_measured("cov", BRANCH),)), TOOLS).as_dict()
        self.assertEqual(
            found["branch"],
            {
                "answer": "yes",
                "rung": "measured",
                "tools": ["cov"],
                "reported": [],
                "gated": [],
                "known": ["cov --branch"],
            },
        )
        self.assertEqual(found["language"], "Lang")


class CoveragePolicyTests(unittest.TestCase):
    def test_branch_coverage_is_required_or_else_the_finest_possible(self) -> None:
        self.assertEqual(required_coverage(coverage_answer("Lang", Facts(), TOOLS)), BRANCH)
        statements = (_tool("go", {"Lang"}, LINE, STATEMENT),)
        self.assertEqual(required_coverage(coverage_answer("Lang", Facts(), statements)), STATEMENT)

    def test_a_language_no_tool_measures_is_skipped(self) -> None:
        self.assertEqual(
            judge_coverage(coverage_answer("Zig", Facts(), TOOLS)),
            Result(status=Status.SKIP, message="no known tool measures the coverage of Zig"),
        )

    def test_the_message_says_the_rung_reached_and_suggests_the_next(self) -> None:
        cases = (
            (measured(BRANCH), "branch coverage is measured with cov", (REPORT_HINT, GATE_HINT)),
            (reported(BRANCH), "branch coverage is reported with cov", (GATE_HINT,)),
            (reported(BRANCH, gated=(BRANCH,)), "branch coverage is gated with cov", ()),
        )
        for run, message, hints in cases:
            with self.subTest(run=run):
                judged = judge_coverage(coverage_answer("Lang", Facts((_run("cov", run),)), TOOLS))
                self.assertEqual(
                    judged, Result.passed(message, *hints, "consider adding path coverage (e.g. paths --path)")
                )
        mixed = Facts((_run("cov", measured(BRANCH)), _run("gate", reported(BRANCH, gated=(BRANCH,)))))
        self.assertEqual(
            judge_coverage(coverage_answer("Lang", mixed, TOOLS)).message, "branch coverage is gated with gate"
        )

    def test_the_path_coverage_bonus_says_its_rung(self) -> None:
        cases = (
            (measured(PATH), "path coverage bonus: measured with paths (not reported)"),
            (reported(PATH), "path coverage bonus: reported with paths"),
            (reported(PATH, gated=(PATH,)), "path coverage bonus: gated with paths"),
        )
        for run, bonus in cases:
            with self.subTest(run=run):
                facts = Facts((_run("cov", reported(BRANCH, gated=(BRANCH,))), _run("paths", run)))
                self.assertEqual(
                    judge_coverage(coverage_answer("Lang", facts, TOOLS)).message,
                    f"branch coverage is gated with cov; {bonus}",
                )

    def test_path_coverage_is_a_bonus(self) -> None:
        both = Facts((_measured("cov", BRANCH), _measured("paths", PATH)))
        self.assertEqual(
            judge_coverage(coverage_answer("Lang", both, TOOLS)).message,
            "branch coverage is measured with cov; path coverage bonus: measured with paths (not reported)",
        )


class LanguagesOfOneEcosystemTests(unittest.TestCase):
    def test_languages_judged_differently_are_labelled(self) -> None:
        c_only = coverage_tool(
            name="ccov", languages=frozenset({"C"}), can={BRANCH: "ccov"}, measures=lambda *_: measured(BRANCH)
        )
        cxx_lines = coverage_tool(
            name="xxcov", languages=frozenset({"C++"}), can={LINE: "xxcov"}, measures=lambda *_: measured(LINE)
        )
        files = {"main.c": "", "app.cpp": "", **github_job("ubuntu-latest", "ccov")}
        with (
            mock.patch("project_validator.questions.coverage.known_tools", return_value=(c_only, cxx_lines)),
            mock.patch("project_validator.facts.tools.known_tools", return_value=(c_only, cxx_lines)),
            temp_project(files) as root,
        ):
            result = coverage.run(make_context(root))
        self.assertEqual(
            result.message,
            "C: branch coverage is measured with ccov; C++: line coverage is measured with xxcov",
        )
        # A language no known tool handles is not judged by the check at all.
        with (
            mock.patch("project_validator.questions.coverage.known_tools", return_value=(c_only,)),
            mock.patch("project_validator.facts.tools.known_tools", return_value=(c_only,)),
            temp_project(files) as root,
        ):
            self.assertEqual(coverage.run(make_context(root)).message, "branch coverage is measured with ccov")


class UnitTests(unittest.TestCase):
    def test_a_run_covers_its_directory_what_is_below_it_and_the_unit_it_is_in(self) -> None:
        units = (".", "packages/a", "packages/a/sub", "packages/b", "packages/ab")
        run = _measured("cov", BRANCH, scope=("packages/a",))
        # A workspace member is a unit of its own: a run in it does not cover the root unit above it.
        self.assertEqual([run.covers(unit, units) for unit in units], [False, True, True, False, False])
        self.assertTrue(_measured("cov", BRANCH).covers("packages/b", units))
        # A run in a directory of a unit (its `src/`) covers that unit.
        inside = _measured("cov", BRANCH, scope=("packages/a/src",))
        self.assertEqual([inside.covers(unit, units) for unit in units], [False, True, False, False, False])
        self.assertTrue(_measured("cov", BRANCH, scope=("src",)).covers(".", units))

    @unittest.expectedFailure  # upstream #181: covers() is quadratic in the units, cubic over a project's runs
    def test_many_units_and_runs_are_covered_quickly(self) -> None:
        """A monorepo of forty members with forty tool runs is judged in a fraction of a second; `owner()` walking
        every unit for every (run, unit) pair takes seconds here and minutes on the real ones (uutils/coreutils has
        116 units, ocaml/dune more)."""
        units = tuple(f"crates/member{number}" for number in range(40))
        runs = [_measured("cov", BRANCH, scope=(unit,)) for unit in units]
        started = time.perf_counter()
        covered = sum(run.covers(unit, units) for run in runs for unit in units)
        self.assertEqual(covered, len(units))
        self.assertLess(time.perf_counter() - started, 0.2)

    def test_a_format_is_answered_in_the_units_whose_files_are_in_it(self) -> None:
        facts = Facts(
            (
                Unit(origin=Origin(path="."), build_systems=(), languages=frozenset(), formats=frozenset({"WDATA"})),
                Unit(origin=Origin(path="b"), build_systems=("npm",), languages=frozenset({"Lang"})),
            )
        )
        self.assertEqual((units_of("WDATA", facts), units_of("Lang", facts)), ((".",), ("b",)))
        self.assertEqual(units_of("WDATA", Facts()), (".",))

    def test_every_question_is_asked_of_the_languages_or_formats_it_is_about(self) -> None:
        with isolated_registry(), temp_project({"src/a.wdata": "", "setup.py": ""}) as root:
            register(FORMAT_ECOSYSTEM)
            found = answers(make_context(root))
        kinds = {question.name: question.kinds for question in known_questions()}
        self.assertEqual((kinds["coverage"], kinds["wellformed"]), (LANGUAGES, FORMATS))
        self.assertEqual(kinds["static-analysis"], LANGUAGES | FORMATS)
        for question, entries in found.items():
            with self.subTest(question=question):
                asked = [entry["language"] for entry in cast("list[dict[str, object]]", entries)]
                # A language is listed whatever the answer; a format only where a tool could answer (no analyzer
                # handles WDATA, so static-analysis lists Python alone), and always for what parses.
                self.assertEqual("Python" in asked, "language" in kinds[question])
                self.assertLessEqual(set(asked) - {"Python"}, {"WDATA"} if "format" in kinds[question] else set())
                if question == "wellformed":
                    self.assertEqual(asked, ["WDATA"])

    def test_each_unit_of_a_language_is_answered(self) -> None:
        facts = Facts(
            (
                Unit(origin=Origin(path="a"), build_systems=("npm",), languages=frozenset({"Lang"})),
                Unit(origin=Origin(path="b"), build_systems=("npm",), languages=frozenset({"Lang"})),
                _measured("cov", BRANCH, scope=("a",)),
            )
        )
        answers = {unit: coverage_answer("Lang", facts, TOOLS, unit)[BRANCH].answer for unit in ("a", "b")}
        self.assertEqual(answers, {"a": Answer.YES, "b": Answer.NO})
