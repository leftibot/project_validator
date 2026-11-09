"""Static analyzers (linters) are configured and run, so the bugs they find are found before review."""

from project_validator.facts.analysis import ANALYSIS
from project_validator.judging import answered_check
from project_validator.policy.analysis import judge_analysis
from project_validator.questions.analysis import static_analysis as analysis_answers

static_analysis = answered_check(
    name="static-analysis",
    description="Static analyzers are configured and run (e.g. clang-tidy and cppcheck, ruff check, clippy)",
    aspect=ANALYSIS,
    answers=analysis_answers,
    judge=judge_analysis,
)
