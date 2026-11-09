"""Dynamically typed code is statically type checked, so type errors are found before the code runs."""

from project_validator.facts.analysis import TYPE_CHECK
from project_validator.judging import answered_check
from project_validator.policy.analysis import judge_type_checking
from project_validator.questions.analysis import type_checking as type_checking_answers

type_checking = answered_check(
    name="type-checking",
    description="CI runs a static type checker on dynamically typed code (e.g. mypy, pyright), ideally strictly",
    aspect=TYPE_CHECK,
    answers=type_checking_answers,
    judge=judge_type_checking,
)
