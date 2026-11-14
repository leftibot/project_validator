"""Expected failures for repository-hygiene bugs the corpus audit found (upstream #235 to #246: committed artifacts,
ignore files, licenses, badges, the map, security policies, dependency updates and management). Each test asserts the
correct behaviour; it starts passing (an "unexpected success") when the bug is fixed, and its decorator goes."""

from __future__ import annotations

import shutil
import unittest
from collections.abc import Mapping

from project_validator.checks.committed_artifacts import committed_artifacts
from project_validator.checks.dependency_management import dependency_management
from project_validator.checks.dependency_updates import dependency_updates
from project_validator.checks.license import license_
from project_validator.checks.security_policy import security_policy
from project_validator.checks.status_badges import status_badges
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.core import Check, Result, Status
from project_validator.facts.licenses import LicenseFile
from project_validator.project_map import ProjectStructure
from tests.support import CMAKE_PROJECT, FIXTURES, github_job, make_context, temp_project
from tests.test_project import git

MIT = (FIXTURES / "well_configured_c_cpp" / "LICENSE").read_text(encoding="utf-8")
GPL_2 = "GNU GENERAL PUBLIC LICENSE\n   Version 2, June 1991\n"
CC0 = "Creative Commons Legal Code\n\nCC0 1.0 Universal\n\nStatement of Purpose\n"
GO_MODULE = {"go.mod": "module example.com/x\n", "main.go": "package main\n", "go.sum": ""}
C_PROJECT = {"CMakeLists.txt": CMAKE_PROJECT.replace("CXX", "C"), "a.c": ""}
CI_BADGE = "![ci](https://github.com/o/r/actions/workflows/ci.yml/badge.svg)\n"

# What a committed-artifacts rule flags by name although the files are sources, fixtures or settings (upstream #235).
NOT_BUILD_OUTPUTS: dict[str, dict[str, str]] = {
    "a Dart source directory named build/ (drift)": {"pubspec.yaml": "name: drift\n", "lib/src/build/a.dart": ""},
    "Cloud Build pipelines in build/ (terraform-google)": {"scripts/x.py": "", "build/ci.yaml": "steps: []\n"},
    "a packaging-source dist/ (ghostty)": {"tool.py": "", "dist/README.md": "# packaging\n"},
    "tracked shell scripts in bin/ (fzf)": {**GO_MODULE, "bin/tool.sh": "#!/bin/sh\n"},
    "a Julia environment named coverage/ (Documenter)": {
        "Project.toml": 'name = "D"\n',
        "src/D.jl": "",
        "coverage/Project.toml": "[deps]\n",
        "assets/x.js": "",
    },
    "Bundler settings in a test fixture (puma)": {
        "Gemfile": "source 'https://rubygems.org'\n",
        "lib/x.rb": "",
        "test/fixture_app/.bundle/config": 'BUNDLE_PATH: "vendor/bundle"\n',
    },
    "egg-info fixtures under tests/ (poetry)": {
        "pyproject.toml": "[project]\nname = 'p'\n",
        "src/p.py": "",
        "tests/fixtures/demo.egg-info/PKG-INFO": "Name: demo\n",
    },
    "build scripts away from the Docusaurus site (prettier)": {
        "website/docusaurus.config.js": "module.exports = {};\n",
        "scripts/build/build.js": "",
    },
    "the mdBook source directory (polylux)": {"book/book.toml": '[book]\nsrc = "src"\n', "book/src/SUMMARY.md": ""},
    "a shell wrapper named .exe (dune)": {**C_PROJECT, "dune.exe": "#!/usr/bin/env sh\nexec _boot/dune.exe\n"},
    "a zero-byte fixture .exe (glib)": {**C_PROJECT, "tests/fixtures/autorun.exe": ""},
    "a sample presets file under docs/ (llama.cpp)": {**C_PROJECT, "docs/x/CMakeUserPresets.json": '{"version": 5}'},
    "a Java module descriptor named .test (tigerbeetle)": {**GO_MODULE, "java/module-info.test": "open module x {}\n"},
    ".class fixtures beside their sources (commons-lang)": {
        "pom.xml": "<project/>\n",
        "src/test/resources/x/Foo.class": "",
        "src/test/resources/x/Foo.java": "",
    },
    "fixture node_modules trees (vite)": {
        "package.json": '{"name": "vite"}\n',
        "index.js": "",
        "tests/fixtures/pkg/node_modules/dep/index.js": "",
    },
}

