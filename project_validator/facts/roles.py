"""Roles: what the code at a path is for (the product, its tests, examples, docs, tooling, benchmarks, or other
projects' vendored code), told by the directories it is in. Shared by the structure facts and the settings readers,
which skip vendored projects' configuration."""

import re
from pathlib import PurePosixPath

# Code the project carries but does not write: minified bundles, and the directories that hold other projects' code.
_MINIFIED = re.compile(r"[.-]min\.[^.]+$")
VENDOR_DIRECTORIES = (
    "third_party",
    "third-party",
    "thirdparty",
    "3rdparty",
    "external",
    "extern",
    "vendor",
    "vendored",
    "deps",
)
# The role of the code below a directory with one of these names (see `role`).
_ROLES = {
    **dict.fromkeys(VENDOR_DIRECTORIES, "vendored"),
    **dict.fromkeys(("test", "tests", "testing", "testdata", "spec", "specs", "__tests__", "fixtures"), "test"),
    **dict.fromkeys(
        ("fuzz", "fuzzing", "fuzz_test", "fuzz_tests", "fuzztest", "stress", "stress-test", "stress-tests"), "test"
    ),
    **dict.fromkeys(("example", "examples", "sample", "samples", "demo", "demos"), "example"),
    **dict.fromkeys(("doc", "docs", "documentation", "website"), "docs"),
    **dict.fromkeys(("tools", "tooling", "scripts"), "tooling"),
    **dict.fromkeys(("bench", "benches", "benchmark", "benchmarks"), "benchmark"),
}
# Roles whose code is not the product: it needs no coverage of its own, and adds no language to the unit it is in.
AUXILIARY = frozenset({"vendored", "example", "docs", "tooling", "benchmark"})


# Directories that hold a unit's sources: below them, directory names are the code's own (`com/example/App.java`).
_SOURCE_ROOTS = frozenset({"src", "lib", "source", "sources", "main", "include", "pkg", "internal", "app"})


def _named_role(part: str) -> str | None:
    """The role a directory's name tells (`tests`, `integration-tests`, `tests-build`, `examples`), if any."""
    if part in _ROLES:
        return _ROLES[part]
    test_named = part.endswith(("-tests", "_tests")) or part.startswith(("tests-", "tests_", "test-", "test_"))
    return "test" if test_named else None


def _vendored(posix: PurePosixPath, parts: list[str], directory: bool) -> bool:
    return any(_ROLES.get(part) == "vendored" for part in parts) or (
        not directory and bool(_MINIFIED.search(posix.name))
    )


def role(path: str, *, directory: bool = False) -> str:
    """What the code at `path` is for: `vendored` code of other projects (below a vendor directory anywhere, or a
    minified bundle), else by the outermost directory that tells, above any source root (`src`, `lib`): the
    `product`, its `test`s (test fixtures, fuzz and stress tests too), an `example`, `docs`, `tooling` or a
    `benchmark`. A directory's own name tells first, below a source root too (`internal/tools`)."""
    posix = PurePosixPath(path)
    parts = [part.lower() for part in (posix.parts if directory else posix.parts[:-1])]
    if _vendored(posix, parts, directory):
        return "vendored"
    # A directory that is a unit of its own is told by its own name first (`internal/tools`, a Go tools module).
    if directory and parts and (own := _named_role(parts[-1])):
        return own
    for part in parts:
        if part in _SOURCE_ROOTS:
            break
        if found := _named_role(part):
            return found
    return "product"


__all__ = ["AUXILIARY", "VENDOR_DIRECTORIES", "role"]
