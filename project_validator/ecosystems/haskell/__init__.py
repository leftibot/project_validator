"""Haskell: built with Cabal (package descriptions `*.cabal`, project files `cabal.project`), Stack (`stack.yaml`) or
hpack (`package.yaml`, which generates the `.cabal` file), judged by the GHC versions CI runs.

The profile's modules: `cabal` reads the Cabal file format, `options` GHC's options wherever a project sets them,
`practices` the strict warning set and warnings as errors over them, `tools` the test runners, coverage, formatters,
linters, dependency managers and build outputs.
"""

import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from project_validator import yaml_support
from project_validator.ecosystems.haskell.cabal import CabalSyntaxError, parse, top_level
from project_validator.ecosystems.haskell.options import HASKELL_LANGUAGE
from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts.axes import versions_axis


def _project_packages(text: str) -> tuple[str, ...]:
    """The package directories a `cabal.project` lists in `packages:` (directories, `.cabal` files, or globs of
    either), as globs relative to it."""
    try:
        listed = top_level(parse(text), "packages") or ""
    except CabalSyntaxError:
        return ()
    found = []
    for entry in re.split(r"[\s,]+", listed):
        entry = entry.strip().rstrip("/")
        if entry.endswith(".cabal"):
            entry = str(PurePosixPath(entry).parent)
        if entry and entry not in (".", "./") and "://" not in entry:
            found.append(entry.removeprefix("./"))
    return tuple(dict.fromkeys(found))


def _stack_packages(text: str) -> tuple[str, ...]:
    try:
        document = yaml_support.load(text)
    except yaml_support.YamlError:
        return ()
    listed = document.get("packages") if isinstance(document, Mapping) else None
    entries = (str(entry).rstrip("/").removeprefix("./") for entry in listed) if isinstance(listed, list) else ()
    return tuple(entry for entry in entries if entry and entry != ".")


def _members(text: str) -> tuple[str, ...]:
    """The packages a `cabal.project` or `stack.yaml` declares; a package description declares none."""
    if re.search(r"^packages\s*:", text, re.MULTILINE | re.IGNORECASE) and not text.lstrip().startswith("{"):
        return _stack_packages(text) if re.search(r"^\s*-\s", text, re.MULTILINE) else _project_packages(text)
    return ()


def _is_build_tree(directory: Path) -> bool:
    return directory.name in ("dist-newstyle", ".stack-work") or (directory / "cache" / "plan.json").is_file()


def _hpack_languages(text: str) -> frozenset[str]:
    """An hpack `package.yaml` builds Haskell (pnpm reads a `package.yaml` too, without hpack's keys)."""
    return (
        HASKELL_LANGUAGE if re.search(r"^\s*(?:source-dirs|ghc-options|main)\s*:", text, re.MULTILINE) else frozenset()
    )


CABAL = BuildSystem(
    name="Cabal",
    files=("*.cabal", "cabal.project"),
    languages=HASKELL_LANGUAGE,
    is_build_tree=_is_build_tree,
    members=_members,
)
STACK = BuildSystem(name="Stack", files=("stack.yaml",), languages=HASKELL_LANGUAGE, members=_members)
HPACK = BuildSystem(
    name="hpack", files=("package.yaml",), declared_languages=lambda _path, text: _hpack_languages(text)
)

_GHC_VERSION = r"(\d+\.\d+(?:\.\d+)*|latest|recommended|head)"
GHC_VERSIONS = versions_axis("GHC version", "GHC", HASKELL_LANGUAGE)

HASKELL = Ecosystem(
    label="Haskell",
    languages=HASKELL_LANGUAGE,
    build_systems=(CABAL, STACK, HPACK),
    default_build_system=CABAL,
    source_suffixes={".hs": "Haskell", ".lhs": "Haskell", ".hs-boot": "Haskell", ".hsc": "Haskell"},
    # Alex and Happy grammars generate Haskell; `.y` is yacc's too.
    ambiguous_suffixes={".x": None, ".y": None, ".chs": "Haskell"},
    toolchain=toolchain_patterns(
        "GHC",
        version=_GHC_VERSION,
        inputs=("ghc-version",),  # haskell-actions/setup
        images=("haskell",),
        image_version=r"(\d+(?:\.\d+)*)",
        more=(
            # A matrix (`"ghc": "9.8.2"`), ghcup, haskell-ci (`ghc-9.8.2`).
            rf"[\"']ghc[\"']\s*:\s*[\"']?{_GHC_VERSION}",
            rf"\bghcup\s+install\s+ghc\s+(?:--set\s+)?{_GHC_VERSION}",
            r"\bghc-(\d+\.\d+(?:\.\d+)*)\b",
        ),
        commands=r"\bcabal\s+(?:v2-)?(?:build|test|run|install)\b|\bstack\s+(?:build|test)\b|\bghc\b",
        # A Stackage snapshot pins a GHC: it names a toolchain, not a version.
        labelled=((re.compile(r"--resolver[=\s]+((?:lts|nightly)[-\w.]*)"), "Stackage {}"),),
    ),
    ci_usage=re.compile(r"\bhaskell-actions/setup\b|\bhaskell/actions/setup\b|\bhaskell-ci\b"),
)
