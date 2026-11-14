"""Expected failures for the ecosystem gaps the corpus audit found in Julia, Lua and LaTeX, Perl, Scala, Shell, SQL,
Nix, OCaml, Rust and Zig projects (upstream #267 to #269, #274 to #276, #285 to #288).

Each test asserts the behaviour the upstream issue asks for; it fails until the bug is fixed, when its decorator goes.
"""

from __future__ import annotations

import json
import unittest
from collections.abc import Mapping

from project_validator.checks.ci_build_types import ci_build_types
from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.fuzz_testing import fuzz_testing
from project_validator.checks.hardening import hardening
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.security_scanning import security_scanning
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.type_checking import type_checking
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from tests.support import GITHUB_WORKFLOW, PROJECT_LAYOUTS, github_job, github_steps, make_context, temp_project

CI = "ubuntu-latest"


def _workflow(job: Mapping[str, object]) -> dict[str, str]:
    """A workflow whose one job is `job` (its steps, strategy and environment as GitHub Actions spells them)."""
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"build": {"runs-on": CI, **job}}})}


def _matrix(matrix: Mapping[str, object], *steps: Mapping[str, object]) -> dict[str, str]:
    """A workflow whose one job runs `steps` on every combination of `matrix`."""
    return _workflow({"strategy": {"matrix": dict(matrix)}, "steps": list(steps)})


def _action(uses: str, **inputs: object) -> dict[str, object]:
    return {"uses": uses, "with": inputs}


def _result(check: Check, files: Mapping[str, str]) -> Result:
    with temp_project(files) as root:
        return check.run(make_context(root))


def _run(check: Check, layout: str, files: Mapping[str, str]) -> Result:
    """The result of `check` in a project of the layout called `layout` with `files` added."""
    [found] = (candidate for candidate in PROJECT_LAYOUTS if candidate.name == layout)
    return _result(check, {**found.files, **files})


def _recognised(files: Mapping[str, str]) -> tuple[frozenset[str], frozenset[str]]:
    """The languages of a project with `files`, and the suffixes it leaves unrecognised."""
    with temp_project(files) as root:
        structure = make_context(root).structure
    return structure.languages, frozenset(suffix for suffix, _ in structure.unrecognised_suffixes)


# JuMP.jl's format_check.yml: a julia step that formats, then exits 1 when `git diff` shows a change.
JUMP_FORMAT_CHECK = (
    'using JuliaFormatter\nformat("."; verbose = true)\nout = String(read(Cmd(`git diff`)))\nif isempty(out)\n'
    '    exit(0)\nend\n@error "Some files have not been formatted !!!"\nwrite(stdout, out)\nexit(1)\n'
)


class JuliaTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #267: only the literal `|| exit(1)` makes JuliaFormatter a check
    def test_formatting_then_exiting_non_zero_on_a_git_diff_is_a_gate(self) -> None:
        """A julia step that runs `format(".")`, reads `git diff` and `exit(1)`s when it is not empty fails on a file
        it changed: JuliaFormatter enforces the style (jump-dev/JuMP.jl)."""
        step = {"run": JUMP_FORMAT_CHECK, "shell": "julia --color=yes {0}"}
        result = _run(code_formatting, "Julia package", _workflow({"steps": [step]}))
        self.assertEqual(result.status, Status.PASS, result)


PLENARY_SPEC = {"tests/shop_spec.lua": 'describe("shop", function() end)\n'}
NVIM_PLENARY = 'nvim --headless --noplugin -c "PlenaryBustedDirectory tests"'
L3BUILD_TESTS = {
    "build.lua": 'module = "shop"\n',
    "testfiles/a.lvt": "\\input regression-test\n",
    "testfiles/a.tlg": "",
}
TEAL_SOURCES = {"tlconfig.lua": 'return { source_dir = "src" }\n', "src/shop.tl": "local record S end\nreturn S\n"}


class LuaAndLatexTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #268: nvim's `-c <command>` is taken for busted's `-c` coverage flag
    def test_nvims_c_option_is_not_busteds_coverage_flag(self) -> None:
        """Plenary's busted inside Neovim (`nvim --headless -c "PlenaryBustedDirectory tests"`) collects no coverage:
        without luacov anywhere, coverage FAILs (nvim-telescope/telescope.nvim)."""
        makefile = {"Makefile": f"test:\n\t{NVIM_PLENARY}\n"}
        for name, files in (
            ("direct", github_job(CI, NVIM_PLENARY)),
            ("make test", {**makefile, **github_job(CI, "make test")}),
        ):
            with self.subTest(case=name):
                result = _run(coverage, "Lua sources", {**PLENARY_SPEC, **files})
                self.assertEqual(result.status, Status.FAIL, result)

    @unittest.expectedFailure  # upstream #268: a Neovim plugin's matrix of Neovim versions counts no toolchain
    def test_neovim_versions_are_the_toolchain_axis_of_a_plugin(self) -> None:
        """`rhysd/action-setup-vim` with `neovim: true` and `version: ${{ matrix.rev }}` runs the plugin's tests on
        each Neovim version: 2 OSes x 2 versions (telescope.nvim), not "no Lua version" everywhere."""
        matrix = {"os": ["ubuntu-latest", "macos-latest"], "rev": ["stable", "nightly"]}
        setup = _action("rhysd/action-setup-vim@v1", neovim=True, version="${{ matrix.rev }}")
        files = _matrix(matrix, setup, {"run": NVIM_PLENARY})
        files[GITHUB_WORKFLOW] = files[GITHUB_WORKFLOW].replace(f'"runs-on": "{CI}"', '"runs-on": "${{ matrix.os }}"')
        result = _run(platform_matrix, "Lua sources", {**PLENARY_SPEC, **files})
        self.assertIn("2 OS(es) (linux, macos)", result.message)
        for version in ("nightly", "stable"):
            with self.subTest(version=version):
                self.assertIn(version, result.message)

    @unittest.expectedFailure  # upstream #268: l3build (`l3build check`, .lvt/.tlg) is not LaTeX's test runner
    def test_l3build_check_runs_a_latex_packages_regression_tests(self) -> None:
        """`l3build check` (or `texlua l3build.lua check`) after `zauguin/install-texlive` runs the `.lvt` tests
        against their `.tlg` expectations (latex3/l3build)."""
        for line in ("run: l3build check", "run: texlua l3build.lua check -q -H --show-log-on-error"):
            with self.subTest(line=line):
                files = {**L3BUILD_TESTS, **github_steps("uses: zauguin/install-texlive@v4", line)}
                result = _run(tests_run, "LaTeX document", files)
                self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #268: Teal (.tl sources, `tl check`) is unknown to the Lua profile
    def test_teal_sources_are_recognised_and_tl_check_type_checks_them(self) -> None:
        """`.tl` files beside `tlconfig.lua` are the project's (Teal) sources, not an unrecognised suffix, and
        `tl check` is their type checker (luarocks/luarocks)."""
        languages, unrecognised = _recognised({**TEAL_SOURCES, "src/shop.lua": "return {}\n"})
        self.assertTrue(languages, "no language recognised")
        self.assertNotIn(".tl", unrecognised)
        result = _run(type_checking, "Lua sources", {**TEAL_SOURCES, **github_job(CI, "tl check src/shop.tl")})
        self.assertEqual(result.status, Status.PASS, result)


PERL_TEST = {"t/basic.t": "use Test::More;\nok(1);\ndone_testing;\n"}
# Perl-Critic's inc/Perl/Critic/Module/Build/Standard.pm: a Module::Build action that depends on `test`.
BUILD_ACTION = {
    "Build.PL": "use lib 'inc';\nuse Shop::Build;\nShop::Build->new(module_name => 'Shop')->create_build_script;\n",
    "inc/Shop/Build.pm": "package Shop::Build;\nuse strict;\nuse warnings;\nuse parent 'Module::Build';\n"
    "sub ACTION_authortest {\n    my ($self) = @_;\n    $self->depends_on('test');\n}\n1;\n",
}
TEST_CLASS = {
    "t/lib/TestFor/Shop.pm": "package TestFor::Shop;\nuse strict;\nuse warnings;\nuse Test::Warnings;\n1;\n",
    "t/shop.t": "use lib 't/lib';\nuse TestFor::Shop;\n",
}


class PerlTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #269: `./Build authortest`, defined under inc/, is not a test run
    def test_a_build_action_that_depends_on_test_runs_the_tests(self) -> None:
        """`./Build authortest` runs the tests when `inc/**/*.pm` defines `sub ACTION_authortest` that
        `depends_on('test')` (Perl-Critic/Perl-Critic)."""
        ci = github_job(CI, "perl Build.PL", "./Build authortest")
        result = _run(tests_run, "Perl modules", {**PERL_TEST, **BUILD_ACTION, **ci})
        self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #269: Test::Perl::Critic in the author tests is not perlcritic running
    def test_test_perl_critic_in_the_tests_is_perlcritic(self) -> None:
        """An author test that uses Test::Perl::Critic, run by `prove -l xt`, runs perlcritic over the code
        (Perl-Critic/Perl-Critic; the profile doc says so)."""
        critic = {"xt/critic.t": "use Test::Perl::Critic;\nall_critic_ok();\n", "perlcriticrc": "severity = 3\n"}
        result = _run(static_analysis, "Perl modules", {**critic, **github_job(CI, "prove -l xt")})
        self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #269: Test::Warnings in a test class under t/lib is not read
    def test_test_warnings_in_a_test_class_counts(self) -> None:
        """`use Test::Warnings` in `t/lib/TestFor/*.pm`, loaded by the `t/*.t` files, fails every test on a
        warning (houseabsolute/perl-code-tidyall)."""
        result = _run(warnings_as_errors, "Perl modules", TEST_CLASS)
        self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #269: corpus/ and inc/ are not auxiliary roles, their modules are judged
    def test_corpus_and_inc_hold_no_modules_of_the_product(self) -> None:
        """A module under `corpus/` (Dist::Zilla's test distributions) or `inc/` (bundled build code) is not one of
        the product's modules that must `use strict` (Perl-Critic, perl-code-tidyall)."""
        for path in ("corpus/DZT/lib/DZT/Sample.pm", "inc/Module/Install.pm"):
            with self.subTest(path=path):
                files = {path: "package Sample;\n1;\n", **github_job(CI, "perlcritic lib")}
                result = _run(compiler_warnings, "Perl modules", files)
                self.assertEqual(result.status, Status.PASS, result)


SBT = "sbt Scala"
SCALAFIX_ALIAS = {
    "build.sbt": 'scalaVersion := "3.3.5"\n'
    'addCommandAlias("scalafixCheck", "; scalafix --check ; Test/scalafix --check")\n',
    ".scalafix.conf": "rules = [DisableSyntax]\n",
}
# scalafmt's project/Extensions.scala: the build definition sets the options in Scala code, not in build.sbt.
PROJECT_OPTIONS = {
    "project/Opts.scala": "import sbt._\nimport sbt.Keys._\n\nobject Opts {\n"
    '  val strict = scalacOptions ++= Seq("-Werror", "-Wunused:all", "-deprecation", "-feature")\n}\n'
}
# http4s's build.sbt: an sbt command text in a string literal; its meta-build's options in project/build.sbt.
FATAL_IN_TEXT = {"build.sbt": 'lazy val enableFatalWarnings = """set ThisBuild / scalacOptions += "-Werror""""\n'}
META_BUILD = {"project/build.sbt": 'scalacOptions := Seq("-deprecation")\n'}
SETUP_JAVA = "actions/setup-java@v4"


class ScalaTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #274: sbt command aliases defined in build.sbt are not resolved
    def test_an_sbt_alias_for_scalafix_check_runs_scalafix(self) -> None:
        """`sbt scalafixCheck` runs scalafix when build.sbt's `addCommandAlias("scalafixCheck", "; scalafix --check
        ...")` says so (scalameta/metals)."""
        result = _run(static_analysis, SBT, {**SCALAFIX_ALIAS, **github_job(CI, "sbt scalafixCheck")})
        self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #274: scalacOptions set in project/*.scala are never read
    def test_scalac_options_in_the_build_definitions_scala_code_count(self) -> None:
        """`scalacOptions ++= Seq("-Werror", "-Wunused:all", ...)` in `project/*.scala` are the build's warning
        settings and make warnings fatal (scalameta/scalafmt)."""
        for check in (compiler_warnings, warnings_as_errors):
            with self.subTest(check=check.name):
                result = _run(check, SBT, PROJECT_OPTIONS)
                self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #274: -Werror in a string literal and the meta-build's options credited
    def test_text_that_is_not_a_compiler_setting_is_not_credited(self) -> None:
        """`-Werror` inside a string literal (an sbt command text) is no setting, and `project/build.sbt` sets the
        options of the build definition's own compilation, not the product's (http4s/http4s)."""
        cases = {"string literal": (warnings_as_errors, FATAL_IN_TEXT), "meta-build": (compiler_warnings, META_BUILD)}
        for name, (check, files) in cases.items():
            with self.subTest(case=name):
                result = _run(check, SBT, files)
                self.assertEqual(result.status, Status.FAIL, result)

    @unittest.expectedFailure  # upstream #274: sbt-typelevel bundles sbt-tpolecat, which is not known
    def test_sbt_typelevel_brings_tpolecats_strict_warning_set(self) -> None:
        """`addSbtPlugin("org.typelevel" % "sbt-typelevel" % ...)` enables the whole strict scalac set, as
        sbt-tpolecat (which it bundles) does (typelevel/cats)."""
        plugin = {"project/plugins.sbt": 'addSbtPlugin("org.typelevel" % "sbt-typelevel" % "0.7.7")\n'}
        result = _run(compiler_warnings, SBT, plugin)
        self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #274: `'++ ${{ matrix.scala }}'` with binary versions reads as default
    def test_a_matrix_scala_version_switched_to_with_a_space_is_counted(self) -> None:
        """`sbt '++ ${{ matrix.scala }}' test` over `scala: [2.12, 2.13, 3]` builds each Scala version on each JDK:
        6 combinations, not 2 "Scala default" ones (typelevel/cats, http4s/http4s)."""
        matrix = {"java": ["8", "17"], "scala": ["2.12", "2.13", "3"]}
        setup = _action(SETUP_JAVA, **{"java-version": "${{ matrix.java }}"})
        result = _run(platform_matrix, SBT, _matrix(matrix, setup, {"run": "sbt '++ ${{ matrix.scala }}' test"}))
        self.assertIn("JDK 8 / Scala 2.12", result.message)
        self.assertIn("6 combination(s)", result.message)

    @unittest.expectedFailure  # upstream #274: `${{ matrix.java || '17' }}` as java-version is "JDK default"
    def test_a_jdk_version_from_a_fallback_expression_is_read(self) -> None:
        """`java-version: ${{ matrix.java || '17' }}` over `java: ['17', '21']` names JDK 17 and JDK 21
        (scalameta/scalafmt)."""
        setup = _action(SETUP_JAVA, **{"java-version": "${{ matrix.java || '17' }}"})
        result = _run(platform_matrix, SBT, _matrix({"java": ["17", "21"]}, setup, {"run": "sbt test"}))
        self.assertIn("2 JDK or Scala version(s) (JDK 17, JDK 21)", result.message)


