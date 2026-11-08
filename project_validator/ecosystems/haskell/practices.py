"""Haskell's practices: GHC's strict warning set and warnings as errors, met on a command line
(`--ghc-options=-Werror`), by `ghc-options` wherever a project sets them (see `options`), or by Stack's
`--pedantic`, which turns on -Wall and -Werror."""

from project_validator.ecosystems.haskell.options import HASKELL_LANGUAGE, READER
from project_validator.facts.flags import flag_requirements
from project_validator.facts.practices import Practice, PracticeName, Wording, always
from project_validator.tools.toolchains import Flag

_EVERYTHING = "-Weverything"
GHC_WARNINGS = (
    Flag("-Wall", f"-Wall|{_EVERYTHING}"),
    Flag("-Wcompat", f"-Wcompat|{_EVERYTHING}"),
    Flag("-Widentities", f"-Widentities|-fwarn-identities|{_EVERYTHING}"),
    Flag("-Wredundant-constraints", f"-Wredundant-constraints|{_EVERYTHING}"),
)
GHC_WARNINGS_AS_ERRORS = Flag("-Werror", "-Werror")
_PEDANTIC = (r"\bstack\b[^\n]*\s--pedantic\b",)


def _pedantic(flag: Flag) -> tuple[str, ...]:
    """The build system setting that sets `flag` from a command line: Stack's `--pedantic`, for -Wall and -Werror."""
    return _PEDANTIC if flag.name in ("-Wall", "-Werror") else ()


WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=HASKELL_LANGUAGE,
    requirements=always(
        *flag_requirements(GHC_WARNINGS, HASKELL_LANGUAGE, configured=_pedantic, configured_hints=("--pedantic",))
    ),
    reads=(READER,),
    words=Wording(
        kind="GHC warning flags",
        separator=" ",
        hint="add -Wall -Wcompat -Widentities -Wredundant-constraints to ghc-options (a common stanza imports them "
        "into every component)",
    ),
)
WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=HASKELL_LANGUAGE,
    requirements=always(
        *flag_requirements(
            (GHC_WARNINGS_AS_ERRORS,), HASKELL_LANGUAGE, configured=_pedantic, configured_hints=("--pedantic",)
        )
    ),
    any_one=True,
    reads=(READER,),
    words=Wording(
        kind="warnings as errors",
        searched="CI configuration or ghc-options (.cabal, package.yaml, cabal.project, stack.yaml)",
        hint="add -Werror, at least behind a flag CI turns on (if flag(pedantic) ghc-options: -Werror), or build with "
        "--ghc-options=-Werror or stack build --pedantic in CI",
    ),
)
