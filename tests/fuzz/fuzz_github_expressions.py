"""Fuzz target: the GitHub Actions expression evaluator and renderer never raise."""

import sys

import atheris

with atheris.instrument_imports():
    from project_validator.ci.github_expressions import Known, evaluate, rendered

KNOWN = Known(os="linux", matrix={"os": "ubuntu-latest", "python": "3.14"}, env={"CI": "true"})


def TestOneInput(data: bytes) -> None:
    text = data.decode("utf-8", "surrogateescape")
    evaluate(text, KNOWN)
    rendered(text, KNOWN)


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
