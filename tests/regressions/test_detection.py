"""Expected failures for detection bugs the corpus audit found (upstream #182 to #189, #228, #230, #283): which
languages, roles, units and CI jobs the validator sees in a project. Each test asserts the correct behaviour; it starts
passing (an "unexpected success") when the bug is fixed, and its decorator goes."""

from __future__ import annotations

import json
import unittest
from collections.abc import Mapping

from project_validator.checks.data_wellformed import data_wellformed
from project_validator.checks.schema_declared import schema_declared
from project_validator.checks.tests_run import tests_run
from project_validator.core import Check, Result, Status
from project_validator.facts.jobs import Job
from project_validator.facts.roles import role
from project_validator.project_map import ProjectStructure
from project_validator.questions.testing import tests
from tests.layouts.openapi import OPENAPI
from tests.layouts.xml_schemas import XSD
from tests.support import GITHUB_WORKFLOW, ci_jobs, github_job, github_steps, make_context, temp_project

RUST = {"Cargo.toml": '[package]\nname = "shop"\nversion = "0.1.0"\n', "src/lib.rs": "#[test]\nfn t() {}\n"}
PYTHON = {"pyproject.toml": "[project]\nname = 'x'\n", "src/x.py": "", "Makefile": "lint:\n\truff check .\n"}
JAVA = {"pom.xml": "<project/>\n", "src/main/java/Main.java": "class Main {}\n"}
MAVEN_TEST_RESOURCE = "src/test/resources/broken.json"
# A `flutter create` output: the pubspec's `flutter:` section and the generated platform runners beside it.
FLUTTER = {
    "pubspec.yaml": "name: shop\nenvironment:\n  sdk: ^3.5.0\ndependencies:\n  flutter:\n    sdk: flutter\nflutter:\n"
    "  uses-material-design: true\n",
    "lib/main.dart": "void main() {}\n",
    "linux/CMakeLists.txt": "cmake_minimum_required(VERSION 3.13)\nproject(runner LANGUAGES CXX)\n",
    "linux/flutter/generated_plugin_registrant.cc": '#include "generated_plugin_registrant.h"\n',
    "ios/Runner.xcodeproj/project.pbxproj": "// !$*UTF8*$!\n",
    "ios/RunnerTests/RunnerTests.swift": "import XCTest\nclass RunnerTests: XCTestCase { func testExample() {} }\n",
    "android/app/src/main/kotlin/com/example/shop/MainActivity.kt": "package com.example.shop\nclass MainActivity\n",
}
# http4s's flake: a developer shell for sbt, with no `packages` or `checks` output.
DEV_SHELL_FLAKE = (
    "{\n  outputs = { self, nixpkgs }: let pkgs = nixpkgs.legacyPackages.x86_64-linux; in {\n"
    "    devShell.x86_64-linux = pkgs.mkShell { packages = [ pkgs.cargo ]; };\n"
    "    devShells.x86_64-linux.default = pkgs.mkShell { packages = [ pkgs.cargo ]; };\n  };\n}\n"
)
SHELL_NIX = "{ pkgs ? import <nixpkgs> {} }: pkgs.mkShell { }\n"
# Racket's multi-package convention (typed-racket, koyo, scribble): a meta-package, a -lib and a -test package.
RACKET_PACKAGES = {
    "foo/info.rkt": '#lang info\n(define collection \'multi)\n(define deps \'("foo-lib" "foo-test"))\n',
    "foo-lib/info.rkt": '#lang info\n(define collection "foo")\n(define deps \'("base"))\n',
    "foo-lib/foo.rkt": "#lang racket/base\n(provide total)\n(define (total xs) (apply + xs))\n",
    "foo-test/info.rkt": '#lang info\n(define collection "tests")\n(define pkg-desc "tests for \\"foo\\"")\n',
    "foo-test/foo-test.rkt": "#lang racket/base\n(module+ test\n  (require rackunit foo)\n"
    "  (check-equal? (total '(1)) 1))\n",
}
BARE_XSD = XSD.replace(' xmlns="urn:example:catalog"\n           targetNamespace="urn:example:catalog"', "")
DART_TEST = "import 'package:test/test.dart';\nvoid main() {\n  test('adds', () {});\n}\n"
# h3's 32-bit sanitizer job: clang by `CC`, and gcc only named by the multilib package it installs.
CLANG_MULTILIB = {
    "runs-on": "ubuntu-latest",
    "env": {"CC": "clang"},
    "steps": [
        {"run": "sudo apt-get install gcc-multilib libc6-dev-i386"},
        {"run": "cmake -DCMAKE_C_FLAGS=-fsanitize=address -B build"},
        {"run": "cmake --build build"},
    ],
}


