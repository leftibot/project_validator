"""The README documents every check, and each built-in ecosystem's page every check that applies to it."""

import os
import re
import unittest
from pathlib import Path

from project_validator.ecosystems import PROFILES, applies_to, isolated_registry, registered
from project_validator.plugins import discover
from project_validator.support_matrix import REGENERATE, render, support_matrix
from tests.support import temp_project

ROOT = Path(__file__).parent.parent
README = ROOT / "README.md"
ECOSYSTEM_PAGES = ROOT / "docs" / "ecosystems"
CHECK_ROW = re.compile(r"^\| `(?P<check>[a-z0-9-]+)` \|", re.MULTILINE)
CHECK_HEADING = re.compile(r"^## `(?P<check>[a-z0-9-]+)`$", re.MULTILINE)


def _checks_section() -> str:
    text = README.read_text(encoding="utf-8")
    start = text.index("\n## Checks\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end >= 0 else None]


class ReadmeTests(unittest.TestCase):
    def test_every_check_is_documented_once(self) -> None:
        rows = [row["check"] for row in CHECK_ROW.finditer(_checks_section())]
        self.assertEqual(sorted(rows), sorted(found.name for found in discover().checks))


class EcosystemPageTests(unittest.TestCase):
    def test_every_built_in_ecosystem_has_a_page_named_after_its_profile(self) -> None:
        pages = {page.stem for page in ECOSYSTEM_PAGES.glob("*.md")}
        self.assertEqual(pages, set(PROFILES))

    def test_a_page_documents_each_check_that_applies_to_its_ecosystem(self) -> None:
        checks = discover().checks
        for name, ecosystem in PROFILES.items():
            with self.subTest(ecosystem=ecosystem.label):
                text = (ECOSYSTEM_PAGES / f"{name}.md").read_text(encoding="utf-8")
                headings = [heading["check"] for heading in CHECK_HEADING.finditer(text)]
                self.assertEqual(len(headings), len(set(headings)))
                applying = {found.name for found in checks if ecosystem.label in applies_to(found)}
                self.assertLessEqual(applying, set(headings))
                # Checks of every project may say what the ecosystem adds to them (its license field, its lints).
                self.assertLessEqual(set(headings), {found.name for found in checks})
                self.assertTrue(text.startswith(f"# {ecosystem.label}\n"))


class ReadmeExampleTests(unittest.TestCase):
    def test_the_ecosystem_plugin_example_works(self) -> None:
        text = README.read_text(encoding="utf-8")
        section = text[text.index("### Adding an ecosystem") :]
        start = section.index("```python\n") + len("```python\n")
        example = section[start : section.index("\n```", start)]
        with isolated_registry(), temp_project({"zig.py": example}) as directory:
            plugins = discover([directory])
            self.assertEqual(registered()[-1].label, "Zig")
            formatting = next(found for found in plugins.checks if found.name == "code-formatting")
            self.assertIn("Zig", applies_to(formatting))


class SupportMatrixTests(unittest.TestCase):
    def test_the_committed_matrix_is_current(self) -> None:
        expected = render(support_matrix(discover().checks))
        page = ROOT / "docs" / "support-matrix.md"
        if os.environ.get("UPDATE_SNAPSHOTS") == "1":
            page.write_text(expected, encoding="utf-8", newline="\n")
        actual = page.read_text(encoding="utf-8")
        self.assertEqual(actual, expected, f"docs/support-matrix.md is stale: run `{REGENERATE}`")

    def test_the_readme_links_the_matrix(self) -> None:
        self.assertIn("(docs/support-matrix.md)", README.read_text(encoding="utf-8"))
