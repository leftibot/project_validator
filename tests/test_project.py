import shutil
import subprocess
import unittest
from pathlib import Path, PurePosixPath
from unittest import mock

from project_validator.checks.data_wellformed import data_wellformed
from project_validator.core import Project, Status
from project_validator.facts import Unknown
from tests.support import PROJECT_LAYOUTS, layout_project, make_context, temp_project


class ProjectTests(unittest.TestCase):
    def test_a_file_exists_only_spelled_as_it_is(self) -> None:
        with temp_project({"Makefile": ""}) as root:
            project = Project(root)
            self.assertEqual(
                (project.exists("Makefile"), project.exists("makefile"), project.exists("x")), (True, False, False)
            )

    def test_finds_cmake_files_recursively(self) -> None:
        files = {"CMakeLists.txt": "", "src/CMakeLists.txt": "", "cmake/Warnings.cmake": "", "src/main.cpp": ""}
        with temp_project(files) as root:
            self.assertEqual(
                Project(root).cmake_files(), ["CMakeLists.txt", "cmake/Warnings.cmake", "src/CMakeLists.txt"]
            )

    def test_a_project_is_read_as_it_was_first_listed(self) -> None:
        """The tree is walked once: extractors ask for the files many times, and a project does not change under a
        run."""
        with temp_project({"src/main.c": ""}) as root:
            project = Project(root)
            self.assertEqual((project.files(), project.tracked_files()), (["src/main.c"], ["src/main.c"]))
            (root / "src" / "later.c").write_text("")
            self.assertEqual((project.files(), project.tracked_files()), (["src/main.c"], ["src/main.c"]))

    def test_lists_every_file_of_every_layout(self) -> None:
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout) as root:
                self.assertEqual(Project(root).files(), sorted(layout.files))

    def test_every_layout_skips_hidden_vendored_and_build_directories(self) -> None:
        skipped = {
            ".git/HEAD": "",
            ".venv/lib/x.py": "",
            "node_modules/y/y.cpp": "",
            "__pycache__/z.py": "",
            "build/CMakeCache.txt": "",
            "build/_deps/x/x.c": "",
            "out/CACHEDIR.TAG": "",
            "out/debug/x.rs": "",
        }
        for layout in PROJECT_LAYOUTS:
            with layout_project(self, layout, skipped) as root:
                self.assertEqual(Project(root).files(), sorted(layout.files))

    def test_skips_hidden_directories_and_build_trees(self) -> None:
        files = {
            "CMakeLists.txt": "",
            ".git/CMakeLists.txt": "",
            "out/CMakeCache.txt": "",
            "out/_deps/x/CMakeLists.txt": "",
        }
        with temp_project(files) as root:
            self.assertEqual(Project(root).cmake_files(), ["CMakeLists.txt"])

    def test_skips_excluded_directories(self) -> None:
        files = {"CMakeLists.txt": "", "tests/fixtures/x/CMakeLists.txt": "", "tests/CMakeLists.txt": ""}
        with temp_project(files) as root:
            project = Project(root, frozenset({PurePosixPath("tests/fixtures")}))
            self.assertEqual(project.cmake_files(), ["CMakeLists.txt", "tests/CMakeLists.txt"])

    def test_files_in_filters_by_suffix_and_ignores_missing_directories(self) -> None:
        files = {"w/a.yml": "", "w/b.yaml": "", "w/c.txt": ""}
        with temp_project(files) as root:
            project = Project(root)
            self.assertEqual(project.files_in("w", (".yml", ".yaml")), ["w/a.yml", "w/b.yaml"])
            self.assertEqual(project.files_in("missing", (".yml",)), [])


def git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True)  # noqa: S603, S607 - tests


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class TrackedFilesTests(unittest.TestCase):
    def test_lists_the_files_git_tracks(self) -> None:
        files = {"src/main.c": "", ".github/workflows/ci.yml": "", "untracked.c": "", "tests/fixtures/f.c": ""}
        with temp_project(files) as root:
            git(root, "init", "-q")
            git(root, "add", "src", ".github", "tests")
            project = Project(root, frozenset({PurePosixPath("tests/fixtures")}))
            self.assertEqual(project.tracked_files(), [".github/workflows/ci.yml", "src/main.c"])

    def test_lists_every_file_outside_a_git_checkout(self) -> None:
        with temp_project({"src/main.c": "", ".github/ci.yml": ""}) as root:
            self.assertEqual(Project(root).tracked_files(), ["src/main.c"])
            with mock.patch("shutil.which", return_value=None):
                self.assertEqual(Project(root).tracked_files(), ["src/main.c"])

    def _read(self, path: str, text: str) -> tuple[Status, bool]:
        """The data-wellformed status of a project of one deeply nested file, and whether its facts say it was nested
        too deeply."""
        with temp_project({path: text}) as root:
            context = make_context(root)
            unknown = any(isinstance(fact, Unknown) and "nested too deeply" in fact.reason for fact in context.facts)
            return data_wellformed.run(context).status, unknown

    def test_deeply_nested_files_do_not_crash_the_extraction(self) -> None:
        job = "jobs:\n  a:\n    runs-on: ubuntu-latest\n"
        cmake = "project(x)\nadd_executable(a a.c)\n"
        generator = "target_compile_options(a PRIVATE " + "$<$<BOOL:1>:" * 500 + "-W" + ">" * 500 + ")\n"
        cases = {
            "CMakeLists.txt": (
                cmake + "if(A)\n" * 3000 + "endif()\n" * 3000,
                cmake + "foreach(i 1)\n" * 3000 + "endforeach()\n" * 3000,
                cmake + "if(" + "(" * 2000 + "A" + ")" * 2000 + ")\nendif()\n",
            ),
            "meson.build": ("x = 'a'" + " + 'a'" * 3000 + "\n",),
            ".github/workflows/ci.yml": (
                job + "    steps:\n      - run: echo\n    x: " + "[" * 3000 + "]" * 3000 + "\n",
                job + "    steps:\n      - run: echo " + "$(" * 2000 + "x" + ")" * 2000 + "\n",
                job + "    if: ${{ " + "(" * 2000 + "true" + ")" * 2000 + " }}\n    steps:\n      - run: echo\n",
            ),
        }
        for path, texts in cases.items():
            for text in texts:
                with self.subTest(path=path, text=text[-30:]):
                    _, unknown = self._read(path, text)
                    if path != ".github/workflows/ci.yml":
                        self.assertTrue(unknown)
        with self.subTest("generator expression"):
            self._read("CMakeLists.txt", cmake + generator)
        with self.subTest("data yaml"):
            status, _ = self._read("data.yaml", "[" * 3000 + "]" * 3000 + "\n")
            self.assertEqual(status, Status.FAIL)
