from project_validator.facts.formatting import FORMAT
from project_validator.judging import answered_check
from project_validator.policy.formatting import judge_formatting
from project_validator.questions.formatting import formatting

code_formatting = answered_check(
    name="code-formatting",
    description="Formatting is defined (e.g. .clang-format, ruff, rustfmt) and CI enforces it",
    aspect=FORMAT,
    answers=formatting,
    judge=judge_formatting,
)