# (base files, ignore entries written as the project writes them, the literal entries the check wants); both ignore
# the same outputs (upstream #236).
TEX_LEFTOVERS = "*.aux\n*.log\n*.out\n*.toc\n*.fls\n*.fdb_latexmk\n"
IGNORE_SPELLINGS: dict[str, tuple[dict[str, str], str, str]] = {
    "*.pyc* (scikit-learn)": ({"a.py": ""}, "*.pyc*\n", "*.pyc\n"),
    "site*/ (mkdocs)": ({"mkdocs.yml": "site_name: x\n", "docs/index.md": ""}, "site*/\n", "site/\n"),
    "blib* (tidyall)": (
        {"Makefile.PL": "", "lib/Foo.pm": "package Foo;\n"},
        "blib*\ncover_db*\nMYMETA.*\n",
        "blib/\ncover_db/\nMYMETA.*\n",
    ),
    "*.gz (l3build)": (
        {"main.tex": "\\documentclass{article}\n\\begin{document}x\\end{document}\n"},
        "*.gz\n" + TEX_LEFTOVERS,
        "*.synctex.gz\n" + TEX_LEFTOVERS,
    ),
    "a whitelist (pandoc)": (
        {"pandoc.cabal": "name: pandoc\nversion: 1\n", "stack.yaml": "resolver: lts\n", "src/A.hs": ""},
        "/*\n/.*\n!/src\n!pandoc.cabal\n!stack.yaml\n",
        "dist-newstyle/\n.stack-work/\n",
    ),
    "a crate's own target path (deno std)": (
        {"sub/Cargo.toml": "[package]\nname = 's'\nversion = '0.1.0'\n", "sub/src/lib.rs": ""},
        "sub/target\n",
        "target/\n",
    ),
    "/lisp/*.elc (magit)": (
        {"lisp/foo.el": ";;; foo.el\n"},
        "/lisp/*.elc\n/lisp/*-autoloads.el\n",
        "*.elc\n*-autoloads.el\n",
    ),
}

# (the project with the output ignored where the unit is, the same with the entry at the root) (upstream #237).
SPHINX_DOCS = {"docs/conf.py": "project = 'x'\n", "docs/index.rst": "", "src/a.py": ""}
HUGO_SITE = {"docs/hugo.yaml": "title: x\n", "docs/content/_index.md": ""}
NPM_UNIT = {"web/package.json": '{"name": "web"}\n', "web/index.js": ""}
GRADLE_UNIT = {"sub/build.gradle.kts": "", "sub/src/main/java/A.java": ""}
PER_UNIT_IGNORES: dict[str, tuple[dict[str, str], dict[str, str]]] = {
    "docs/.gitignore ignores Sphinx's _build (PostgREST)": (
        {**SPHINX_DOCS, ".gitignore": "*.pyc\n", "docs/.gitignore": "_build\n"},
        {**SPHINX_DOCS, ".gitignore": "*.pyc\n_build/\n"},
    ),
    "docs/_build/ anchored at the root (rich)": (
        {**SPHINX_DOCS, ".gitignore": "*.pyc\ndocs/_build/\n"},
        {**SPHINX_DOCS, ".gitignore": "*.pyc\n_build/\n"},
    ),
    "the Hugo site's own .gitignore (golangci-lint)": (
        {**HUGO_SITE, ".gitignore": "*.log\n", "docs/.gitignore": "public/\nresources/\n"},
        {**HUGO_SITE, ".gitignore": "*.log\npublic/\nresources/\n"},
    ),
    "the npm unit's own .gitignore (koyo, laravel)": (
        {**NPM_UNIT, ".gitignore": "compiled\n", "web/.gitignore": "node_modules/\ndist/\ncoverage/\n"},
        {**NPM_UNIT, ".gitignore": "compiled\nnode_modules/\ndist/\ncoverage/\n"},
    ),
    "the Gradle unit's own .gitignore (guava)": (
        {**GRADLE_UNIT, ".gitignore": "target/\n", "sub/.gitignore": ".gradle\nbuild\n*.class\n"},
        {**GRADLE_UNIT, ".gitignore": "target/\n.gradle/\nbuild/\n*.class\n"},
    ),
}

