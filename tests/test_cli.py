import contextlib
import io
import json
import tomllib
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from project_validator import pretty, yaml_support
from project_validator.cli import EXIT_FAILURE, EXIT_SUCCESS, EXIT_USAGE, main
from project_validator.ecosystems import C_FAMILY, applies_to
from project_validator.plugins import discover
from project_validator.support_matrix import render, support_matrix
from tests.layouts.model import ProjectLayout
from tests.support import (
    BARE_PROJECT,
    C_FAMILY_LAYOUTS,
    C_FAMILY_ONLY_LAYOUTS,
    CI_FILES,
    FIXTURES,
    OTHER_LANGUAGE_LAYOUTS,
    PROJECT_LAYOUTS,
    WELL_CONFIGURED,
    WELL_CONFIGURED_PYTHON,
    layout_project,
    requires_rich,
    temp_project,
    well_configured,
)

LANGUAGE_SPECIFIC_CHECKS = tuple(found for found in discover().checks if found.languages)
COMPILER_CHECKS = ",".join(found.name for found in LANGUAGE_SPECIFIC_CHECKS)
# Language -> the language-specific checks that do not apply to it.
NOT_APPLICABLE = {
    language: {found.name for found in LANGUAGE_SPECIFIC_CHECKS if language not in found.languages}
    for layout in OTHER_LANGUAGE_LAYOUTS
    for language in layout.languages
}


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def run_cli(*arguments: str, terminal: bool = False) -> tuple[int, str, str]:
    stdout, stderr = Terminal() if terminal else io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(list(arguments))
    return code, stdout.getvalue(), stderr.getvalue()


