"""The mutation testing question: for each language, in each unit of the project that has it, does CI run a mutation
testing tool (on the changes of a pull request only, as a bonus)?"""

from project_validator.facts.mutation import MUTATION, RUNS
from project_validator.questions import Question
from project_validator.questions.tooling import aspect_answers

mutation = aspect_answers(MUTATION, RUNS)

MUTATION_QUESTION = Question(
    name="mutation-testing",
    description="Does CI run mutation testing on each language in each unit, and only on a pull request's changes?",
    answer=mutation,
)

__all__ = ["MUTATION_QUESTION", "mutation"]