# License texts and declarations the audit found unrecognised, and the identifier each names (upstream #238).
PERL_TERMS = (
    "Terms of Perl itself\n\na) the GNU General Public License as published by the Free Software Foundation; either"
    ' version 1, or (at your option) any later version, or\nb) the "Artistic License"\n'
)
POSTGRESQL = (
    "PostgreSQL License\n\nCopyright (c) 1996-2026, PostgreSQL Global Development Group\n\nPermission to use, copy,"
    " modify, and distribute this software and its documentation for any purpose, without fee, and without a written"
    " agreement is hereby granted, provided that the above copyright notice and this paragraph and the following two"
    " paragraphs appear in all copies.\n"
)
QUOTED_MIT = "DataFrames.jl is licensed under the MIT License:\n\n> " + MIT.replace(
    "obtaining a copy", "obtaining\n> a copy"
)
CC_BY = 'Attribution 4.0 International\n\nCreative Commons Corporation ("Creative Commons") is not a law firm\n'
CC_BY_NC_NOTICE = (
    "This work is licensed under the Creative Commons Attribution-NonCommercial 4.0 International License.\n"
)
R_PACKAGE = {"DESCRIPTION": "Package: foo\nVersion: 0.1\nLicense: MIT + file LICENSE\n", "R/foo.R": ""}
LICENSE_CASES: dict[str, tuple[dict[str, str], str]] = {
    "EPL-1.0 (clj-kondo)": ({"LICENSE": "Eclipse Public License - v 1.0\n\nTHE ACCOMPANYING PROGRAM\n"}, "EPL-1.0"),
    "LPPL-1.3c (l3build)": (
        {"LICENSE": "The LaTeX Project Public License\n\nLPPL Version 1.3c  2008-05-04\n"},
        "LPPL-1.3c",
    ),
    "Artistic-2.0 (mojo)": (
        {"LICENSE": "The Artistic License 2.0\n\nCopyright (c) 2000-2006, The Perl Foundation.\n"},
        "Artistic-2.0",
    ),
    "the terms of Perl itself (Perl-Critic)": ({"LICENSE": PERL_TERMS}, "Artistic-1.0-Perl"),
    "ODbL-1.0 (countries)": ({"LICENSE": "## ODC Open Database License (ODbL)\n\n### Preamble\n"}, "ODbL-1.0"),
    "CC-BY-4.0 (fivethirtyeight)": ({"LICENSE": CC_BY}, "CC-BY-4.0"),
    "CC-BY-NC-4.0 by name (cppbestpractices)": ({"LICENSE": CC_BY_NC_NOTICE}, "CC-BY-NC-4.0"),
    "PostgreSQL (pgvector)": ({"LICENSE": POSTGRESQL}, "PostgreSQL"),
    "MIT in a Markdown blockquote (DataFrames.jl)": ({"LICENSE.md": QUOTED_MIT}, "MIT"),
    "CRAN's MIT + file LICENSE stub (dplyr)": (
        {
            **R_PACKAGE,
            "LICENSE": "YEAR: 2026\nCOPYRIGHT HOLDER: foo authors\n",
            "LICENSE.md": "# MIT License\n\n" + MIT,
        },
        "MIT",
    ),
    "-or-later kept from the manifests (pandoc)": (
        {
            "COPYING": GPL_2,
            "x.cabal": "cabal-version: 2.4\nname: x\nversion: 1\nlicense: GPL-2.0-or-later\n",
            "src/A.hs": "",
        },
        "GPL-2.0-or-later",
    ),
    "LICENSE-CODE beside an unrecognised LICENSE-TEXT (PythonDataScienceHandbook)": (
        {"LICENSE-CODE": MIT, "LICENSE-TEXT": "Attribution-NonCommercial-NoDerivs 3.0 Unported\n"},
        "MIT",
    ),
    "a Data Package's licenses (datasets/gdp)": (
        {
            "datapackage.json": '{"name": "gdp", "licenses": [{"name": "ODC-PDDL-1.0"}], "resources": []}\n',
            "data/gdp.csv": "a\n1\n",
        },
        "ODC-PDDL-1.0",
    ),
    "dual-licensed pointer beside the texts (ripgrep)": (
        {
            "COPYING": "This project is dual-licensed under the Unlicense and MIT licenses.\n",
            "LICENSE-MIT": MIT,
            "UNLICENSE": "This is free and unencumbered software released into the public domain.\n",
            "Cargo.toml": "[package]\nname = 'rg'\nversion = '1.0.0'\nlicense = 'Unlicense OR MIT'\n",
            "src/main.rs": "",
        },
        "MIT",
    ),
}