class CliTests(unittest.TestCase):
    def test_list(self) -> None:
        code, output, _ = run_cli("--list")
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertIn("platform-matrix", output)

    def test_well_configured_project_passes(self) -> None:
        for layout in C_FAMILY_ONLY_LAYOUTS:
            with layout_project(self, layout, WELL_CONFIGURED) as root:
                code, output, _ = run_cli(str(root))
                self.assertEqual(code, EXIT_SUCCESS, output)
                self.assertIn("[PASS] coverage:", output)

    def test_well_configured_projects_in_other_languages_pass_strictly(self) -> None:
        for layout in OTHER_LANGUAGE_LAYOUTS:
            with layout_project(self, layout, well_configured(layout)) as root:
                code, output, _ = run_cli("--strict", str(root))
                self.assertEqual(code, EXIT_SUCCESS, output)
                # The profile's well-configured project may add languages of its own to the layout's (C# to F#).
                languages = set(json.loads(run_cli("--map", str(root))[1])["languages"])
                for found in LANGUAGE_SPECIFIC_CHECKS:
                    status = "PASS" if found.languages & languages else "SKIP"
                    self.assertIn(f"[{status}] {found.name}:", output)

    def test_mixed_language_project_passes_when_every_language_is_well_configured(self) -> None:
        python = {
            "pyproject.toml": "[tool.coverage.run]\nbranch = true\n",
            "tests/test_bindings.py": "",
            ".github/workflows/python.yml": WELL_CONFIGURED_PYTHON[".github/workflows/ci.yml"],
        }
        mixed = [layout for layout in C_FAMILY_LAYOUTS if layout not in C_FAMILY_ONLY_LAYOUTS]
        # ci-build-types is left out: a Python-only job on a runner counts as a C/C++ build with its default compiler.
        judged_per_language = "compiler-warnings,coverage,tests-run,hardening,platform-matrix"
        for layout in mixed:
            with layout_project(self, layout, {**WELL_CONFIGURED, **python}) as root:
                code, output, _ = run_cli("--only", judged_per_language, str(root))
                self.assertEqual(code, EXIT_SUCCESS, output)
                self.assertIn("[PASS] coverage: C/C++: branch coverage is reported with gcovr", output)

    def test_bare_project_fails(self) -> None:
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout, BARE_PROJECT) as root:
                code, output, _ = run_cli(str(root))
                self.assertEqual(code, EXIT_FAILURE)
                self.assertIn("[FAIL] ci-present:", output)

    def test_json_output_with_only(self) -> None:
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout, BARE_PROJECT) as root:
                code, output, _ = run_cli("--format", "json", "--only", "ci-present,coverage", str(root))
                self.assertEqual(code, EXIT_FAILURE)
                self.assertEqual([entry["check"] for entry in json.loads(output)], ["ci-present", "coverage"])

    def test_an_unknown_answer_is_an_error_unless_allowed(self) -> None:
        # Jenkinsfiles are scanned heuristically, so what their jobs run is not known for certain.
        files = {"main.c": "int main(void) { return 0; }\n", "Jenkinsfile": "sh 'gcovr'\n"}
        with temp_project(files) as root:
            code, output, _ = run_cli("--only", "coverage", str(root))
            self.assertEqual(code, EXIT_FAILURE)
            self.assertIn("[ERROR] coverage: whether CI reports branch coverage is unknown", output)
            code, output, _ = run_cli("--only", "coverage", "--allow-unknown", str(root))
            self.assertEqual(code, EXIT_FAILURE)
            self.assertIn("[FAIL] coverage: no branch coverage reporting found in what CI runs", output)

    def test_skipping_every_failure_succeeds(self) -> None:
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout, BARE_PROJECT) as root:
                self.assertEqual(
                    run_cli("--skip", f"ci-present,license,status-badges,{COMPILER_CHECKS}", str(root))[0], EXIT_SUCCESS
                )

    def test_map_prints_the_project_structure(self) -> None:
        code, output, _ = run_cli("--map", str(FIXTURES / "well_configured_c_cpp"))
        self.assertEqual(code, EXIT_SUCCESS)
        mapped = json.loads(output)
        self.assertEqual(mapped["languages"], ["C++"])
        self.assertIn("GitHub Actions", mapped["ci"]["providers"])

    def assert_map_matches_layout(self, layout: ProjectLayout, *arguments: str) -> dict[str, Any]:
        code, output, _ = run_cli("--map", *arguments)
        self.assertEqual(code, EXIT_SUCCESS)
        mapped: dict[str, Any] = json.loads(output)
        self.assertEqual(mapped["languages"], sorted(layout.languages))
        self.assertEqual(mapped["build_systems"], sorted(layout.build_systems))
        return mapped

    def test_map_prints_every_layout_with_every_ci_provider(self) -> None:
        for layout in PROJECT_LAYOUTS:
            for provider, path in CI_FILES.items():
                with layout_project(self, layout, {path: "jobs: {}\n"}, ci=provider) as root:
                    mapped = self.assert_map_matches_layout(layout, str(root))
                    self.assertEqual(mapped["ci"]["providers"], [provider])

    def test_compiler_checks_are_skipped_only_where_they_do_not_apply(self) -> None:
        for layout in OTHER_LANGUAGE_LAYOUTS:
            [language] = layout.languages
            for provider, path in CI_FILES.items():
                with layout_project(self, layout, {path: "jobs: {}\n"}, ci=provider) as root:
                    code, output, _ = run_cli("--only", COMPILER_CHECKS, str(root))
                    expected = NOT_APPLICABLE[language] | layout.skipped
                    # A language none of the checks applies to yet (a new profile) has nothing to fail.
                    applying = set(COMPILER_CHECKS.split(",")) - expected
                    self.assertEqual(code, EXIT_FAILURE if applying else EXIT_SUCCESS, output)
                    for name in COMPILER_CHECKS.split(","):
                        skipped = f"[SKIP] {name}:" in output
                        self.assertEqual(skipped, name in expected, name)

    def test_compiler_checks_run_for_c_family_languages(self) -> None:
        for layout in C_FAMILY_LAYOUTS:
            with layout_project(self, layout, {".github/workflows/ci.yml": "jobs: {}\n"}) as root:
                code, output, _ = run_cli("--only", COMPILER_CHECKS, str(root))
                self.assertEqual(code, EXIT_FAILURE, output)
                for found in LANGUAGE_SPECIFIC_CHECKS:
                    skipped = f"[SKIP] {found.name}:" in output
                    self.assertEqual(skipped, not found.languages & layout.languages, found.name)

    def test_excluded_directories_are_left_out_of_the_map(self) -> None:
        excluded = {"tests/fixtures/cmake/CMakeLists.txt": "", "tests/fixtures/cmake/main.cpp": ""}
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout, excluded) as root:
                self.assert_map_matches_layout(layout, "--exclude", "./tests/fixtures/", str(root))

    def test_usage_errors(self) -> None:
        self.assertEqual(run_cli("--only", "nope", ".")[0], EXIT_USAGE)
        self.assertEqual(run_cli(str(FIXTURES / "missing"))[0], EXIT_USAGE)
        for size in ("0", "-1", "big", "nan"):
            with self.subTest(size=size), self.assertRaises(SystemExit) as raised:
                run_cli("--max-file-size", size, ".")
            self.assertEqual(raised.exception.code, EXIT_USAGE)

    def test_max_file_size_sets_the_large_file_limit(self) -> None:
        code, output, _ = run_cli("--only", "large-files", "--max-file-size", "0.5", str(FIXTURES / "bare_c_cpp"))
        self.assertEqual(
            (code, output.strip()), (EXIT_SUCCESS, "[PASS] large-files: no committed file is larger than 512 KiB")
        )

    @requires_rich
    def test_color_always_beautifies_the_output(self) -> None:
        code, output, _ = run_cli("--color", "always", str(FIXTURES / "well_configured_c_cpp"))
        self.assertEqual(code, EXIT_SUCCESS, output)
        self.assertIn("\x1b[", output)
        applicable = [found for found in discover().checks if not found.languages or found.languages & C_FAMILY]
        self.assertIn(f"{len(applicable)} passed", output)

    def test_color_never_and_auto_when_redirected_keep_plain_text(self) -> None:
        for choice in ("never", "auto"):
            _, output, _ = run_cli("--color", choice, str(FIXTURES / "well_configured_c_cpp"))
            self.assertNotIn("\x1b[", output)
            self.assertIn("[PASS] coverage:", output)

    def test_color_auto_is_used_for_a_terminal_unless_no_color_is_set(self) -> None:
        with mock.patch.object(pretty, "available", return_value=False):
            with mock.patch.dict("os.environ", {}, clear=True):
                self.assertIn("install rich", run_cli(str(FIXTURES / "well_configured_c_cpp"), terminal=True)[2])
            with mock.patch.dict("os.environ", {"NO_COLOR": "1"}):
                self.assertEqual(run_cli(str(FIXTURES / "well_configured_c_cpp"), terminal=True)[2], "")

    def test_color_without_rich_falls_back_to_plain_text_and_says_so(self) -> None:
        with mock.patch.object(pretty, "_rich", None):
            code, output, errors = run_cli("--color", "always", str(FIXTURES / "well_configured_c_cpp"))
        self.assertEqual(code, EXIT_SUCCESS, output)
        self.assertIn("[PASS] coverage:", output)
        self.assertIn("install rich", errors)

    def test_missing_pyyaml_is_an_error_instead_of_reduced_accuracy(self) -> None:
        with mock.patch.object(yaml_support, "_yaml", None):
            code, output, error = run_cli(str(FIXTURES / "well_configured_c_cpp"))
        self.assertEqual((code, output), (EXIT_USAGE, ""))
        self.assertIn("PyYAML", error)

    def test_pyyaml_can_not_be_disabled(self) -> None:
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            main(["--no-yaml", str(FIXTURES / "well_configured_c_cpp")])


