import unittest

from project_validator.core import Check, Placed, Result, Status
from project_validator.grid import MARKS, render_grid
from project_validator.runner import Report


def language_check(name: str, *languages: str) -> Check:
    return Check(
        name=name,
        description=name,
        run=lambda context: Result.passed(""),
        languages_from=lambda: frozenset(languages),
    )


def universal(name: str) -> Check:
    return Check(name=name, description=name, run=lambda context: Result.passed(""))


def cxx(name: str) -> Check:
    return language_check(name, "C", "C++")


def coverage_and_formatting() -> list[Report]:
    coverage = Report(
        check=cxx("coverage"),
        result=Result(
            status=Status.FAIL,
            message="C/C++: fine; Python: none",
            places=(
                Placed(ecosystem="C/C++", unit=".", result=Result.passed("fine"), tools=("gcovr",)),
                Placed(ecosystem="Python", unit="tools", result=Result.failed("none")),
            ),
        ),
    )
    formatting = Report(
        check=cxx("code-formatting"),
        result=Result(
            status=Status.PASS,
            message="ok",
            places=(Placed(ecosystem="C/C++", unit=".", result=Result.passed("ok"), tools=("clang-format",)),),
        ),
    )
    return [coverage, formatting]


class RenderGridTests(unittest.TestCase):
    def test_a_grid_of_two_ecosystems_in_two_units(self) -> None:
        self.assertEqual(
            render_grid(coverage_and_formatting()),
            "## Results by ecosystem\n\n"
            "| Check | C/C++ in the root | Python in tools |\n|---|---|---|\n"
            "| `coverage` | ✅ gcovr | ❌ |\n"
            "| `code-formatting` | ✅ clang-format | — |\n\n"
            "## Findings\n\n- ❌ `coverage`: C/C++: fine; Python: none\n",
        )

    def test_one_unit_heads_columns_by_ecosystem_alone(self) -> None:
        reports = [
            Report(
                check=cxx("a"),
                result=Result(
                    status=Status.PASS,
                    message="ok",
                    places=(
                        Placed(ecosystem="Python", unit=".", result=Result.passed("ok")),
                        Placed(ecosystem="C/C++", unit=".", result=Result.passed("ok")),
                    ),
                ),
            )
        ]
        self.assertIn("| Check | C/C++ | Python |\n|---|---|---|\n| `a` | ✅ | ✅ |\n", render_grid(reports))

    def test_whole_project_table_and_skipped_marks(self) -> None:
        ci = Report(check=universal("ci-present"), result=Result.passed("found"))
        skipped = Report(
            check=cxx("hardening"),
            result=Result(
                status=Status.SKIP,
                message="n/a",
                places=(Placed(ecosystem="C/C++", unit=".", result=Result.skipped("n/a")),),
            ),
        )
        self.assertEqual(
            render_grid([ci, skipped]),
            "## Results by ecosystem\n\n| Check | C/C++ |\n|---|---|\n| `hardening` | ⏭️ |\n\n"
            "## Whole project\n\n| Check | Result |\n|---|---|\n| `ci-present` | ✅ found |\n",
        )

    def test_a_language_scoped_result_without_places_fills_the_columns_it_applies_to(self) -> None:
        bare = Report(check=language_check("x", "C", "C++"), result=Result.passed("fine"))
        out = render_grid([*coverage_and_formatting(), bare])
        self.assertIn("| `x` | ✅ | — |\n", out)

    def test_details_and_pipes(self) -> None:
        warned = Report(check=universal("x"), result=Result.warned("a | b", "d1"))
        out = render_grid([warned])
        self.assertIn("| `x` | ⚠️ a \\| b |", out)
        self.assertTrue(out.endswith("## Findings\n\n- ⚠️ `x`: a | b\n  - d1\n"))

    def test_tools_are_escaped_and_marks_cover_every_status(self) -> None:
        piped = Report(
            check=cxx("p"),
            result=Result(
                status=Status.PASS,
                message="ok",
                places=(Placed(ecosystem="C/C++", unit=".", result=Result.passed("ok"), tools=("a|b",)),),
            ),
        )
        self.assertIn("| `p` | ✅ a\\|b |", render_grid([piped]))
        self.assertEqual(set(MARKS), set(Status))

    def test_nothing_to_show(self) -> None:
        self.assertEqual(render_grid([]), "")