# Manifests that are not the project's, and a combined license file (upstream #239).
MIT_PYPROJECT = "[project]\nname = 'p'\nlicense = 'MIT'\n"
NOT_THE_PROJECTS_MANIFEST: dict[str, dict[str, str]] = {
    "a fixture pyproject.toml (poetry)": {
        "pyproject.toml": MIT_PYPROJECT,
        "LICENSE": MIT,
        "src/p.py": "",
        "tests/fixtures/bad/pyproject.toml": "[project]\nname = 'bad'\nlicense = 'INVALID'\n",
    },
    "a linter fixture pyproject.toml (ruff)": {
        "Cargo.toml": "[package]\nname = 'r'\nversion = '0.1.0'\nlicense = 'MIT'\n",
        "LICENSE": MIT,
        "src/lib.rs": "",
        "tests/fixtures/pyproject.toml": "[project]\nname = 'f'\nlicense = 'GPL-2.0'\n",
    },
    "a combined license file whose first licence is the package's (vite)": {
        "package.json": '{"name": "create-vite", "license": "MIT"}\n',
        "index.js": "",
        "LICENSE": "# create-vite license\n\ncreate-vite is released under the MIT license:\n\n" + MIT + "\n" + CC0,
    },
}

# README text -> the status and the message fragment status-badges should report (upstream #240).
BADGEN_REFERENCES = (
    "[![Build Status][ci-image]][ci-url]\n[![Coverage Status][cov-image]][cov-url]\n\n"
    "[ci-image]: https://badgen.net/github/checks/o/r/main?label=ci\n[ci-url]: https://github.com/o/r/actions\n"
    "[cov-image]: https://badgen.net/coveralls/c/github/o/r/main\n[cov-url]: https://coveralls.io/r/o/r\n"
)
DATAHUB_BADGE = (
    '<a href="https://datahub.io/core/gdp"><img src="https://badgen.net/badge/icon/View%20on%20datahub.io/orange'
    '?icon=https://datahub.io/x.svg&label&scale=1.25" alt="badge" /></a>\n'
)
BADGE_CASES: dict[str, tuple[str, Status, str]] = {
    "reference-style badgen links (mime-db)": (BADGEN_REFERENCES, Status.PASS, "Coveralls"),
    "a datahub badgen image is not Jenkins (datasets/gdp)": (DATAHUB_BADGE, Status.FAIL, "shows no status badges"),
    "Codecov's coverage.svg (data.table)": (
        CI_BADGE
        + "[![cov](https://codecov.io/github/o/r/coverage.svg?branch=master)](https://codecov.io/github/o/r)\n",
        Status.PASS,
        "Codecov",
    ),
    "a badge inside an HTML comment (got)": (
        CI_BADGE
        + "<!-- [![cov](https://codecov.io/gh/o/r/branch/main/graph/badge.svg)](https://codecov.io/gh/o/r) -->\n",
        Status.WARN,
        "but no quality badge",
    ),
    "a stale travis-ci.org badge beside GitHub Actions (typed-racket)": (
        "[![Build Status](https://travis-ci.org/o/r.svg?branch=master)](https://travis-ci.org/o/r)\n",
        Status.FAIL,
        "",
    ),
    "the legacy visualstudio.com host (Open-XML-SDK)": (
        "[![Build](https://office.visualstudio.com/OC/_apis/build/status/Def?branchName=main)](https://x)\n",
        Status.WARN,
        "Azure Pipelines",
    ),
}