class DependencyTests(unittest.TestCase):
    def test_pyyaml_is_a_required_dependency(self) -> None:
        pyproject = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("PyYAML>=6.0", pyproject["project"]["dependencies"])
        self.assertNotIn("yaml", pyproject["project"]["optional-dependencies"])


class ListTests(unittest.TestCase):
    def test_facts_are_printed_as_json(self) -> None:
        code, output, _ = run_cli("--facts", str(FIXTURES / "well_configured_c_cpp"))
        self.assertEqual(code, EXIT_SUCCESS)
        facts = json.loads(output)
        self.assertIn("CiJob", {fact["kind"] for fact in facts})
        self.assertTrue(all("origin" in fact for fact in facts))

    def test_markdown_format_is_the_grid(self) -> None:
        code, output, _ = run_cli("--format", "markdown", str(FIXTURES / "well_configured_python"))
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertTrue(output.startswith("# project_validator results\n\n✅ pass"))
        self.assertIn("| `coverage` | ✅ coverage.py |", output)
        self.assertIn("| `code-formatting` | ✅ ruff format |", output)
        self.assertIn("| `fuzz-testing` | ✅ atheris |", output)
        self.assertIn("\n## Results by ecosystem\n\n| Check | Python |\n", output)
        self.assertIn("\n## Whole project\n", output)

    def test_list_as_json_is_the_check_list(self) -> None:
        code, output, _ = run_cli("--list", "--format", "json")
        self.assertEqual(code, EXIT_SUCCESS)
        matrix = {row["check"]: row["applies_to"] for row in json.loads(output)}
        self.assertEqual(matrix, {found.name: list(applies_to(found)) for found in discover().checks})
        self.assertEqual(matrix["ci-present"], [])
        self.assertIn("C/C++", matrix["ci-build-types"])
        self.assertNotIn("Python", matrix["ci-build-types"])

    def test_support_matrix_is_printed_as_markdown(self) -> None:
        code, output, _ = run_cli("--support-matrix")
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertEqual(
            output, render(support_matrix(discover().checks))
        )  # printed with end="", so `>` writes the page as is
        self.assertTrue(output.startswith("# Support matrix\n"))

    def test_support_matrix_as_json(self) -> None:
        code, output, _ = run_cli("--support-matrix", "--format", "json")
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertEqual(json.loads(output)["ecosystems"][0], "C/C++")

    def test_support_matrix_needs_no_yaml(self) -> None:
        with mock.patch.object(yaml_support, "available", return_value=False):
            code, _, _ = run_cli("--support-matrix")
        self.assertEqual(code, EXIT_SUCCESS)
