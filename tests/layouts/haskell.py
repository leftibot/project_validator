"""Kinds of Haskell project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

HASKELL = frozenset({"Haskell"})
_PACKAGE = "cabal-version: 3.0\nname: app\nversion: 0.1\n\nlibrary\n  exposed-modules: App\n  hs-source-dirs: src\n"

LAYOUTS = (
    ProjectLayout(
        name="Cabal package",
        files={"app.cabal": _PACKAGE, "src/App.hs": "module App where\n"},
        languages=HASKELL,
        build_systems=frozenset({"Cabal"}),
    ),
    ProjectLayout(
        name="Stack project",
        files={"stack.yaml": "resolver: lts-22.0\n", "app.cabal": _PACKAGE, "src/App.hs": "module App where\n"},
        languages=HASKELL,
        build_systems=frozenset({"Cabal", "Stack"}),
    ),
    ProjectLayout(
        name="hpack package",
        files={"package.yaml": "name: app\nlibrary:\n  source-dirs: src\n", "src/App.hs": "module App where\n"},
        languages=HASKELL,
        build_systems=frozenset({"hpack"}),
    ),
)