# Files -> (the language the map claims, or None; the suffixes it must then not call unrecognised) (upstream #241).
CMAKE_WITH = "cmake_minimum_required(VERSION 3.21)\nproject(x LANGUAGES {})\n"
SUFFIX_CASES: dict[str, tuple[dict[str, str], str | None, tuple[str, ...]]] = {
    "CUDA (llama.cpp)": ({"CMakeLists.txt": CMAKE_WITH.format("CXX CUDA"), "a.cpp": "", "k.cu": ""}, "CUDA", (".cu",)),
    "Objective-C (glfw)": (
        {"CMakeLists.txt": CMAKE_WITH.format("C OBJC"), "a.c": "", "m.m": ""},
        "Objective-C",
        (".m",),
    ),
    "cabal.project.freeze (PostgREST)": (
        {"x.cabal": "name: x\nversion: 1\n", "src/A.hs": "", "cabal.project.freeze": "constraints: any.base ==4.18\n"},
        None,
        (".freeze",),
    ),
    "Package.resolved and test plans (Alamofire)": (
        {
            "Package.swift": "// swift-tools-version:5.9\n",
            "Sources/X/a.swift": "",
            "Package.resolved": "{}\n",
            "Tests/Plans/iOS.xctestplan": "{}\n",
        },
        None,
        (".resolved", ".xctestplan"),
    ),
    "META-INF/services (flyway)": (
        {"pom.xml": "<project/>\n", "src/main/java/A.java": "", "src/main/resources/META-INF/services/com.x.Spi": ""},
        None,
        (".Spi",),
    ),
    "R data and build files (data.table)": (
        {"DESCRIPTION": "Package: shop\nVersion: 0.1\n", "R/shop.R": "", "data/x.rda": "", "src/Makevars.win": ""},
        None,
        (".rda", ".win"),
    ),
    "EEx templates and cheatsheets (ecto)": (
        {"mix.exs": "", "lib/x.ex": "", "lib/x.html.heex": "", "guides/x.cheatmd": ""},
        None,
        (".heex", ".cheatmd"),
    ),
    "Terraform templates (terraform-google)": ({"main.tf": "", "templates/x.tftpl": ""}, None, (".tftpl",)),
    "zsh themes (ohmyzsh)": ({"x.sh": "#!/bin/sh\n", "themes/a.zsh-theme": ""}, None, (".zsh-theme",)),
    "an asciidoc README (cowboy)": ({"x.sh": "#!/bin/sh\n", "README.asciidoc": "= X\n"}, None, (".asciidoc",)),
}

# Security policies in other shapes (upstream #242).
SECURITY_CONTACTS = (
    "# Defined below are the security contacts for this repo.\n#\n"
    "# DO NOT REPORT SECURITY VULNERABILITIES DIRECTLY TO THESE NAMES, FOLLOW THE\n"
    "# INSTRUCTIONS AT https://kubernetes.io/security/\n\nfloryut\n"
)
OBFUSCATED_POLICY = (
    "# Security Policy\n\n## Reporting a Vulnerability\n\nIf you find one you send email to martin <dot> horenovsky"
    " <at> gmail <dot> com. If you want to encrypt the email, my pgp key is\n`E29C 46F3 B8A7 5028 6079 3B7D ECC9 C20E"
    " 314B 2360`\n"
)

# Renovate's other documented configuration paths (upstream #245).
RENOVATE_PATHS = (".github/renovate.json5", ".renovaterc.json5", ".gitlab/renovate.json", ".gitlab/renovate.json5")

# dependency-management misreads (upstream #246): files -> the fragment the message must not contain.
R_WITH_IMPORTS = {"DESCRIPTION": "Package: shop\nVersion: 0.1\nImports: cli, glue\n", "R/shop.R": "", "src/a.c": ""}
JULIA_WITH_DEPS = {"Project.toml": 'name = "D"\n\n[deps]\nJSON = "682c06a0"\n', "src/D.jl": "", "assets/x.js": ""}
MISREAD_DEPENDENCIES: dict[str, tuple[dict[str, str], str]] = {
    "an empty .gitmodules (kubespray)": ({**GO_MODULE, ".gitmodules": ""}, "third-party"),
    "license notices only in third_party/ (golangci-lint)": (
        {**GO_MODULE, "third_party/foo/LICENSE": MIT},
        "third-party",
    ),
    "a Composer package without a type is a library (guzzle)": (
        {"composer.json": '{"name": "g/g", "require": {"psr/log": "^3"}}\n', "src/A.php": "<?php\n"},
        "not locked",
    ),
    "a Julia Project.toml with [deps] (Documenter)": (JULIA_WITH_DEPS, "no dependencies are declared"),
    "an R DESCRIPTION with Imports (dplyr)": (R_WITH_IMPORTS, "no dependencies are declared"),
}


def _run(selected: Check, files: Mapping[str, str]) -> Result:
    with temp_project(files) as root:
        return selected.run(make_context(root))


def _run_tracked(selected: Check, files: Mapping[str, str]) -> Result:
    """`selected` in a git checkout tracking `files` (a plain directory walk prunes node_modules/; git lists it)."""
    with temp_project(files) as root:
        git(root, "init", "-q")
        git(root, "add", "-f", ".")
        return selected.run(make_context(root))


