"""The project corpus (`corpus/`) is complete and consistent: every project is pinned to a commit, every ecosystem
profile has a project that stands for it, and the issues named are issue numbers. What the validator says about the
projects is compared between branches by `python -m corpus` (see corpus/README.md), which fetches the checkouts;
these tests read only the manifest and exercise the recording tools on a recording made by hand."""

from __future__ import annotations

import io
import json
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from corpus import CorpusProject, projects, shortfalls, unexplained
from corpus.__main__ import main
from project_validator.ecosystems import BUILT_IN
from tests.support import temp_project

COMMIT = re.compile(r"^[0-9a-f]{40}$")
MANIFEST = Path(__file__).parent.parent / "corpus" / "projects.toml"
NO_ISSUES = CorpusProject(name="o/r", commit="0" * 40, ecosystems=("Rust",))
RECORDED: dict[str, object] = {
    "commit": "0" * 40,
    "map": {"ecosystems": {"Rust": [".rs files"]}},
    "results": [],
    "strict": {},
}


class CorpusManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.projects = projects()

    def test_every_project_is_pinned_and_its_issues_are_sorted_numbers(self) -> None:
        self.assertTrue(self.projects)
        for project in self.projects:
            with self.subTest(project=project.name):
                self.assertRegex(project.commit, COMMIT)
                self.assertRegex(project.name, r"^[\w.-]+/[\w.-]+$")
                self.assertEqual(sorted(set(project.issues)), list(project.issues))
                self.assertTrue(all(number > 0 for number in project.issues))

    def test_names_are_unique(self) -> None:
        names = [project.name for project in self.projects]
        self.assertEqual(sorted(set(names)), sorted(names))

    def test_every_ecosystem_has_a_project_that_stands_for_it(self) -> None:
        labels = {ecosystem.label for ecosystem in BUILT_IN}
        for project in self.projects:
            self.assertLessEqual(set(project.ecosystems), labels, project.name)
        for label in sorted(labels):
            with self.subTest(ecosystem=label):
                self.assertTrue(any(label in project.ecosystems for project in self.projects), label)

    def test_the_manifest_is_what_the_runner_reads(self) -> None:
        self.assertEqual(projects(MANIFEST), self.projects)


class RecordingTests(unittest.TestCase):
    def test_shortfalls_are_a_crash_or_an_ecosystem_not_detected(self) -> None:
        self.assertEqual(shortfalls(NO_ISSUES, RECORDED), [])
        undetected: dict[str, object] = {**RECORDED, "map": {"ecosystems": {}}}
        self.assertEqual(shortfalls(NO_ISSUES, undetected), ["Rust is not detected"])
        crashed: dict[str, object] = {"commit": "0" * 40, "extraction_error": "boom", "results": [], "strict": {}}
        self.assertEqual(shortfalls(NO_ISSUES, crashed), ["the extraction failed: boom"])

    def test_a_shortfall_is_fatal_only_without_an_issue_to_account_for_it(self) -> None:
        problems = ["Rust is not detected"]
        self.assertEqual(unexplained(NO_ISSUES, problems), problems)
        known = CorpusProject(name="o/r", commit="0" * 40, ecosystems=("Rust",), issues=(180,))
        self.assertEqual(unexplained(known, problems), [])

    def test_diff_says_which_checks_changed_status(self) -> None:
        before = {
            **RECORDED,
            "results": [{"check": "license", "status": "PASS"}, {"check": "ci-lint", "status": "WARN"}],
        }
        after = {
            **RECORDED,
            "results": [{"check": "license", "status": "FAIL"}, {"check": "ci-lint", "status": "WARN"}],
        }
        files = {
            "base/o--r.json": json.dumps(before),
            "head/o--r.json": json.dumps(after),
            "base/o--same.json": json.dumps(RECORDED),
            "head/o--same.json": json.dumps(RECORDED),
            "head/o--new.json": json.dumps({**RECORDED, "extraction_error": "boom"}),
        }
        printed = io.StringIO()
        with temp_project(files) as root, redirect_stdout(printed):
            self.assertEqual(main(["diff", str(root / "base"), str(root / "head")]), 0)
        self.assertIn("o/r: license: PASS → FAIL", printed.getvalue())
        self.assertIn("o/new: extraction: crashes now", printed.getvalue())
        self.assertIn("2 of 3 projects differ", printed.getvalue())
        self.assertNotIn("o/same", printed.getvalue())
