"""GHC's options, wherever a project sets them: each component's `ghc-options` in a package description (`*.cabal`,
hpack's `package.yaml`), a project file's `package` and `program-options` stanzas (`cabal.project`), Stack's
`ghc-options` (`stack.yaml`), and CI's command lines (`--ghc-options=-Werror`, `stack build --pedantic`). The strict
warning set and warnings as errors are practices over them."""

import re
import shlex
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from project_validator import yaml_support
from project_validator.ecosystems.haskell.cabal import CabalSyntaxError, parse, values
from project_validator.facts import Fact, Facts, Origin
from project_validator.facts.practices import WARNINGS as WARNINGS_PRACTICE
from project_validator.facts.practices import WARNINGS_AS_ERRORS as WARNINGS_AS_ERRORS_PRACTICE
from project_validator.facts.practices import Evidence, Found, Practice, Requirement, always
from project_validator.facts.settings import SettingsReader, unreadable

HASKELL_LANGUAGE = frozenset({"Haskell"})
READER = "GHC options"


@dataclass(frozen=True, slots=True, kw_only=True)
class GhcOptions(Fact):
    """The options GHC is given for a `component` (`library`, `executable app`, `package *`, Stack's `$locals`),
    and the conditions they need, as written (`flag(dev)`)."""

    component: str
    options: tuple[str, ...]
    requires: frozenset[str] = frozenset()


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
        yield GhcOptions(
            origin=Origin(path=path), component=str(component), options=_split(found.value), requires=found.requires
        )


def _words(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(word for item in value for word in _split(str(item)))
    return _split(str(value)) if value is not None else ()


def _stack(path: str, document: Mapping[str, object]) -> Iterator[Fact]:
    """Stack's `ghc-options`, by the packages they apply to (`$locals`, `$targets`, `$everything`, or a name)."""
    found = document.get("ghc-options")
    for packages, value in found.items() if isinstance(found, Mapping) else ():
        yield GhcOptions(origin=Origin(path=path), component=f"stack {packages}", options=_words(value))


_HPACK_SECTIONS = ("executables", "tests", "benchmarks", "internal-libraries")


def _hpack_component(path: str, name: str, section: object, requires: frozenset[str]) -> Iterator[Fact]:
    if not isinstance(section, Mapping):
        return
    if words := _words(section.get("ghc-options")):
        yield GhcOptions(origin=Origin(path=path), component=name, options=words, requires=requires)
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


@dataclass(frozen=True, slots=True)
class GhcFlag:
    """A GHC flag, `name`d as messages give it, and the spellings that set it (`-Weverything` sets every warning)."""

    name: str
    spellings: str

    def option(self) -> re.Pattern[str]:
        return re.compile(rf"(?:{self.spellings})")

    def on_a_command_line(self) -> re.Pattern[str]:
        """The flag in a command line, alone or as an option's value (`--ghc-options=-Wall`), and Stack's
        `--pedantic`, which turns on -Wall and -Werror."""
        pedantic = r"|\bstack\b[^\n]*\s--pedantic\b" if self.name in ("-Wall", "-Werror") else ""
        return re.compile(rf"(?<![\w/:-])(?:{self.spellings})(?![\w=:-]){pedantic}")


def _options(flag: GhcFlag) -> Found:
    def found(facts: Facts, _compiler: str | None) -> Iterator[Evidence]:
        pattern = flag.option()
        for options in facts.of(GhcOptions):
            if any(pattern.fullmatch(option) for option in options.options):
                yield Evidence(f"{options.origin.path} ({options.component})", options.requires)

    return found


_EVERYTHING = "-Weverything"
GHC_WARNINGS = (
    GhcFlag("-Wall", f"-Wall|{_EVERYTHING}"),
    GhcFlag("-Wcompat", f"-Wcompat|{_EVERYTHING}"),
    GhcFlag("-Widentities", f"-Widentities|-fwarn-identities|{_EVERYTHING}"),
    GhcFlag("-Wredundant-constraints", f"-Wredundant-constraints|{_EVERYTHING}"),
)
GHC_WARNINGS_AS_ERRORS = GhcFlag("-Werror", "-Werror")
_HINTS = ("-W", "-fwarn", "--pedantic")


def _requirement(flag: GhcFlag) -> Requirement:
    return Requirement(name=flag.name, runs=flag.on_a_command_line(), found=_options(flag), hints=_HINTS)


WARNINGS = Practice(
    name=WARNINGS_PRACTICE,
    languages=HASKELL_LANGUAGE,
    kind="GHC warning flags",
    requirements=always(*(_requirement(flag) for flag in GHC_WARNINGS)),
    reads=(READER,),
    separator=" ",
    hint="add -Wall -Wcompat -Widentities -Wredundant-constraints to ghc-options (a common stanza imports them "
    "into every component)",
)
WARNINGS_AS_ERRORS = Practice(
    name=WARNINGS_AS_ERRORS_PRACTICE,
    languages=HASKELL_LANGUAGE,
    kind="warnings as errors",
    requirements=always(_requirement(GHC_WARNINGS_AS_ERRORS)),
    any_one=True,
    reads=(READER,),
    searched="CI configuration or ghc-options (.cabal, package.yaml, cabal.project, stack.yaml)",
    hint="add -Werror, at least behind a flag CI turns on (if flag(pedantic) ghc-options: -Werror), or build with "
    "--ghc-options=-Werror or stack build --pedantic in CI",
)
