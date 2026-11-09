"""Fuzz target: the Meson parser raises only `MesonSyntaxError`; the evaluator raises nothing on one file."""

import contextlib
import pathlib
import sys
import tempfile

import atheris

with atheris.instrument_imports():
    from project_validator.build_systems.meson import meson_project
    from project_validator.build_systems.meson.syntax import MesonSyntaxError, parse
    from project_validator.core import Context, Options, Project
    from project_validator.plugins import discover

PROVIDERS = discover().providers


def evaluated(text: str) -> None:
    with tempfile.TemporaryDirectory(prefix="fuzz_meson_") as directory:
        root = pathlib.Path(directory)
        (root / "meson.build").write_text(text, encoding="utf-8", errors="surrogateescape")
        meson_project(Context(Project(root), PROVIDERS, Options())).facts  # noqa: B018


def TestOneInput(data: bytes) -> None:
    text = data.decode("utf-8", "surrogateescape")
    with contextlib.suppress(MesonSyntaxError):
        parse(text)
    evaluated(text)


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
