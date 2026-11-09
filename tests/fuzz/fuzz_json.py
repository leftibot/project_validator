"""Fuzz target: `check_json` agrees with `json.loads` on whether a text is JSON."""

import json
import sys

import atheris

with atheris.instrument_imports():
    from project_validator.text import JsonSyntaxError, check_json


def standard_verdict(text: str) -> str | None:
    """None when `json.loads` accepts the text, its error otherwise; `RecursionError` gives no verdict."""
    try:
        json.loads(text)
    except RecursionError:
        raise
    except ValueError as error:
        return repr(error)
    return None


def own_verdict(text: str) -> str | None:
    try:
        check_json(text)
    except JsonSyntaxError as error:
        return repr(error)
    return None


def TestOneInput(data: bytes) -> None:
    text = data.decode("utf-8", "surrogateescape")
    try:
        standard = standard_verdict(text)
    except RecursionError:
        return
    ours = own_verdict(text)
    if (standard is None) != (ours is None):
        raise AssertionError(f"json.loads: {standard or 'accepted'}; check_json: {ours or 'accepted'}; text: {text!r}")


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
