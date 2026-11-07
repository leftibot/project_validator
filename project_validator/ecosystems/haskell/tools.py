"""Haskell's tools: the test runners (`cabal test`, `stack test`) and the test suites packages declare, HPC
coverage, the formatters (ormolu, fourmolu, stylish-haskell), the linters (hlint, weeder, stan), cabal-audit, the
dependency managers (Cabal and Stack) and their lockfiles, the declared license, and the build outputs."""

import re
import shlex
from collections.abc import Callable, Iterator, Mapping

from project_validator import yaml_support
from project_validator.ecosystems.haskell.cabal import CabalSyntaxError, components, parse, top_level
from project_validator.ecosystems.haskell.options import HASKELL_LANGUAGE
from project_validator.facts import Command, Fact, Facts, Origin, Setting, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import has_option, program
from project_validator.facts.audit import audited, auditor
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.dependencies import Lock, PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.expansion import Action
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.licenses import declared_license_reader
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.settings import SettingsReader, file_reader, unreadable
from project_validator.facts.testing import test_runner, tested
from project_validator.facts.tools import Definition, Run, defined_by, starts, when

# --- running the tests

# cabal or stack, by its versioned name too (haskell-ci runs `cabal-3.16.0.0`).
_CABAL_OR_STACK = re.compile(r"(?:cabal|stack)(?:-[\d.]+)?")


def _builds(argv: tuple[str, ...], *subcommands: str) -> bool:
    """`cabal <subcommand>` (or its `v2-` and `new-` forms) or `stack <subcommand>`."""
    if not _CABAL_OR_STACK.fullmatch(program(argv)) or len(argv) < 2:
        return False
    subcommand = next((word for word in argv[1:] if not word.startswith("-")), "")
    return subcommand.removeprefix("v2-").removeprefix("new-") in subcommands


def _runs_tests(command: Command, _facts: Facts) -> Run | None:
    """`cabal test`, `stack test`, or `stack build --test`."""
    argv = resolved(command)
    return tested() if _builds(argv, "test") or (_builds(argv, "build") and "--test" in argv) else None


def _read_test_suites(path: str, text: str) -> Iterator[Fact]:
    """The test suites a package declares: `test-suite` sections of a `.cabal` file, `tests:` of a `package.yaml`."""
    if path.endswith(".cabal"):
        try:
            root = parse(text)
        except CabalSyntaxError as error:
            yield unreadable("Haskell test suites", path, error)
            return
        names = [component.name for component in components(root) if component.kind == "test-suite"]
    else:
        try:
            document = yaml_support.load(text)
        except yaml_support.YamlError as error:
            yield unreadable("Haskell test suites", path, error)
            return
        tests = document.get("tests") if isinstance(document, Mapping) else None
        names = [str(name) for name in tests] if isinstance(tests, Mapping) else []
    for name in names:
        yield Setting(origin=Origin(path=path), tool="Haskell test suites", key="test-suite", value=name)


TEST_SUITES = SettingsReader(name="Haskell test suites", files=("*.cabal", "package.yaml"), read=_read_test_suites)
CABAL_TEST = test_runner(
    name="cabal test",
    languages=HASKELL_LANGUAGE,
    how="cabal test (or stack test)",
    runs=_runs_tests,
    tests=Definition(
        found=lambda facts: (setting.path for setting in facts.settings("Haskell test suites")),
        default=False,
        describe="test-suite sections in .cabal files (or tests: in package.yaml)",
        from_test_units=True,
    ),
    reads=("Haskell test suites",),
)

# --- coverage

REGION, BRANCH = Granularity.REGION, Granularity.BRANCH
_HPC_PROGRAMS = frozenset({"hpc", "hpc-codecov", "hpc-lcov"})


def _hpc(command: Command, _facts: Facts) -> Run | None:
    """HPC, which counts expressions (regions) and the outcomes of boolean decisions (guards, conditions; branches):
    `cabal test --enable-coverage`, `stack test --coverage`, GHC's `-fhpc`, or the HPC reports."""
    argv = resolved(command)
    instrumented = (_builds(argv, "test", "build", "run") and has_option(argv, "--enable-coverage", "--coverage")) or (
        "-fhpc" in " ".join(argv)
    )
    return measured(REGION, BRANCH) if instrumented or program(argv) in _HPC_PROGRAMS else None


HPC = coverage_tool(
    name="HPC",
    languages=HASKELL_LANGUAGE,
    can={REGION: "cabal test --enable-coverage", BRANCH: "cabal test --enable-coverage"},
    measures=_hpc,
)

# --- formatting

_ORMOLU_STYLE = (("ormolu",), ("fourmolu",))
ORMOLU = format_tool(
    name="ormolu",
    languages=HASKELL_LANGUAGE,
    can={Enforcement.CHECK: "ormolu --mode check $(git ls-files '*.hs')", Enforcement.APPLY: "ormolu --mode inplace"},
    formats=flagged(("ormolu",), checks=("check",), applies=("inplace", "-i")),
    # ormolu has one style.
    style=defined_by(),
)
FOURMOLU = format_tool(
    name="fourmolu",
    languages=HASKELL_LANGUAGE,
    can={Enforcement.CHECK: "fourmolu --mode check .", Enforcement.APPLY: "fourmolu --mode inplace ."},
    formats=flagged(("fourmolu",), checks=("check",), applies=("inplace", "-i")),
    style=defined_by(named=("fourmolu.yaml",)),
)
STYLISH_HASKELL = format_tool(
    name="stylish-haskell",
    languages=HASKELL_LANGUAGE,
    can={Enforcement.APPLY: "stylish-haskell --inplace --recursive ."},
    formats=flagged(("stylish-haskell",), checks=(), applies=("-i", "--inplace")),
    style=defined_by(named=(".stylish-haskell.yaml",)),
)
FORMATTER_STYLE_FILES = file_reader("Haskell formatter styles", ("fourmolu.yaml", ".stylish-haskell.yaml"))


