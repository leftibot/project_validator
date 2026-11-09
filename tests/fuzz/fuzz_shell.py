"""Fuzz target: the shell and PowerShell script splitters never raise."""

import sys

import atheris

with atheris.instrument_imports():
    from project_validator.facts.shell import split_script


def TestOneInput(data: bytes) -> None:
    text = data.decode("utf-8", "surrogateescape")
    list(split_script(text))
    list(split_script(text, powershell=True))


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
