from project_validator.facts.fuzzing import FUZZ
from project_validator.judging import answered_check
from project_validator.policy.fuzzing import judge_fuzzing
from project_validator.questions.fuzzing import fuzzing

fuzz_testing = answered_check(
    name="fuzz-testing",
    description="Fuzz targets exist (e.g. libFuzzer, cargo-fuzz, atheris, Go fuzzing) and CI runs them",
    aspect=FUZZ,
    answers=fuzzing,
    judge=judge_fuzzing,
)