SHELL = "Shell scripts"
# nvm's urchin tests: executable files with no suffix, one test each, under test/<speed>/<suite>/.
URCHIN_TESTS = {
    "test/fast/Unit tests/nvm ls": "#!/bin/sh\n. ../../../nvm.sh\nnvm ls\n",
    "test/fast/Unit tests/nvm use": "#!/bin/sh\n. ../../../nvm.sh\nnvm use\n",
}
ZUNIT_TEST = {"plugins/dotenv/tests/basic.zunit": "#!/usr/bin/env zunit\n\n@test 'parses' {\n  assert 1 equals 1\n}\n"}
BATS_TEST = {"test/shop.bats": '@test "sums" {\n  true\n}\n'}


class ShellTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #275: urchin's suffix-less test scripts under test/ are "no tests"
    def test_urchin_runs_the_suffix_less_tests_under_its_directory(self) -> None:
        """`urchin test/fast` (also through `make test-fast`) runs every script under the directory: those are the
        tests (nvm-sh/nvm)."""
        makefile = {"Makefile": "URCHIN := urchin\ntest-fast:\n\t$(URCHIN) test/fast\n"}
        for name, files in (
            ("urchin", github_job(CI, "urchin test/fast")),
            ("make", {**makefile, **github_job(CI, "make test-fast")}),
        ):
            with self.subTest(case=name):
                result = _run(tests_run, SHELL, {**URCHIN_TESTS, **files})
                self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #275: .zsh-theme scripts and .zunit tests are unrecognised suffixes
    def test_zsh_themes_are_shell_scripts_and_zunit_files_are_tests(self) -> None:
        """`themes/*.zsh-theme` are zsh scripts and `tests/*.zunit` are zunit tests: neither is an unrecognised suffix,
        and with the tests never run, tests-run FAILs without saying "no tests found" (ohmyzsh/ohmyzsh)."""
        for files in ({"themes/robbyrussell.zsh-theme": "PROMPT='%n'\n"}, ZUNIT_TEST):
            with self.subTest(files=files):
                languages, unrecognised = _recognised(files)
                self.assertEqual((languages, unrecognised), (frozenset({"Shell"}), frozenset()))
        result = _run(tests_run, SHELL, {**ZUNIT_TEST, **github_job(CI, "shellcheck src/shop.sh")})
        self.assertEqual(result.status, Status.FAIL)
        self.assertNotIn("no tests found", result.message)

    @unittest.expectedFailure  # upstream #275: bash versions in a matrix are no toolchain axis for Shell
    def test_bash_versions_are_a_toolchain_axis(self) -> None:
        """A matrix of bash versions each running the bats tests (`docker run bash:${{ matrix.bash-version }} bats
        test`) is a toolchain axis the platform matrix counts (bats-core/bats-core)."""
        matrix = {"bash-version": ["3.2", "4.4", "5.1"]}
        files = _matrix(matrix, {"run": "docker run bash:${{ matrix.bash-version }} bats test"})
        result = _run(platform_matrix, SHELL, {**BATS_TEST, **files})
        self.assertNotEqual(result.status, Status.SKIP, result)
        for version in matrix["bash-version"]:
            with self.subTest(version=version):
                self.assertIn(version, result.message)


