"""Fuzz target: the CMake tokenizer raises only `CMakeSyntaxError`; the evaluator raises nothing on one file."""

import contextlib
import pathlib
import sys
import tempfile

import atheris

with atheris.instrument_imports():
    from project_validator.build_systems.cmake import cmake_project
    from project_validator.build_systems.cmake.syntax import CMakeSyntaxError, invocations
    from project_validator.core import Context, Options, Project
    from project_validator.plugins import discover

PROVIDERS = discover().providers


def evaluated(text: str) -> None:
    with tempfile.TemporaryDirectory(prefix="fuzz_cmake_") as directory:
        root = pathlib.Path(directory)
        (root / "CMakeLists.txt").write_text(text, encoding="utf-8", errors="surrogateescape")
        cmake_project(Context(Project(root), PROVIDERS, Options())).facts  # noqa: B018


def TestOneInput(data: bytes) -> None:
    text = data.decode("utf-8", "surrogateescape")
    with contextlib.suppress(CMakeSyntaxError):
        list(invocations(text))
    evaluated(text)


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
