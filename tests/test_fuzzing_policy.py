import unittest

from project_validator.core import Result, Status
from project_validator.facts.fuzzing import FUZZ, RUNS
from project_validator.policy.fuzzing import judge_fuzzing
from project_validator.questions import Answer
from project_validator.questions.fuzzing import FuzzAnswer
from project_validator.questions.tooling import ToolAnswer

UNREAD = "some of what it runs could not be read"


def _answer(tool_answer: Answer, *, unknown_definitions: tuple[str, ...] = ()) -> FuzzAnswer:
    tools = ToolAnswer(
        aspect=FUZZ,
        language="Python",
        level=RUNS,
        answer=tool_answer,
        unknown_definitions=unknown_definitions,
    )
    return FuzzAnswer(tools=tools, property_files=(), other_runs=())


class JudgeFuzzingTests(unittest.TestCase):
    def test_a_language_no_fuzzer_runs_is_skipped(self) -> None:
        result = judge_fuzzing(_answer(Answer.IMPOSSIBLE))
        self.assertEqual(result, Result.skipped("no known fuzzer runs Python"))

    def test_unreadable_definitions_with_no_targets_are_an_error(self) -> None:
        result = judge_fuzzing(_answer(Answer.NO, unknown_definitions=(UNREAD,)))
        self.assertEqual(result.status, Status.ERROR)
        self.assertIn("whether there are fuzz targets", result.message)

    def test_allowing_unknown_falls_through_to_the_no_targets_outcome(self) -> None:
        result = judge_fuzzing(_answer(Answer.NO, unknown_definitions=(UNREAD,)), allow_unknown=True)
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(result.message, "no fuzz targets found")


if __name__ == "__main__":
    unittest.main()
