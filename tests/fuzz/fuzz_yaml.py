"""Fuzz target: the YAML loader and the multi-document checker raise only `YamlError`."""

import contextlib
import sys

import atheris

with atheris.instrument_imports():
    from project_validator.yaml_support import YamlError, check_documents, load


def TestOneInput(data: bytes) -> None:
    text = data.decode("utf-8", "surrogateescape")
    for parse in (load, check_documents):
        with contextlib.suppress(YamlError):
            parse(text)


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