# A PostgreSQL extension built with PGXS (pgvector, pgaudit): its control file, SQL scripts, C sources and the
# pg_regress tests under test/sql with their expected output.
PGXS_EXTENSION = {
    "shop.control": "comment = 'shop'\ndefault_version = '1.0'\nmodule_pathname = '$libdir/shop'\n",
    "Makefile": "EXTENSION = shop\nMODULE_big = shop\nDATA = $(wildcard sql/*--*.sql)\nOBJS = src/shop.o\n"
    "TESTS = $(wildcard test/sql/*.sql)\nREGRESS = $(patsubst test/sql/%.sql,%,$(TESTS))\nTAP_TESTS = 1\n"
    "PG_CONFIG ?= pg_config\nPGXS := $(shell $(PG_CONFIG) --pgxs)\ninclude $(PGXS)\n",
    "sql/shop--1.0.sql": "CREATE FUNCTION total(int[]) RETURNS int AS 'MODULE_PATHNAME' LANGUAGE C;\n",
    "src/shop.c": '#include "postgres.h"\n',
    "test/sql/total.sql": "SELECT total(ARRAY[1, 2]);\n",
    "test/expected/total.out": " total\n-------\n     3\n",
    "test/t/001_basic.pl": "use PostgreSQL::Test::Cluster;\nuse Test::More;\nok(1);\ndone_testing;\n",
}
C_MAKEFILE = {"Makefile": "all:\n\t$(CC) -o shop src/shop.c\n", "src/shop.c": "int main(void) { return 0; }\n"}


class SqlTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #276: a PGXS extension (control file, sql/, test/sql) is plain C
    def test_a_postgresql_extension_is_an_sql_project(self) -> None:
        """A `*.control` file, a PGXS Makefile (`EXTENSION =`, `DATA = sql/*.sql`) and `test/sql` + `test/expected`
        make SQL one of the project's languages; `.sql` and `.control` are not unrecognised (pgvector, pgaudit)."""
        languages, unrecognised = _recognised(PGXS_EXTENSION)
        self.assertIn("SQL", languages)
        self.assertFalse(unrecognised & {".sql", ".control"}, unrecognised)

    @unittest.expectedFailure  # upstream #276: pg_regress (REGRESS) and TAP tests run by installcheck are unknown
    def test_installcheck_runs_the_pg_regress_and_tap_tests(self) -> None:
        """`make installcheck` runs the `REGRESS` tests under test/sql and `make prove_installcheck` the TAP tests
        under test/t: the extension's tests run (pgvector/pgvector, pgaudit/pgaudit)."""
        for target in ("installcheck", "prove_installcheck"):
            with self.subTest(target=target):
                result = _result(tests_run, {**PGXS_EXTENSION, **github_job(CI, "make", f"make {target}")})
                self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #276: scan-build is a transparent wrapper, never a static analyzer run
    def test_scan_build_with_status_bugs_is_a_static_analyzer_run(self) -> None:
        """`scan-build --status-bugs make` runs the Clang Static Analyzer over the build and fails the job on any
        finding (pgvector/pgvector)."""
        result = _result(static_analysis, {**C_MAKEFILE, **github_job(CI, "scan-build --status-bugs make")})
        self.assertEqual(result.status, Status.PASS, result)


NIX = "Nix flake"
# home-manager's treefmt.toml: what `nix fmt` runs through treefmt.
TREEFMT = {
    "treefmt.toml": '[formatter.statix]\ncommand = "treefmt-statix"\nincludes = [ "*.nix" ]\n\n'
    '[formatter.deadnix]\ncommand = "deadnix"\noptions = [ "--edit" ]\nincludes = [ "*.nix" ]\n'
}
# home-manager's update-maintainers.yml: a bot formats one generated file and commits it when it changed.
BOT_COMMIT = "if git diff --quiet all-maintainers.nix; then echo same; else git commit -am x; fi"
DEVENV_HOOKS = {
    "devenv.nix": "{ pkgs, ... }:\n{\n  git-hooks = {\n    package = pkgs.prek;\n    hooks.rustfmt.enable = true;\n"
    "  };\n}\n"
}
RUST_TEST = {"src/lib.rs": "#[cfg(test)]\nmod tests {\n    #[test]\n    fn total() {}\n}\n"}


class NixTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #285: treefmt's `--ci` (fail-on-change) is not a checking flag
    def test_treefmts_ci_flag_makes_nix_fmt_a_check(self) -> None:
        """`nix fmt -- --ci` (treefmt's `--fail-on-change --no-cache`) fails on an unformatted file: CI enforces the
        style (ryantm/agenix, nix-community/home-manager)."""
        for line in ("nix fmt -- --ci", "nix fmt . -- --ci"):
            with self.subTest(line=line):
                result = _run(code_formatting, NIX, github_job(CI, line))
                self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #285: `git diff --quiet` in an `if` condition counts as a failing step
    def test_a_git_diff_quiet_in_an_if_condition_is_not_a_failing_step(self) -> None:
        """`nix fmt one-file.nix` followed by `if git diff --quiet ...; then ...; else git commit ...; fi` commits what
        changed; nothing fails, so the style is not enforced (nix-community/home-manager)."""
        result = _run(code_formatting, NIX, github_job(CI, "nix fmt all-maintainers.nix", BOT_COMMIT))
        self.assertNotEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #285: treefmt.toml, which says what `nix fmt` runs, is never read
    def test_treefmt_toml_says_which_lints_nix_fmt_runs(self) -> None:
        """With `treefmt.toml` naming statix and deadnix, `nix fmt -- --ci` runs them: the Nix lints are enabled and
        a static analyzer runs (nix-community/home-manager, nix-community/disko)."""
        for check in (static_analysis, compiler_warnings):
            with self.subTest(check=check.name):
                result = _run(check, NIX, {**TREEFMT, **github_job(CI, "nix fmt -- --ci")})
                self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #285: `devenv shell -- cmd` is no launcher, devenv git-hooks unknown
    def test_devenv_shell_runs_the_command_and_its_git_hooks_are_preks(self) -> None:
        """`devenv shell -- cargo nextest run` runs the tests, and `devenv shell -- prek run -a` runs the hooks
        `devenv.nix` enables (rustfmt), which is the formatter checking (cachix/devenv)."""
        tests = _run(tests_run, "Cargo Rust", {**RUST_TEST, **github_job(CI, "devenv shell -- cargo nextest run")})
        with self.subTest(case="nextest"):
            self.assertEqual(tests.status, Status.PASS, tests)
        hooks = _run(code_formatting, "Cargo Rust", {**DEVENV_HOOKS, **github_job(CI, "devenv shell -- prek run -a")})
        with self.subTest(case="prek"):
            self.assertIn("Rust: CI enforces the rustfmt style", hooks.message)


DUNE = "dune project"
LEXER_FLAGS = {
    "lib/dune": "(library\n (name shop))\n\n(ocamllex\n (modules lexer)\n (flags -ml))\n",
    "lib/lexer.mll": "",
}
FIXTURE_ENV = {
    "test/plugin.t/plugin/dune": "(env (_ (flags -w -33)))\n",
    "test/plugin.t/run.t": "  $ dune build\n",
}


class OCamlTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #286: ocamllex `(flags -ml)` and fixture `(env …)` drop :standard
    def test_lexer_flags_and_test_fixtures_are_not_the_products_compiler_flags(self) -> None:
        """An `(ocamllex ... (flags -ml))` stanza's flags are the lexer generator's, and an `(env ...)` inside a cram
        test's fixture is the fixture's: neither drops the dev profile's warnings (ocaml/dune)."""
        cases = {
            "ocamllex": (compiler_warnings, LEXER_FLAGS),
            "ocamllex errors": (warnings_as_errors, LEXER_FLAGS),
            "fixture env": (compiler_warnings, FIXTURE_ENV),
        }
        for name, (check, files) in cases.items():
            with self.subTest(case=name):
                result = _run(check, DUNE, {**files, **github_job(CI, "dune build")})
                self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #286: a matrix variable `ocamlv` of compiler versions reads as default
    def test_a_matrix_of_compiler_versions_built_by_a_script_is_counted(self) -> None:
        """`ocamlv: [4.14.4, 5.5.0]` passed to the script that builds the compiler (`.github/scripts/main/ocaml-cache.sh
        ${{ matrix.ocamlv }}`) is 2 OCaml versions, not "1 (default)" (ocaml/opam)."""
        steps = (
            {"run": "bash -exu .github/scripts/main/ocaml-cache.sh ${{ runner.os }} ${{ matrix.ocamlv }}"},
            {"run": "opam exec -- dune build"},
        )
        result = _run(platform_matrix, DUNE, _matrix({"ocamlv": ["4.14.4", "5.5.0"]}, *steps))
        self.assertIn("2 OCaml version(s) (4.14.4, 5.5.0)", result.message)

    @unittest.expectedFailure  # upstream #286: ocaml/setup-ocaml/lint-fmt, which runs `dune build @fmt`, unknown
    def test_setup_ocamls_lint_fmt_action_is_the_format_check(self) -> None:
        """`uses: ocaml/setup-ocaml/lint-fmt@v3` runs `dune build @fmt` and fails on unformatted files: with an
        `.ocamlformat`, CI runs ocamlformat (ocsigen/lwt)."""
        steps = github_steps("uses: ocaml/setup-ocaml@v3", "uses: ocaml/setup-ocaml/lint-fmt@v3")
        result = _run(code_formatting, DUNE, {".ocamlformat": "version = 0.27.0\n", **steps})
        self.assertEqual(result.status, Status.PASS, result)