def _result(check: Check, files: Mapping[str, str]) -> Result:
    """What `check` says of a throw-away project of `files`."""
    with temp_project(files) as root:
        return check.run(make_context(root))


def _structure(files: Mapping[str, str]) -> ProjectStructure:
    """The map of a throw-away project of `files`."""
    with temp_project(files) as root:
        return make_context(root).structure


def _root_unit_languages(files: Mapping[str, str]) -> frozenset[str]:
    [root] = (unit for unit in _structure(files).units if unit.directory == ".")
    return root.languages


def _root_unit_tests(files: Mapping[str, str], language: str) -> tuple[str, ...]:
    """The test files of `language` the root unit of a throw-away project of `files` is said to have."""
    with temp_project(files) as root:
        [answer] = (unit for unit in tests(language, make_context(root).facts).units if unit.unit == ".")
    return answer.definitions()


def _job(files: Mapping[str, str]) -> Job:
    [job] = ci_jobs(files)
    return job


class AuxiliaryLanguageTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #182: a fixture .c or docs .js makes a product language of the unit
    def test_a_language_only_in_auxiliary_files_is_not_the_products(self) -> None:
        """A Rust crate with a test fixture in C and a docs theme script is a Rust product: C and JavaScript are
        auxiliary, and tests-run does not fail for them (ripgrep, glib, fmt, ansible community.general)."""
        files = {**RUST, "tests/fixtures/sleeper.c": "int main() {}\n", "docs/theme.js": "x\n"}
        self.assertEqual(_root_unit_languages(files), frozenset({"Rust"}))
        result = _result(tests_run, {**files, **github_job("ubuntu-latest", "cargo test")})
        self.assertNotEqual(result.status, Status.FAIL, result)

    @unittest.expectedFailure  # upstream #182: .dir-locals.el, an editor settings file, is an Emacs Lisp source
    def test_editor_settings_files_are_not_sources(self) -> None:
        """Emacs's per-directory settings file beside a Clojure project adds no language (clj-kondo, glib, frog)."""
        settings = {".dir-locals.el": '((nil . ((cider-clojure-cli-aliases . ":test"))))\n'}
        structure = _structure({"deps.edn": "{}\n", "src/a.clj": "(ns a)\n", **settings})
        self.assertEqual(structure.languages, frozenset({"Clojure"}))


class RoleBelowSourceRootTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #184: role() stops at src/, pkg/, so testdata below them is product
    def test_a_test_directory_below_a_source_root_names_the_test_role(self) -> None:
        """Maven's src/test, Go's pkg/**/testdata and vite's src/**/__tests__/fixtures hold tests and their data
        (liquibase, golangci-lint, vite, SchemaStore)."""
        for path in (MAVEN_TEST_RESOURCE, "pkg/x/testdata/bad.json", "src/__tests__/fixtures/x/package.json"):
            with self.subTest(path=path):
                self.assertEqual(role(path), "test")

    @unittest.expectedFailure  # upstream #184: a malformed fixture under src/test/resources fails data-wellformed
    def test_malformed_test_data_below_a_source_root_is_reported_not_judged(self) -> None:
        """A deliberately broken JSON fixture under src/test/resources is test data and does not fail the project
        (liquibase's invalidChangeLog.xml, golangci-lint's testdata/json/empty.json)."""
        result = _result(data_wellformed, {**JAVA, MAVEN_TEST_RESOURCE: "{\n"})
        self.assertEqual(result.status, Status.PASS, result)


class FlutterScaffoldingTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #185: Flutter's generated runners make C/C++, Swift and JVM units
    def test_flutter_platform_directories_are_the_flutter_builds_own(self) -> None:
        """The android/, ios/ and linux/ runners beside a pubspec with a `flutter:` section make the project neither
        C/C++, Swift nor JVM, and add no CMake or Xcode build (dart-lang/http, bloc, drift)."""
        structure = _structure(FLUTTER)
        self.assertEqual(structure.languages, frozenset({"Dart"}))
        self.assertEqual(structure.build_systems, frozenset({"pub"}))


class NixDevShellTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #187: a dev-shell flake or shell.nix is judged as a Nix build
    def test_a_dev_shell_is_not_a_nix_build_of_the_product(self) -> None:
        """A flake whose only outputs are devShells, or a lone shell.nix, is a developer environment: the Nix checks
        do not fail a project whose real tests run (http4s, cats, dune)."""
        cases = (
            {"flake.nix": DEV_SHELL_FLAKE, **github_job("ubuntu-latest", "nix develop -c cargo test")},
            {"shell.nix": SHELL_NIX, **github_job("ubuntu-latest", "cargo test")},
        )
        for files in cases:
            with self.subTest(files=sorted(files)):
                result = _result(tests_run, {**RUST, **files})
                self.assertNotEqual(result.status, Status.FAIL, result)


class RacketMultiPackageTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #189: sibling packages fail "no tests found" when X-test has the tests
    def test_the_test_package_tests_its_siblings(self) -> None:
        """In Racket's X, X-lib, X-test layout the -test package holds the suite CI runs with raco test, so the
        meta-package and the library are tested (typed-racket, koyo, scribble)."""
        ci = github_job("ubuntu-latest", "raco pkg install --auto foo-lib/ foo-test/", "raco test foo-test/")
        result = _result(tests_run, {**RACKET_PACKAGES, **ci})
        self.assertEqual(result.status, Status.PASS, result)


class ContentFormatOwnershipTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #283: content-detected formats go to the root unit, not the file's owner
    def test_a_content_detected_format_belongs_to_the_unit_holding_the_files(self) -> None:
        """An XSD without targetNamespace in a Gradle sub-unit is judged there (docbook); an OpenAPI description in
        a Cabal package is judged there (hledger-web), not reported as "no file to judge" for the root."""
        docbook = {"sub/build.gradle": "plugins { id 'java' }\n", "sub/src/main/java/A.java": "", "sub/a.xsd": BARE_XSD}
        with self.subTest(project="docbook"):
            result = _result(schema_declared, docbook)
            self.assertEqual(result.status, Status.FAIL, result)
            self.assertIn("sub/a.xsd: no targetNamespace", result.details)
        hledger = {
            "cabal.project": "packages: web\n",
            "web/web.cabal": "cabal-version: 3.0\nname: web\nversion: 0.1\nlibrary\n  exposed-modules: W\n",
            "web/src/W.hs": "module W where\n",
            "web/config/openapi.yaml": OPENAPI,
        }
        with self.subTest(project="hledger"):
            result = _result(schema_declared, hledger)
            self.assertEqual(result.message, "1 OpenAPI file declares its version (openapi) and info.version")


class TestsCountedPerUnitTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #230: a unit is credited with the test files of every other unit
    def test_a_unit_reports_only_the_test_files_it_owns(self) -> None:
        """The root unit, which owns no tests, has none: the children's test files are theirs (bloc, drift, hledger,
        Pluto.jl)."""
        dart = {
            "tool/gen.dart": "void main() {}\n",
            "packages/a/pubspec.yaml": "name: a\nenvironment:\n  sdk: ^3.5.0\n",
            "packages/a/lib/a.dart": "",
            "packages/a/test/a_test.dart": DART_TEST,
        }
        javascript = {
            "cabal.project": "packages: .\n",
            "app.cabal": "cabal-version: 3.0\nname: app\nversion: 0.1\n",
            "assets/app.js": "",
            "web/test/browser/package.json": json.dumps({"devDependencies": {"@playwright/test": "1"}}),
            "web/test/browser/browse.spec.js": "test('x', () => {});\n",
        }
        for language, files in (("Dart", dart), ("JavaScript", javascript)):
            with self.subTest(language=language):
                self.assertEqual(_root_unit_tests(files, language), ())


class JobAttributionTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #228: make/devenv mark a job C/C++, and every runner gets a compiler
    def test_a_job_is_c_cxx_only_when_it_compiles_c_or_cxx(self) -> None:
        """A job that runs `make lint` in a Python project, or the devenv CLI, is not a C/C++ job; a job that compiles
        nothing has no compiler (compose-spec, country-codes, devenv, dbt-utils, every JVM project)."""
        cases = (
            {**PYTHON, **github_job("ubuntu-latest", "make lint")},
            {**RUST, "flake.nix": DEV_SHELL_FLAKE, **github_job("ubuntu-latest", "devenv shell -- cargo test")},
            {**PYTHON, **github_steps("uses: actions/checkout@v4")},
            {**JAVA, **github_steps("uses: actions/setup-java@v4", "run: mvn test")},
        )
        for files in cases:
            job = _job(files)
            with self.subTest(workflow=files[GITHUB_WORKFLOW]):
                self.assertNotIn("C/C++", job.ecosystems)
                self.assertEqual(job.compilers, frozenset())

    @unittest.expectedFailure  # upstream #228: `apt-get install gcc-multilib` credits gcc with a clang job's build
    def test_a_clang_job_installing_gcc_multilib_is_clang_only(self) -> None:
        """h3's sanitizer jobs set CC=clang and install gcc-multilib for 32-bit libraries: clang builds, gcc does
        not, so gcc gets no sanitizer credit (uber/h3)."""
        workflow = {GITHUB_WORKFLOW: json.dumps({"jobs": {"build": CLANG_MULTILIB}})}
        job = _job({"CMakeLists.txt": "project(h C)\n", "src/h.c": "", **workflow})
        self.assertEqual(job.compilers, frozenset({"clang"}))
