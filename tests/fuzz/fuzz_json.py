"""Fuzz target: `check_json` agrees with `json.loads` on whether a text is JSON."""

import json
import sys

import atheris

with atheris.instrument_imports():
    from project_validator.text import JsonSyntaxError, check_json


def _reject(name: str) -> object:
    """`NaN`, `Infinity` and `-Infinity` are not JSON, though `json.loads` takes them."""
    raise ValueError(f"not JSON: {name}")


def standard_verdict(text: str) -> str | type[RecursionError] | None:
    """None when `json.loads` accepts the text (as JSON: no non-finite numbers, and integers stay text, since
    `json.loads` refuses integers of over 4300 digits), its error otherwise; `RecursionError` gives no verdict."""
    try:
        json.loads(text, parse_constant=_reject, parse_int=str)
    except RecursionError:
        return RecursionError
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
    standard = standard_verdict(text)
    if standard is RecursionError:
        return
    ours = own_verdict(text)
    if (standard is None) != (ours is None):
        raise AssertionError(f"json.loads: {standard or 'accepted'}; check_json: {ours or 'accepted'}; text: {text!r}")


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
