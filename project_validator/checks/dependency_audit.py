from project_validator.facts.audit import AUDIT
from project_validator.judging import answered_check
from project_validator.policy.audit import judge_audit
from project_validator.questions.audit import dependency_audit as audit_answers

dependency_audit = answered_check(
    name="dependency-audit",
    description="CI checks the dependencies against known vulnerabilities (e.g. pip-audit, cargo audit, govulncheck)",
    aspect=AUDIT,
    answers=audit_answers,
    judge=judge_audit,
)
