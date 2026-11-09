"""CI limits function length: with lizard told a limit, or with a linter's rule that limits it (clang-tidy's
readability-function-size, RuboCop's Metrics/MethodLength)."""

from project_validator.facts.limits import FUNCTION_LENGTH
from project_validator.judging import answered_check
from project_validator.policy.limits import judge_limits
from project_validator.questions.limits import function_limits as limit_answers

function_limits = answered_check(
    name="function-limits",
    description="Function length is limited (lizard, or each language's linter rule)",
    aspect=FUNCTION_LENGTH,
    answers=limit_answers,
    judge=judge_limits,
)
