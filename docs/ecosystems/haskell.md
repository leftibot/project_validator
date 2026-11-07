# Haskell

Recognised by `.hs`, `.lhs`, `.hs-boot` and `.hsc` sources (and Alex, Happy and c2hs files once the project is known
to be Haskell), and by its build systems: Cabal (`*.cabal` package descriptions and `cabal.project`), Stack
(`stack.yaml`) and hpack (a `package.yaml` with hpack's keys). The packages a `cabal.project` or `stack.yaml` lists
in `packages:` are units of their own.

GHC's options are read from every place a project sets them: each component's `ghc-options` in a `.cabal` file
(with the `common` stanzas it imports, and `if`/`else` branches kept as conditions, so `-Werror` behind
`if flag(pedantic)` counts "when flag(pedantic)"), hpack's `ghc-options`, a `cabal.project`'s `package` and
`program-options` stanzas, Stack's `ghc-options`, and CI command lines (`--ghc-options=-Werror`).

## `tests-run`

`cabal test` (or `stack test`, `stack build --test`), and the `test-suite` sections of the `.cabal` files (or
`tests:` in `package.yaml`).

## `coverage`

HPC, which counts expressions and the outcomes of boolean decisions (guards and conditions, so branch coverage):
`cabal test --enable-coverage`, `stack test --coverage`, GHC's `-fhpc`, or the HPC reports (`hpc`, `hpc-codecov`,
`hpc-lcov`).

## `platform-matrix`

The toolchains are GHC versions: haskell-actions/setup's `ghc-version`, a matrix's `ghc`, haskell-ci's `ghc-X.Y.Z`,
`ghcup install ghc`, a `haskell:` image, or a Stack resolver.

## `compiler-warnings`

`-Wall -Wcompat -Widentities -Wredundant-constraints` (`-Weverything` sets them all; `-fwarn-identities` is the old
spelling), in `ghc-options` or on a CI command line.

## `warnings-as-errors`

`-Werror` in `ghc-options` (at least behind a flag) or on a CI command line, or `stack build --pedantic`.

## `code-formatting`

ormolu or fourmolu checking (`--mode check`, or haskell-actions/run-ormolu and run-fourmolu); ormolu has one style,
fourmolu's is in `fourmolu.yaml`. stylish-haskell only rewrites files.

## `static-analysis`

hlint (or haskell-actions/hlint-run), weeder or stan.

## `dependency-management`

Cabal (`build-depends`) and Stack (a `resolver`). A package with an executable commits `cabal.project.freeze` or
`stack.yaml.lock`; a library's users resolve its dependencies themselves.

## `dependency-audit`

cabal-audit.

## `license`

A `.cabal` file's `license` field (the names of `cabal-version` before 2.2 are mapped to SPDX: `BSD3` is
`BSD-3-Clause`).

## `committed-artifacts`

`dist-newstyle/`, interface and object files (`*.hi`, `*.o`), HPC's `*.tix`, and Stack's `.stack-work/`.

## `vcs-ignore`

`dist-newstyle` (or `dist`) for Cabal, `.stack-work` for Stack.

## Not judged

GHC compiles memory-safe code, so `hardening` does not apply; Haskell is statically typed (`type-checking`); no
function length limiter (`function-limits`) or code security scanner (`security-scanning`) the validator knows
measures Haskell.