RUST = "Cargo Rust"
CONFIG_CLIPPY = "cargo --config .cargo/ci.toml clippy --all-targets -- -D warnings -D clippy::pedantic"
# ruff's workspace: unsafe_code only warned about, one member crate forbidding it, another using it.
UNSAFE_WORKSPACE = {
    "Cargo.toml": '[workspace]\nmembers = ["crates/a", "crates/b"]\n\n[workspace.lints.rust]\nunsafe_code = "warn"\n',
    "crates/a/Cargo.toml": '[package]\nname = "a"\n\n[lints]\nworkspace = true\n',
    "crates/a/src/lib.rs": "pub fn first(bytes: &[u8]) -> u8 { unsafe { *bytes.as_ptr() } }\n",
    "crates/b/Cargo.toml": '[package]\nname = "b"\n\n[lints]\nworkspace = true\n',
    "crates/b/src/lib.rs": "#![forbid(unsafe_code)]\npub fn total() {}\n",
}
INHERITED_PROFILE = {"Cargo.toml": '[package]\nname = "shop"\n\n[profile.fast]\ninherits = "release"\nlto = true\n'}


class RustTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #287: `cargo --config <file> clippy` is not read as clippy
    def test_cargo_options_before_the_clippy_subcommand_are_skipped(self) -> None:
        """`cargo --config .cargo/ci.toml clippy ...` runs clippy: the analyzer runs and `cargo clippy` is among the
        lint settings (nushell/nushell)."""
        for check in (static_analysis, compiler_warnings):
            with self.subTest(check=check.name):
                result = _run(check, RUST, github_job(CI, CONFIG_CLIPPY))
                self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #287: `-Dclippy::pedantic` without a space misses the pedantic regex
    def test_pedantic_denied_without_a_space_after_d_counts(self) -> None:
        """`cargo clippy -- -Dwarnings -Dclippy::pedantic` enables every lint setting (serde-rs/serde)."""
        result = _run(compiler_warnings, RUST, github_job(CI, "cargo clippy -- -Dwarnings -Dclippy::pedantic"))
        self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #287: one member crate's forbid(unsafe_code) is credited workspace-wide
    def test_a_workspace_that_only_warns_on_unsafe_code_does_not_forbid_it(self) -> None:
        """With `[workspace.lints.rust] unsafe_code = "warn"` and `unsafe {` in one crate, one other crate's
        `#![forbid(unsafe_code)]` does not make the build forbid unsafe code (astral-sh/ruff)."""
        result = _result(security_scanning, {**UNSAFE_WORKSPACE, **github_job(CI, "cargo build --workspace")})
        self.assertNotEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #287: warnings-as-errors is "not applicable to Rust", RUSTFLAGS ignored
    def test_rustflags_denying_warnings_is_warnings_as_errors(self) -> None:
        """`RUSTFLAGS: -Dwarnings` in the job's environment makes every warning fail the build: Rust is judged and
        PASSes, not skipped (tokio-rs/tokio, serde-rs/serde)."""
        job = {"env": {"RUSTFLAGS": "-Dwarnings"}, "steps": [{"run": "cargo build"}]}
        result = _run(warnings_as_errors, RUST, _workflow(job))
        self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #287: `-D warnings` in RUSTDOCFLAGS is credited as a rustc setting
    def test_rustdocflags_are_not_the_compilers_lint_settings(self) -> None:
        """`RUSTDOCFLAGS: -D warnings` on a `cargo doc` step denies rustdoc's lints only: no Rust lint setting is found
        (BurntSushi/ripgrep)."""
        step = {"run": "cargo doc --no-deps --workspace", "env": {"RUSTDOCFLAGS": "-D warnings"}}
        result = _run(compiler_warnings, RUST, _workflow({"steps": [step]}))
        self.assertEqual(result.status, Status.FAIL, result)

    @unittest.expectedFailure  # upstream #287: a custom profile inheriting release yields no build type
    def test_a_profile_that_inherits_release_builds_release(self) -> None:
        """`cargo build --profile fast` with `[profile.fast] inherits = "release"` is a Release build: the job misses
        Debug and the sanitizer builds, not Release (BurntSushi/ripgrep's release-lto)."""
        result = _run(ci_build_types, RUST, {**INHERITED_PROFILE, **github_job(CI, "cargo build --profile fast")})
        self.assertEqual(result.details, ("linux / default: missing Debug, Debug + sanitizers, Release + sanitizers",))

    @unittest.expectedFailure  # upstream #287: rust-toolchain.toml's channel is not the jobs' toolchain
    def test_rust_toolchain_toml_pins_the_toolchain_plain_cargo_uses(self) -> None:
        """With `rust-toolchain.toml` saying `channel = "1.80"`, a job running `cargo test` runs Rust 1.80, not the
        runner's default (nushell/nushell, astral-sh/ruff)."""
        pinned = {"rust-toolchain.toml": '[toolchain]\nchannel = "1.80"\n'}
        result = _run(platform_matrix, RUST, {**pinned, **github_job(CI, "cargo test")})
        self.assertIn("1 Rust toolchain(s) (1.80)", result.message)


