"""CI scans the code for security problems: with a multi-language scanner (CodeQL, GitLab SAST, semgrep), or with
each language's own security lints."""

from project_validator.facts.security import SECURITY
from project_validator.judging import answered_check
from project_validator.policy.security import judge_security
from project_validator.questions.security import security_scanning as security_answers

security_scanning = answered_check(
    name="security-scanning",
    description="CI scans the code for security problems (CodeQL, GitLab SAST, or each language's security lints)",
    aspect=SECURITY,
    answers=security_answers,
    judge=judge_security,
)