def _check_with(name: str) -> Action:
    return Action(name=f"haskell-actions/run-{name}", runs=lambda _inputs: ((name, "--mode", "check"),))


FORMATTER_ACTIONS = (_check_with("ormolu"), _check_with("fourmolu"))

# --- linting

HLINT_SETTINGS = file_reader("hlint", (".hlint.yaml",))
HLINT = analyzer(
    name="hlint",
    languages=HASKELL_LANGUAGE,
    how="hlint .",
    analyses=when(starts(("hlint",)), analysed),
    rules=defined_by(),
    reads=("hlint",),
)
HLINT_ACTION = Action(
    name="haskell-actions/hlint-run",
    runs=lambda inputs: (("hlint", *shlex.split(inputs.get("path", ".").strip("[]").replace(",", " "))),),
)
WEEDER = analyzer(name="weeder", languages=HASKELL_LANGUAGE, how="weeder", analyses=when(starts(("weeder",)), analysed))
STAN = analyzer(name="stan", languages=HASKELL_LANGUAGE, how="stan", analyses=when(starts(("stan",)), analysed))

AUDITORS = (
    auditor(
        name="cabal-audit",
        languages=HASKELL_LANGUAGE,
        how="cabal-audit",
        audits=when(starts(("cabal-audit",), ("cabal", "audit")), audited),
    ),
)

# --- dependencies


def _has(kind: str) -> Callable[[str, str], bool]:
    def recognises(_path: str, text: str) -> bool:
        return any(component.kind == kind for component in components(parse(text)))

    return recognises


CABAL_PACKAGES = manifest_reader(
    name="Cabal packages",
    manager="Cabal",
    files=("*.cabal",),
    declares=lambda _path, text: bool(re.search(r"^\s*build-depends\s*:", text, re.MULTILINE | re.IGNORECASE)),
    application=_has("executable"),
    library=_has("library"),
)
STACK_PROJECTS = manifest_reader(
    name="Stack projects",
    manager="Stack",
    files=("stack.yaml",),
    declares=lambda _path, text: bool(re.search(r"^(?:resolver|snapshot)\s*:", text, re.MULTILINE)),
)
CABAL_FREEZE = lockfile_reader(manager="Cabal", files=("cabal.project.freeze",))
STACK_LOCK = lockfile_reader(manager="Stack", files=("stack.yaml.lock",))
_LOCK_HINT = "commit cabal.project.freeze (cabal freeze) or stack.yaml.lock, so the executable is always built with "
_LOCK_HINT += "the dependencies it was tested with"
# An executable's builds should be reproducible; a library's users resolve its dependencies themselves.
PACKAGE_MANAGERS = tuple(
    PackageManager(
        name=name,
        languages=HASKELL_LANGUAGE,
        lock=Lock.APPLICATIONS,
        applications_by_default=False,
        lock_hint=_LOCK_HINT,
        # A freeze file (or stack.yaml.lock) locks the project beside it, not one above it.
        nested_locks=False,
    )
    for name in ("Cabal", "Stack")
)

# --- the declared license

# The license names of `cabal-version` before 2.2, which are not SPDX expressions.
_LEGACY_LICENSES = {"BSD2": "BSD-2-Clause", "BSD3": "BSD-3-Clause", "BSD4": "BSD-4-Clause", "MIT": "MIT"}
_LEGACY_LICENSES |= {"ISC": "ISC", "MPL-2.0": "MPL-2.0", "Apache-2.0": "Apache-2.0", "PublicDomain": "Unlicense"}
_LEGACY_LICENSES |= {"GPL-2": "GPL-2.0-only", "GPL-3": "GPL-3.0-only", "LGPL-2.1": "LGPL-2.1-only"}
_LEGACY_LICENSES |= {"LGPL-3": "LGPL-3.0-only", "AGPL-3": "AGPL-3.0-only"}


def _cabal_license(text: str) -> str | None:
    found = top_level(parse(text), "license")
    return _LEGACY_LICENSES.get(found, found) if found else None


CABAL_LICENSE = declared_license_reader(
    name="Cabal license", files=("*.cabal",), languages=HASKELL_LANGUAGE, declared=_cabal_license
)

# --- build outputs

DIST_NEWSTYLE = BuildOutput(
    languages=HASKELL_LANGUAGE,
    # hpack generates the .cabal file Cabal builds.
    build_systems=frozenset({"Cabal", "hpack"}),
    name="Cabal's build directory",
    globs=ignored_at_top_level(r"dist-newstyle|dist(?:-\*)?"),
    paths=directories("dist-newstyle"),
    hint="consider ignoring dist-newstyle/",
    artifacts=("dist-newstyle/", "*.hi", "*.dyn_hi", "*.o", "*.dyn_o", "*.tix"),
)
STACK_WORK = BuildOutput(
    languages=HASKELL_LANGUAGE,
    build_systems=frozenset({"Stack"}),
    name="Stack's work directory",
    globs=ignored_at_top_level(r"\.stack-work\*?"),
    paths=directories(".stack-work"),
    hint="consider ignoring .stack-work/",
    artifacts=(".stack-work/",),
)
