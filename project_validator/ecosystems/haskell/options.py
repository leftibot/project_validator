"""GHC's options, wherever a project sets them: each component's `ghc-options` in a package description (`*.cabal`,
hpack's `package.yaml`), a project file's `package` and `program-options` stanzas (`cabal.project`), and Stack's
`ghc-options` (`stack.yaml`), as `CompilerOption` facts for GHC and Haskell. The practices over them are in
`practices`."""

import shlex
from collections.abc import Iterator, Mapping
from pathlib import PurePosixPath

from project_validator import yaml_support
from project_validator.ecosystems.haskell.cabal import CabalSyntaxError, parse, values
from project_validator.facts import Fact, Origin
from project_validator.facts.build import CompilerOption, disjuncts
from project_validator.facts.conditions import both, extend, negated, only, requiring
from project_validator.facts.settings import SettingsReader, unreadable

HASKELL_LANGUAGE = frozenset({"Haskell"})
READER = "GHC options"
GHC = "ghc"
# GHC and Haskell scope build conditions like the compilers and languages the shared build systems know.
extend("compilers", GHC)
extend("languages", "Haskell")


def ghc_options(
    path: str, build_system: str, component: str, options: tuple[str, ...], requires: frozenset[str] = frozenset()
) -> Iterator[Fact]:
    """The options GHC is given for a `component` (`library`, `executable app`, `package *`, Stack's `$locals`), as
    `CompilerOption` facts: for GHC and Haskell, in the builds the conditions (as written: `flag(dev)`, `not
    impl(ghc < 9)`) hold in."""
    conditions = (
        negated(requiring(found.removeprefix("not "))) if found.startswith("not ") else requiring(found)
        for found in sorted(requires)
    )
    builds = both(only("compilers", [GHC]), only("languages", HASKELL_LANGUAGE), *conditions)
    for applies in disjuncts(builds):
        for option in options:
            yield CompilerOption(
                origin=Origin(path=path), build_system=build_system, option=option, applies=applies, target=component
            )


def _split(value: str) -> tuple[str, ...]:
    try:
        return tuple(shlex.split(value))
    except ValueError:
        return tuple(value.split())


def _cabal(path: str, text: str) -> Iterator[Fact]:
    try:
        root = parse(text)
    except CabalSyntaxError as error:
        yield unreadable(READER, path, error)
        return
    for component, found in values(root, "ghc-options"):
        yield from ghc_options(path, "Cabal", str(component), _split(found.value), found.requires)


def _words(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(word for item in value for word in _split(str(item)))
    return _split(str(value)) if value is not None else ()


def _stack(path: str, document: Mapping[str, object]) -> Iterator[Fact]:
    """Stack's `ghc-options`, by the packages they apply to (`$locals`, `$targets`, `$everything`, or a name)."""
    found = document.get("ghc-options")
    for packages, value in found.items() if isinstance(found, Mapping) else ():
        yield from ghc_options(path, "Stack", f"stack {packages}", _words(value))


_HPACK_SECTIONS = ("executables", "tests", "benchmarks", "internal-libraries")


def _hpack_component(path: str, name: str, section: object, requires: frozenset[str]) -> Iterator[Fact]:
    if not isinstance(section, Mapping):
        return
    if words := _words(section.get("ghc-options")):
        yield from ghc_options(path, "hpack", name, words, requires)
    for when in section.get("when") or () if isinstance(section.get("when"), list) else ():
        if isinstance(when, Mapping):
            condition = frozenset({str(when.get("condition", ""))})
            yield from _hpack_component(path, name, when, requires | condition)


def _hpack(path: str, document: Mapping[str, object]) -> Iterator[Fact]:
    """hpack's `ghc-options`: at the top (for every component), in `library`, and in each named component."""
    yield from _hpack_component(path, "package", document, frozenset())
    yield from _hpack_component(path, "library", document.get("library"), frozenset())
    for kind in _HPACK_SECTIONS:
        named = document.get(kind)
        for name, section in named.items() if isinstance(named, Mapping) else ():
            yield from _hpack_component(path, f"{kind} {name}", section, frozenset())


def _read(path: str, text: str) -> Iterator[Fact]:
    name = PurePosixPath(path).name
    if not name.endswith(".yaml"):
        yield from _cabal(path, text)
        return
    try:
        document = yaml_support.load(text)
    except yaml_support.YamlError as error:
        yield unreadable(READER, path, error)
        return
    if isinstance(document, Mapping):
        yield from _stack(path, document) if name.startswith("stack") else _hpack(path, document)


GHC_OPTIONS = SettingsReader(name=READER, files=("*.cabal", "cabal.project", "stack.yaml", "package.yaml"), read=_read)