ZIG = "Zig build"
# http.zig's build.zig: a module for the library, an executable per example.
EXAMPLES_ONLY = {
    "build.zig": 'const std = @import("std");\n\npub fn build(b: *std.Build) void {\n'
    '    _ = b.addModule("shop", .{ .root_source_file = b.path("src/main.zig") });\n'
    '    const exe = b.addExecutable(.{ .name = "example", .root_source_file = b.path("examples/x.zig") });\n'
    "    b.installArtifact(exe);\n}\n",
    "examples/x.zig": "",
}
AFL_SHIM = {
    "pkg/afl.c": "// Manual expansion of __AFL_LOOP(UINT_MAX): persistent mode loop.\nint main(void) { return 0; }\n"
}
MANIFEST = {
    "build.zig.zon": '.{\n    .name = "shop",\n    .version = "0.1.0",\n    .minimum_zig_version = "0.14.0",\n}\n'
}
FUZZ_STEP = {
    "build.zig": 'const std = @import("std");\n\npub fn build(b: *std.Build) void {\n'
    '    _ = b.step("fuzz", "Run fuzzers");\n}\n',
    "src/fuzz.zig": 'const std = @import("std");\n\ntest "fuzz" {\n    try std.testing.fuzz({}, fuzzOne, .{});\n}\n',
}


class ZigTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #288: any addExecutable, examples included, means a binary to harden
    def test_a_library_whose_only_executables_are_examples_has_no_binary_to_harden(self) -> None:
        """A build.zig whose only `addExecutable` builds `examples/*.zig` is a library: hardening is skipped, not
        failed for a missing ReleaseSafe build (karlseguin/http.zig, mitchellh/libxev)."""
        result = _run(hardening, ZIG, EXAMPLES_ONLY)
        self.assertEqual(result.status, Status.SKIP, result)

    @unittest.expectedFailure  # upstream #288: an __AFL_LOOP in a comment makes a C file a fuzz target
    def test_an_afl_macro_named_in_a_comment_is_not_a_fuzz_target(self) -> None:
        """A `.c` file whose only `__AFL_LOOP` is in a comment (ghostty's AFL++ packaging shim) holds no fuzz
        target: "no fuzz targets found" (ghostty-org/ghostty)."""
        result = _run(fuzz_testing, "CMake C", AFL_SHIM)
        self.assertIn("no fuzz targets found", result.message)

    @unittest.expectedFailure  # upstream #288: setup-zig without `version` installs the manifest's minimum
    def test_setup_zig_without_a_version_installs_the_manifests_minimum(self) -> None:
        """`mlugg/setup-zig` with no `version` input installs `build.zig.zon`'s `minimum_zig_version`: the job's Zig
        is 0.14.0, not "default" (Hejsil/zig-clap, zls, libxev, ghostty)."""
        files = {**MANIFEST, **github_steps("uses: mlugg/setup-zig@v2", "run: zig build test")}
        result = _run(platform_matrix, ZIG, files)
        self.assertIn("1 Zig version(s) (0.14.0)", result.message)

    @unittest.expectedFailure  # upstream #288: fuzz-testing is "not applicable to Zig"; zig build fuzz unknown
    def test_zig_build_fuzz_and_test_fuzz_run_the_fuzzers(self) -> None:
        """`zig build fuzz` (a fuzz step in build.zig) and `zig build test --fuzz` (std.testing.fuzz) run the
        project's fuzzers: Zig is judged and PASSes (tigerbeetle/tigerbeetle)."""
        for line in ("zig build fuzz -- smoke", "zig build test --fuzz"):
            with self.subTest(line=line):
                result = _run(fuzz_testing, ZIG, {**FUZZ_STEP, **github_job(CI, line)})
                self.assertEqual(result.status, Status.PASS, result)
