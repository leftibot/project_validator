"""CI runs mutation testing, so the tests are shown to catch the faults they should."""

from project_validator.facts.mutation import MUTATION
from project_validator.judging import answered_check
from project_validator.policy.mutation import judge_mutation
from project_validator.questions.mutation import mutation as mutation_answers

mutation_testing = answered_check(
    name="mutation-testing",
    description=(
        "CI runs mutation testing (e.g. mutmut, cargo-mutants, StrykerJS, PIT), "
        "ideally on a pull request's changes only"
    ),
    aspect=MUTATION,
    answers=mutation_answers,
    judge=judge_mutation,
)
