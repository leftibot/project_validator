"""Judging: how results are built, settled before a policy judges, and combined across what was judged."""

import unittest
from collections.abc import Callable

from project_validator.core import Check, Result, Status
from project_validator.facts.tools import handling
from project_validator.judging import answered_check, combined
from project_validator.policy import skipped_or_unknown, unknown
from project_validator.questions import Answer
from project_validator.questions.tooling import ToolAnswer, aspect_answers


class ResultTests(unittest.TestCase):
    def test_skipped_is_a_result_like_the_others(self) -> None:
        self.assertEqual(
            Result.skipped("no known tool formats Zig", "why"),
            Result(status=Status.SKIP, message="no known tool formats Zig", details=("why",)),
        )

    def test_statuses_are_ordered_by_severity(self) -> None:
        statuses = (Status.ERROR, Status.SKIP, Status.WARN, Status.PASS, Status.FAIL)
        self.assertEqual(
            sorted(statuses, key=lambda status: status.severity),
            [Status.SKIP, Status.PASS, Status.WARN, Status.FAIL, Status.ERROR],
        )


class SkippedOrUnknownTests(unittest.TestCase):
    def _settled(self, answer: Answer, *, allow_unknown: bool = False) -> Result | None:
        return skipped_or_unknown(
            answer,
            ("ci.yml: not read",),
            impossible="no known tool formats Zig",
            asks="whether CI enforces the formatting",
            hint="consider zig fmt --check",
            allow_unknown=allow_unknown,
        )

    def test_an_impossible_answer_is_skipped(self) -> None:
        self.assertEqual(self._settled(Answer.IMPOSSIBLE), Result.skipped("no known tool formats Zig"))

    def test_an_unknown_answer_is_an_error_unless_allowed(self) -> None:
        settled = self._settled(Answer.UNKNOWN)
        self.assertEqual(
            settled, unknown("whether CI enforces the formatting", ("ci.yml: not read",), "consider zig fmt --check")
        )
        self.assertEqual(settled.status if settled else None, Status.ERROR)
        self.assertIsNone(self._settled(Answer.UNKNOWN, allow_unknown=True))

    def test_yes_and_no_are_left_to_the_policy(self) -> None:
        self.assertIsNone(self._settled(Answer.YES))
        self.assertIsNone(self._settled(Answer.NO))


class CombinedTests(unittest.TestCase):
    PASSED, FAILED, SKIPPED = Result.passed("fine"), Result.failed("bad"), Result.skipped("n/a")

    def _combined(self, results: dict[str, Result]) -> Result:
        return combined(results, label=lambda key, _keys: key.upper(), none="nothing judged")

    def test_one_result_when_all_agree(self) -> None:
        self.assertEqual(self._combined({"c": self.PASSED, "d": self.PASSED}), self.PASSED)

    def test_skipped_results_are_left_out_unless_all_are(self) -> None:
        self.assertEqual(self._combined({"c": self.SKIPPED, "d": self.FAILED}), self.FAILED)
        self.assertEqual(self._combined({"c": self.SKIPPED, "d": self.SKIPPED}), self.SKIPPED)

    def test_results_that_differ_are_labelled_and_the_worst_wins(self) -> None:
        self.assertEqual(
            self._combined({"c": self.PASSED, "d": self.FAILED}),
            Result(status=Status.FAIL, message="C: fine; D: bad"),
        )

    def test_labels_see_the_keys_that_are_kept(self) -> None:
        """A label may depend on what else is named: `judged` names a language only when several are."""
        kept: list[tuple[str, ...]] = []

        def label(key: str, keys: tuple[str, ...]) -> str:
            kept.append(keys)
            return key

        combined({"c": self.SKIPPED, "d": self.PASSED, "e": self.FAILED}, label=label, none="")
        self.assertEqual(kept, [("d", "e"), ("d", "e")])

    def test_nothing_judged(self) -> None:
        self.assertEqual(self._combined({}), Result.skipped("nothing judged"))


def _passes(answer: ToolAnswer, /, *, allow_unknown: bool = False) -> Result:
    return Result.passed("ok")


class AnsweredCheckTests(unittest.TestCase):
    def _check(self, *, aspect: str | None = None, languages: Callable[[], frozenset[str]] | None = None) -> Check:
        return answered_check(
            name="x",
            description="x",
            answers=aspect_answers("format", "check"),
            judge=_passes,
            aspect=aspect,
            languages=languages,
        )

    def test_an_aspect_names_the_languages_its_tools_handle(self) -> None:
        check = self._check(aspect="format")
        self.assertEqual(check.aspect, "format")
        self.assertEqual(check.languages, handling("format")())
        self.assertIn("Python", check.languages)

    def test_languages_may_be_given_without_an_aspect(self) -> None:
        check = self._check(languages=lambda: frozenset({"Zig"}))
        self.assertIsNone(check.aspect)
        self.assertEqual(check.languages, frozenset({"Zig"}))

    def test_an_aspect_or_languages_is_required(self) -> None:
        with self.assertRaisesRegex(TypeError, "aspect or languages"):
            self._check()
