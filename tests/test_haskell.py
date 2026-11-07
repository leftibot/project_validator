"""The Haskell profile: the Cabal file format, GHC's options wherever they are set, and the Haskell tools, judged by
the generic checks in every Haskell layout."""

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.dependency_management import dependency_management
from project_validator.checks.license import license_ as license_check
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.haskell import HASKELL, _members
from project_validator.ecosystems.haskell.cabal import CabalSyntaxError, parse, values
from project_validator.ecosystems.haskell.options import GHC_OPTIONS
from project_validator.ecosystems.haskell.tools import TEST_SUITES
from project_validator.facts import Setting
from project_validator.facts.build import CompilerOption
from tests.support import fixture_files, github_job, github_steps, make_context, run_as, run_in_layout, temp_project

STRICT = "-Wall -Wcompat -Widentities -Wredundant-constraints"
PACKAGE = """cabal-version: 3.0
name: app
version: 0.1

common warnings
  ghc-options: -Wall
  if flag(pedantic)
    ghc-options: -Werror
  elif impl(ghc >= 9.8)
    ghc-options: -Wno-x-partial
  else
    ghc-options: -O0

-- a comment
library
  import: warnings
  ghc-options:
    -Wcompat
    -Widentities
  exposed-modules: App

executable app
  main-is: Main.hs
  ghc-options: -threaded
  build-depends: base, app

test-suite spec
  type: exitcode-stdio-1.0
  main-is: Spec.hs
"""


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class CabalTests(unittest.TestCase):
    def test_components_have_their_fields_with_the_conditions_they_need(self) -> None:
        found = [
            (str(component), value.value, sorted(value.requires))
            for component, value in values(parse(PACKAGE), "ghc-options")
        ]
        self.assertEqual(
            found,
            [
                ("library", "-Wall", []),
                ("library", "-Werror", ["flag(pedantic)"]),
                ("library", "-Wno-x-partial", ["impl(ghc >= 9.8)", "not flag(pedantic)"]),
                ("library", "-O0", ["not flag(pedantic)", "not impl(ghc >= 9.8)"]),
                ("library", "-Wcompat\n-Widentities", []),
                ("executable app", "-threaded", []),
            ],
        )

    def test_unreadable_files(self) -> None:
        with self.assertRaises(CabalSyntaxError):
            parse("library\n\tghc-options: -Wall\n")
        with self.assertRaises(CabalSyntaxError):
            parse("library {\n  ghc-options: -Wall\n}\n")
        [fact] = GHC_OPTIONS.read("app.cabal", "library\n\tghc-options: -Wall\n")
        self.assertEqual(fact.origin.path, "app.cabal")
        self.assertNotIsInstance(fact, CompilerOption)

    def test_imports_of_unknown_or_cyclic_stanzas_and_other_sections(self) -> None:
        text = (
            "common a\n  import: a, missing\n  ghc-options: -Wall\n"
            "library\n  import: a\n  source-repository head\n    ghc-options: -Werror\n"
        )
        self.assertEqual([found.value for _, found in values(parse(text), "ghc-options")], ["-Wall"])

    def test_unreadable_test_suites_and_manifests(self) -> None:
        for path, text in (("app.cabal", "library\n\tx: y\n"), ("package.yaml", "tests: [\n")):
            with self.subTest(path=path):
                [fact] = TEST_SUITES.read(path, text)
                self.assertNotIsInstance(fact, Setting)
        self.assertEqual(list(GHC_OPTIONS.read("stack.yaml", "- a list\n")), [])
        self.assertEqual(_members("packages: x\nlibrary\n\tbad\n"), ())

    def test_projects_declare_their_packages(self) -> None:
        self.assertEqual(_members("packages: ./ lib/ tools/*.cabal\n  extra\n"), ("lib", "tools", "extra"))
        self.assertEqual(_members("resolver: lts-22.0\npackages:\n- .\n- ./servant\n"), ("servant",))
        self.assertEqual(_members("packages: https://example.com/p.tar.gz\n"), ())
        self.assertEqual(_members("name: app\n"), ())
        self.assertEqual(_members("resolver: x\npackages:\n- [\n"), ())

    def test_options_of_every_file(self) -> None:
        def options(path: str, text: str) -> list[tuple[str, tuple[str, ...]]]:
            grouped: dict[tuple[str, frozenset[str]], list[str]] = {}
            for fact in GHC_OPTIONS.read(path, text):
                if isinstance(fact, CompilerOption):
                    grouped.setdefault((str(fact.target), fact.applies.requires), []).append(fact.option)
            return [(target, tuple(found)) for (target, _), found in grouped.items()]

        self.assertEqual(options("cabal.project", "package *\n  ghc-options: -Werror\n"), [("package *", ("-Werror",))])
        self.assertEqual(
            options("stack.yaml", 'ghc-options:\n  "$locals": -Wall -Werror\n'),
            [("stack $locals", ("-Wall", "-Werror"))],
        )
        hpack = (
            "ghc-options: -Wall\nexecutables:\n  app:\n    ghc-options: [-threaded]\n"
            "    when:\n    - condition: flag(dev)\n      ghc-options: -Werror\n"
        )
        self.assertEqual(
            options("package.yaml", hpack),
            [("package", ("-Wall",)), ("executables app", ("-threaded",)), ("executables app", ("-Werror",))],
        )
        self.assertEqual(options("package.yaml", ":"), [])
        self.assertEqual(
            options("package.yaml", "library:\n  when: [not a mapping]\n  ghc-options: -O2\n"), [("library", ("-O2",))]
        )
        self.assertEqual(
            options("app.cabal", 'library\n  ghc-options: "-with-rtsopts=-N -A16m" -O2\n'),
            [("library", ("-with-rtsopts=-N -A16m", "-O2"))],
        )
        self.assertEqual(options("app.cabal", 'library\n  ghc-options: "unclosed\n'), [("library", ('"unclosed',))])


class HaskellTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, HASKELL)

    def _cabal(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, "Cabal package", selected, files)

    def test_warnings_in_ghc_options(self) -> None:
        result = self._cabal(compiler_warnings, {"app.cabal": PACKAGE})
        self.assertEqual(
            result,
            Result.warned("missing GHC warning flags: -Wredundant-constraints", "found -Wall -Wcompat -Widentities"),
        )
        everything = self._cabal(compiler_warnings, {"app.cabal": "library\n  ghc-options: -Weverything\n"})
        self.assertEqual(everything.status, Status.PASS)

    def test_warnings_on_the_command_line(self) -> None:
        passed = self._run(compiler_warnings, _ci(f'cabal build --ghc-options="{STRICT}"'))
        self.assertEqual(passed, Result.passed(f"strict GHC warning flags are enabled: {STRICT}"))

    def test_warnings_as_errors(self) -> None:
        behind_a_flag = self._cabal(warnings_as_errors, {"app.cabal": PACKAGE})
        self.assertEqual(behind_a_flag, Result.passed("warnings are treated as errors with -Werror"))
        for command in ("cabal build --ghc-options=-Werror", "stack build --pedantic"):
            with self.subTest(command=command):
                self.assertEqual(self._run(warnings_as_errors, _ci(command)).status, Status.PASS)
        self.assertEqual(
            self._run(warnings_as_errors, _ci("cabal build --ghc-options=-Werror=missing-methods")).status, Status.FAIL
        )

    def test_tests_run(self) -> None:
        self.assertEqual(self._cabal(tests_run, {"app.cabal": PACKAGE, **_ci("cabal test all")}).status, Status.PASS)
        self.assertEqual(
            self._cabal(tests_run, {"app.cabal": PACKAGE, **_ci("stack build --test")}).status, Status.PASS
        )
        self.assertEqual(self._cabal(tests_run, _ci("cabal test")).status, Status.FAIL)
        hpack = {"package.yaml": "name: app\nlibrary:\n  source-dirs: src\ntests:\n  spec:\n    main: Spec.hs\n"}
        self.assertEqual(
            run_in_layout(self, "hpack package", tests_run, {**hpack, **_ci("stack test")}).status, Status.PASS
        )

    def test_hpc_coverage(self) -> None:
        for command in ("cabal test --enable-coverage", "stack test --coverage", "hpc-codecov cabal:spec"):
            with self.subTest(command=command):
                self.assertEqual(
                    self._run(coverage, _ci(command)), Result.passed("branch coverage is reported with HPC")
                )
        self.assertEqual(self._run(coverage, _ci("cabal test")).status, Status.FAIL)

    def test_formatting(self) -> None:
        self.assertEqual(
            self._run(code_formatting, _ci("ormolu --mode check $(git ls-files '*.hs')")).status, Status.PASS
        )
        self.assertEqual(
            self._run(code_formatting, github_steps("uses: haskell-actions/run-fourmolu@v11")).status, Status.PASS
        )
        self.assertEqual(self._run(code_formatting, _ci("ormolu --mode inplace src")).status, Status.FAIL)
        self.assertEqual(self._run(code_formatting, _ci("stylish-haskell -i src/App.hs")).status, Status.FAIL)

    def test_linters(self) -> None:
        self.assertEqual(
            self._run(static_analysis, github_steps("uses: haskell-actions/hlint-run@v2")).status, Status.PASS
        )
        for command in ("hlint src", "weeder", "stan"):
            with self.subTest(command=command):
                self.assertEqual(self._run(static_analysis, _ci(command)).status, Status.PASS)

    def test_ghc_versions(self) -> None:
        matrix = {"ghc": ["9.8", "9.10"], "os": ["ubuntu-latest", "macos-latest"]}
        files = github_job("${{ matrix.os }}", "cabal test", matrix=matrix)
        self.assertIn("2 GHC version(s) (9.10, 9.8)", self._run(platform_matrix, files).message)
        nested = {"versions": [{"ghc": "9.6"}, {"ghc": "9.12"}], "os": ["ubuntu-latest", "windows-latest"]}
        files = github_job("${{ matrix.os }}", "ghcup install ghc --set ${{ matrix.versions.ghc }}", matrix=nested)
        self.assertIn("2 GHC version(s) (9.12, 9.6)", self._run(platform_matrix, files).message)

    def test_stackage_snapshots_are_toolchains_of_their_own(self) -> None:
        files = github_job("${{ matrix.os }}", "stack test --resolver lts-22.0", matrix={"os": ["ubuntu-latest"]})
        self.assertIn("Stackage lts-22.0", self._run(platform_matrix, files).message)

    def test_a_builders_freeze_file_does_not_lock_the_package(self) -> None:
        files = {"app.cabal": PACKAGE, "builders/armv6/cabal.project.freeze": "constraints: any.base ==4.19\n"}
        self.assertEqual(self._cabal(dependency_management, files).status, Status.WARN)

    def test_executables_lock_their_dependencies(self) -> None:
        unlocked = self._cabal(
            dependency_management,
            {"app.cabal": PACKAGE.replace("main-is: Spec.hs", "main-is: Spec.hs\n  build-depends: base")},
        )
        self.assertEqual(unlocked.status, Status.WARN)
        locked = {"app.cabal": PACKAGE, "cabal.project.freeze": "constraints: any.base ==4.19\n"}
        self.assertEqual(self._cabal(dependency_management, locked).status, Status.PASS)
        library = {"app.cabal": "library\n  build-depends: base\n"}
        self.assertEqual(self._cabal(dependency_management, library).status, Status.PASS)

    def test_legacy_licenses_are_spdx(self) -> None:
        mit = fixture_files("well_configured_go")["LICENSE"]
        self.assertEqual(
            self._cabal(license_check, {"app.cabal": "license: MIT\n", "LICENSE": mit}).status, Status.PASS
        )
        mismatch = self._cabal(license_check, {"app.cabal": "name: app\nlicense: BSD3\n", "LICENSE": mit})
        self.assertIn("BSD-3-Clause", " ".join((mismatch.message, *mismatch.details)))

    def test_build_outputs_by_build_system(self) -> None:
        stack = run_in_layout(self, "Stack project", vcs_ignore, {".gitignore": "dist-newstyle/\n"})
        self.assertEqual(stack.status, Status.WARN)
        both = run_in_layout(self, "Stack project", vcs_ignore, {".gitignore": "dist-newstyle/\n.stack-work*\n"})
        self.assertEqual(both.status, Status.PASS)


class RecognitionTests(unittest.TestCase):
    def test_a_pnpm_package_yaml_is_not_hpack(self) -> None:
        with temp_project({"package.yaml": "dependencies:\n  left-pad: ^1.0\n"}) as root:
            self.assertEqual(make_context(root).structure.languages, frozenset())


if __name__ == "__main__":
    unittest.main()