def _structure(files: Mapping[str, str]) -> ProjectStructure:
    with temp_project(files) as root:
        return make_context(root).structure


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class CommittedArtifactsTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #235: committed-artifacts flags directories and files by name, not by content
    def test_sources_fixtures_and_settings_are_judged_by_what_they_are(self) -> None:
        """A build/ of Dart sources, a bin/ of scripts, a coverage/ Julia environment, a .bundle/config, fixtures
        under tests/, a text .exe and the mdBook source directory are not build outputs (drift, fzf, Documenter, puma,
        poetry, vite, dune, polylux, ...)."""
        for name, files in NOT_BUILD_OUTPUTS.items():
            with self.subTest(name):
                result = _run_tracked(committed_artifacts, files)
                self.assertEqual(result.status, Status.PASS, result)


class VcsIgnoreTests(unittest.TestCase):
    def assert_ignored_like(self, variant: Mapping[str, str], control: Mapping[str, str]) -> None:
        """`variant` ignores the outputs as `control`, whose ignore entries are the literal ones the check knows."""
        expected = _run(vcs_ignore, control)
        self.assertEqual(expected.status, Status.PASS, expected)
        result = _run(vcs_ignore, variant)
        self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #236: ignore entries are compared textually, not with gitignore semantics
    def test_ignore_entries_are_matched_with_gitignore_semantics(self) -> None:
        """An anchored path (/lisp/*.elc), a glob covering the output (site*/, *.pyc*, blib*, *.gz), a unit's own
        target path and a whitelist (/* then !tracked) ignore the output as the literal entry does (magit, mkdocs,
        scikit-learn, tidyall, l3build, deno std, pandoc)."""
        for name, (base, spelled, literal) in IGNORE_SPELLINGS.items():
            with self.subTest(name):
                self.assert_ignored_like({**base, ".gitignore": spelled}, {**base, ".gitignore": literal})

    @unittest.expectedFailure  # upstream #237: only the root ignore file is judged, not the unit's own or its path
    def test_a_units_outputs_are_judged_against_the_ignore_files_that_apply_to_it(self) -> None:
        """The ignore file of the unit that writes the output (docs/.gitignore, web/.gitignore) and a root entry
        anchored to the unit (docs/_build/) ignore it as a root entry does (PostgREST, rich, golangci-lint, koyo,
        laravel, guava)."""
        for name, (variant, control) in PER_UNIT_IGNORES.items():
            with self.subTest(name):
                self.assert_ignored_like(variant, control)


class LicenseTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #238: EPL-1.0, LPPL, Artistic, ODbL, CC-BY, PostgreSQL and more unrecognised
    def test_recognises_the_licenses_of_the_corpus(self) -> None:
        """EPL-1.0, LPPL-1.3c, Artistic-2.0, the terms of Perl, ODbL, CC-BY, PostgreSQL, MIT in a blockquote, CRAN's
        stub, -or-later, a LICENSE-CODE/LICENSE-TEXT pair, a Data Package's licenses and a dual-licence pointer are
        recognised and named (clj-kondo, l3build, mojo, Perl-Critic, DataFrames.jl, dplyr, pandoc, datasets,
        ripgrep)."""
        for name, (files, identifier) in LICENSE_CASES.items():
            with self.subTest(name):
                result = _run(license_, files)
                self.assertNotEqual(result.status, Status.FAIL, result)
                self.assertIn(identifier, result.message, result)

    @unittest.expectedFailure  # upstream #238: License.pm and license.t full-match the license file name pattern
    def test_perl_modules_and_tests_are_not_license_files(self) -> None:
        """Dist-Zilla's lib/Dist/Zilla/Plugin/License.pm and t/plugins/license.t match the license file name pattern
        and are recorded as (unrecognised) license files."""
        with temp_project(
            {"dist.ini": "name = Foo\nlicense = Perl_5\n", "lib/License.pm": "", "t/license.t": ""}
        ) as root:
            paths = [fact.origin.path for fact in make_context(root).facts.of(LicenseFile)]
        self.assertEqual(paths, [])

    @unittest.expectedFailure  # upstream #239: fixture manifests are compared; a combined file's longest licence wins
    def test_only_the_projects_own_manifests_are_compared_with_its_license_files(self) -> None:
        """A test fixture's pyproject.toml declaring INVALID or GPL-2.0 is not the project's manifest, and a combined
        LICENSE whose first licence is MIT (CC0 for the bundled templates) agrees with a package.json declaring MIT
        (poetry, ruff, vite)."""
        for name, files in NOT_THE_PROJECTS_MANIFEST.items():
            with self.subTest(name):
                result = _run(license_, files)
                self.assertEqual(result.status, Status.PASS, result)
                self.assertIn("MIT", result.message, result)


class StatusBadgesTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #240: badges matched by URL fragments of every provider, not what they show
    def test_badges_are_read_by_what_they_show(self) -> None:
        """Reference-style links and badgen images are followed, a datahub badge is not Jenkins, Codecov's
        coverage.svg counts, a badge in an HTML comment does not, a travis-ci.org badge is not the status of a GitHub
        Actions project, and office.visualstudio.com is Azure Pipelines (mime-db, datasets, data.table, got,
        typed-racket, Open-XML-SDK)."""
        for name, (readme, status, fragment) in BADGE_CASES.items():
            with self.subTest(name):
                result = _run(status_badges, {"README.md": readme, **github_job("ubuntu-latest", "make")})
                self.assertEqual(result.status, status, result)
                self.assertIn(fragment, result.message, result)


class ProjectMapTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #241: the map lists suffixes of claimed languages and read files as unknown
    def test_files_the_profiles_know_are_not_unrecognised_suffixes(self) -> None:
        """A language the map names has no unrecognised suffix of its own (CUDA/.cu, Objective-C/.m), and the files
        a profile reads or owns (cabal.project.freeze, Package.resolved, META-INF/services, .rda, .heex, .tftpl,
        .zsh-theme, .asciidoc) are not unknown (llama.cpp, glfw, PostgREST, Alamofire, flyway, data.table, ecto)."""
        for name, (files, language, suffixes) in SUFFIX_CASES.items():
            with self.subTest(name):
                structure = _structure(files)
                if language is not None and language not in structure.languages:
                    continue  # The other correct answer: the language is not claimed.
                unrecognised = dict(structure.unrecognised_suffixes)
                for suffix in suffixes:
                    self.assertNotIn(suffix, unrecognised, structure.unrecognised_suffixes)


class SecurityPolicyTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #242: SECURITY_CONTACTS and an obfuscated address are not a way to report
    def test_other_conventions_say_how_to_report(self) -> None:
        """The Kubernetes organisation's SECURITY_CONTACTS file (whose header points at kubernetes.io/security) and a
        "Reporting a Vulnerability" section with an obfuscated address and a PGP fingerprint are security policies
        that say how to report (kubespray, Catch2)."""
        for name, files in {
            "SECURITY_CONTACTS": {"SECURITY_CONTACTS": SECURITY_CONTACTS},
            "an obfuscated address": {"SECURITY.md": OBFUSCATED_POLICY},
        }.items():
            with self.subTest(name):
                result = _run(security_policy, files)
                self.assertEqual(result.status, Status.PASS, result)


class DependencyUpdatesTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #245: .github/renovate.json5 and the other Renovate locations are unknown
    def test_renovate_is_found_at_every_documented_location(self) -> None:
        """.github/renovate.json5 (prettier, vite, okhttp, junit5, opentelemetry-proto, clap, starship, ruff),
        .renovaterc.json5 and .gitlab/renovate.json[5] are Renovate configurations."""
        for path in RENOVATE_PATHS:
            with self.subTest(path):
                result = _run(dependency_updates, {path: "{}\n", "src/a.py": ""})
                expected = Result.passed("automated dependency updates are configured with Renovate", path)
                self.assertEqual(result, expected)


class DependencyManagementTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #246: .gitmodules by presence, Composer's default type, R/Julia deps unread
    def test_reads_what_the_files_say(self) -> None:
        """An empty .gitmodules has no submodules, a third_party/ of license notices is not code, a Composer package
        without a type is a library, and an R DESCRIPTION or Julia Project.toml with dependencies is not "no
        dependencies are declared" (kubespray, golangci-lint, guzzle, dplyr, Documenter)."""
        for name, (files, wrong) in MISREAD_DEPENDENCIES.items():
            with self.subTest(name):
                result = _run(dependency_management, files)
                self.assertNotIn(wrong, result.message, result)
