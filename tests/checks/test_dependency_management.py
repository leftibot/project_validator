import shutil
import unittest
from collections.abc import Mapping
from dataclasses import replace

from project_validator.checks.dependency_management import VENDOR_HINT, dependency_management
from project_validator.core import Options, Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.go import GO, GO_MODULES_MANAGER
from project_validator.ecosystems.python import PYTHON, PYTHON_PACKAGE_MANAGER
from project_validator.ecosystems.rust import CARGO_PACKAGES, RUST
from project_validator.facts import Facts
from project_validator.facts.dependencies import Lock, PackageManager
from project_validator.policy.dependencies import judge_dependencies
from project_validator.questions.dependencies import dependency_answer
from tests.support import (
    FIXTURES,
    WELL_CONFIGURED,
    make_context,
    run_as,
    run_in_every_layout,
    temp_project,
)
from tests.test_project import git

C_HINT = (
    "if the project has dependencies, consider a dependency manager: CPM, FetchContent, Meson wraps, vcpkg or Conan"
)
NO_DEPENDENCIES = Result.passed("no dependencies are declared")
PYTHON_MANIFEST = {"pyproject.toml": "[project]\ndependencies = ['requests']\n"}


def _run_in_git(files: Mapping[str, str], tracked: tuple[str, ...]) -> Result:
    with temp_project(files) as root:
        git(root, "init", "-q")
        git(root, "add", *tracked)
        return dependency_management.run(make_context(root))


def _declared(where: str, managers: str, locked: str = "") -> Result:
    message = f"dependencies are declared in {where} ({managers})"
    return Result.passed(f"{message} and locked in {locked}" if locked else message)


def _not_locked(where: str, managers: str, hint: str) -> Result:
    return Result.warned(f"dependencies are declared in {where} ({managers}) but not locked", hint)


class DependencyManagementTests(unittest.TestCase):
    def test_applies_to_the_languages_of_its_package_managers(self) -> None:
        self.assertLessEqual(C_FAMILY | {"Python", "Rust", "Go"}, dependency_management.languages)

    def test_the_fixtures(self) -> None:
        cases = {
            "well_configured_c_cpp": _declared("cmake/Dependencies.cmake", "FetchContent"),
            "well_configured_python": _declared("pyproject.toml", "Python packages", "uv.lock"),
            "well_configured_rust": _declared("fuzz/Cargo.toml", "Cargo", "fuzz/Cargo.lock"),
            "well_configured_go": NO_DEPENDENCIES,
        }
        for fixture, expected in cases.items():
            with self.subTest(fixture):
                self.assertEqual(dependency_management.run(make_context(FIXTURES / fixture)), expected)
        for fixture in ("bare_c_cpp", "bare_python", "bare_rust", "bare_go"):
            with self.subTest(fixture):
                self.assertEqual(dependency_management.run(make_context(FIXTURES / fixture)).status, Status.WARN)

    def test_a_language_no_known_package_manager_handles_is_skipped(self) -> None:
        answer = dependency_answer("Lang", Facts(()), ())
        self.assertEqual(
            judge_dependencies(answer),
            Result(status=Status.SKIP, message="no known package manager resolves Lang dependencies"),
        )


class VendoringTests(unittest.TestCase):
    def test_committed_third_party_code_warns(self) -> None:
        for directory in ("third_party", "third-party", "3rdparty", "external", "extern", "vendor"):
            with self.subTest(directory):
                result = run_in_every_layout(self, dependency_management, {f"{directory}/lib/lib.c": ""})
                expected = Result.warned(
                    f"third-party code is committed ({directory}/); no dependencies are declared", C_HINT, VENDOR_HINT
                )
                self.assertEqual(result, expected)

    def test_git_submodules_warn(self) -> None:
        result = run_in_every_layout(self, dependency_management, {**WELL_CONFIGURED, ".gitmodules": ""})
        expected = Result.warned(
            "third-party code is committed (git submodules (.gitmodules)); dependencies are declared in "
            "cmake/Dependencies.cmake (FetchContent)",
            VENDOR_HINT,
        )
        self.assertEqual(result, expected)

    def test_an_unknown_answer_stays_an_error_whatever_is_vendored(self) -> None:
        files = {"pyproject.toml": "[project\n", ".gitmodules": ""}
        self.assertEqual(run_as(self, dependency_management, files, PYTHON).status, Status.ERROR)

    def test_a_file_named_like_a_vendor_directory_is_not_one(self) -> None:
        self.assertEqual(run_in_every_layout(self, dependency_management, {"vendor": ""}).status, Status.PASS)

    def test_go_mod_vendor_output_is_not_vendored_code(self) -> None:
        files = {"go.mod": "module m\n", "go.sum": "", "vendor/modules.txt": "", "vendor/x/y.go": ""}
        self.assertEqual(run_as(self, dependency_management, files, GO), NO_DEPENDENCIES)

    def test_a_vendor_directory_without_modules_txt_is_vendored(self) -> None:
        result = run_as(self, dependency_management, {"go.mod": "module m\n", "vendor/x/y.go": ""}, GO)
        self.assertEqual(result.status, Status.WARN)


class CAndCxxTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, dependency_management, files)

    def test_passes_with_a_note_without_a_dependency_manager(self) -> None:
        self.assertEqual(self._run({}), Result.passed("no dependencies are declared", C_HINT))

    def test_names_every_dependency_manager(self) -> None:
        files = {
            "cmake/CPM.cmake": "",
            "cmake/deps.cmake": "CPMAddPackage(NAME fmt GITHUB_REPOSITORY fmtlib/fmt GIT_TAG 11.0.2)\n",
            "vcpkg.json": "{}",
            "conanfile.txt": "",
            "subprojects/zlib.wrap": "",
        }
        self.assertEqual(
            self._run(files),
            _declared(
                "cmake/deps.cmake, conanfile.txt, subprojects/zlib.wrap and 1 more", "CPM, Conan, Meson wraps, vcpkg"
            ),
        )

    def test_commented_out_calls_declare_nothing(self) -> None:
        self.assertEqual(self._run({"CMakeLists.txt": "# FetchContent_Declare(x)\n"}).message, NO_DEPENDENCIES.message)


class PythonTests(unittest.TestCase):
    HINT = PYTHON_PACKAGE_MANAGER.lock_hint

    def _run(self, files: dict[str, str], options: Options | None = None) -> Result:
        return run_as(self, dependency_management, files, PYTHON, options=options)

    def test_warns_when_declared_dependencies_are_not_locked(self) -> None:
        cases = {
            "pyproject.toml": PYTHON_MANIFEST,
            "setup.py": {"setup.py": "setup(install_requires=['requests'])\n"},
            "requirements.txt": {"requirements.txt": "requests==2.32.3\n"},
        }
        for where, files in cases.items():
            with self.subTest(where):
                self.assertEqual(self._run(files), _not_locked(where, "Python packages", self.HINT))

    def test_poetry_dependencies_besides_python_are_declared(self) -> None:
        poetry = "[tool.poetry.dependencies]\npython = '^3.12'\nrequests = '^2'\n"
        self.assertEqual(self._run({"pyproject.toml": poetry}).status, Status.WARN)
        for python_only in ("[tool.poetry.dependencies]\npython = '^3.12'\n", "[tool]\npoetry = 1\n", "x = 1\n"):
            with self.subTest(python_only):
                self.assertEqual(self._run({"pyproject.toml": python_only}), NO_DEPENDENCIES)

    def test_lockfiles_lock_them(self) -> None:
        for lockfile in ("uv.lock", "poetry.lock", "pdm.lock", "Pipfile.lock", "pylock.toml", "pylock.dev.toml"):
            with self.subTest(lockfile):
                result = self._run({**PYTHON_MANIFEST, lockfile: ""})
                self.assertEqual(result, _declared("pyproject.toml", "Python packages", lockfile))

    def test_hash_pinned_requirements_lock_them(self) -> None:
        pinned = (
            "requests==2.32.3 \\\n    --hash=sha256:70761cfe03c773ceb22aa2f671b4757976145175cdfca038c02654d061d6dcc6\n"
        )
        self.assertEqual(
            self._run({"requirements.txt": pinned}),
            _declared("requirements.txt", "Python packages", "requirements.txt"),
        )
        several = self._run({"requirements/dev.txt": pinned, "requirements/docs.txt": pinned})
        self.assertEqual(
            several.message.rpartition(" and locked in ")[2], "requirements/dev.txt, requirements/docs.txt"
        )

    def test_an_unreadable_manifest_is_unknown(self) -> None:
        result = self._run({"pyproject.toml": "[project\n"})
        self.assertEqual(result.status, Status.ERROR)
        self.assertEqual(
            result.message,
            "whether the dependencies are managed and locked is unknown: some of what it runs could not be read",
        )
        self.assertEqual(self._run({"pyproject.toml": "[project\n"}, Options(allow_unknown=True)), NO_DEPENDENCIES)

    def test_ci_lockfiles_count_only_when_nothing_else_locks(self) -> None:
        pinned = "pyyaml==6.0.2 --hash=sha256:0a\n"
        ci = {".github/requirements/test.txt": pinned, ".github/actions/tool/pylock.toml": ""}
        locks = ".github/actions/tool/pylock.toml, .github/requirements/test.txt"
        self.assertEqual(self._run({**PYTHON_MANIFEST, **ci}), _declared("pyproject.toml", "Python packages", locks))
        self.assertEqual(
            self._run({**PYTHON_MANIFEST, **ci, "uv.lock": ""}),
            _declared("pyproject.toml", "Python packages", "uv.lock"),
        )

    def test_the_docs_and_tooling_have_dependencies_of_their_own(self) -> None:
        files = {"docs/requirements.txt": "sphinx\n", "scripts/requirements.txt": "click\n"}
        self.assertEqual(self._run(files), NO_DEPENDENCIES)

    def test_a_lockfile_locks_the_units_below_it(self) -> None:
        files = {
            "pyproject.toml": "[tool.uv.workspace]\nmembers = ['packages/*']\n",
            "uv.lock": "",
            "packages/a/pyproject.toml": "[project]\nname = 'a'\ndependencies = ['requests']\n",
            "packages/a/a/__init__.py": "",
        }
        with temp_project(files) as root:
            result = dependency_management.run(make_context(root))
        self.assertEqual(result, _declared("packages/a/pyproject.toml", "Python packages", "uv.lock"))


class RustTests(unittest.TestCase):
    HINT = CARGO_PACKAGES.lock_hint

    def _run(self, files: dict[str, str]) -> Result:
        """Rust layouts build a binary, so these projects are written out whole."""
        with temp_project(files) as root:
            context = make_context(root)
            self.assertEqual(context.structure.languages, RUST.languages)
            return dependency_management.run(context)

    def test_a_library_need_not_commit_cargo_lock(self) -> None:
        files = {"Cargo.toml": "[package]\nname = 'x'\n\n[dependencies]\nlibc = '0.2'\n", "src/lib.rs": ""}
        self.assertEqual(self._run(files), _declared("Cargo.toml", "Cargo"))

    def test_a_binary_commits_cargo_lock(self) -> None:
        manifest = "[package]\nname = 'x'\n\n[dev-dependencies]\nproptest = '1'\n"
        binaries = {
            "src/main.rs": {"src/main.rs": ""},
            "src/bin": {"src/bin/tool.rs": ""},
            "[[bin]]": {"Cargo.toml": manifest + "\n[[bin]]\nname = 'tool'\npath = 'tool.rs'\n", "src/lib.rs": ""},
        }
        for binary, files in binaries.items():
            with self.subTest(binary):
                result = self._run({"Cargo.toml": manifest, **files})
                self.assertEqual(result, _not_locked("Cargo.toml", "Cargo", self.HINT))
                locked = self._run({"Cargo.toml": manifest, **files, "Cargo.lock": ""})
                self.assertEqual(locked, _declared("Cargo.toml", "Cargo", "Cargo.lock"))

    def test_workspace_members_declare_their_dependencies(self) -> None:
        """`[workspace.dependencies]` only sets the versions its members use (`serde.workspace = true`)."""
        files = {
            "Cargo.toml": "[workspace]\nmembers = ['a']\n\n[workspace.dependencies]\nserde = '1'\n",
            "a/Cargo.toml": "[package]\nname = 'a'\n",
            "a/src/lib.rs": "",
        }
        self.assertEqual(self._run(files), NO_DEPENDENCIES)
        member = {**files, "a/Cargo.toml": "[package]\nname = 'a'\n\n[dependencies]\nserde.workspace = true\n"}
        self.assertEqual(self._run(member), _declared("a/Cargo.toml", "Cargo"))

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_an_untracked_cargo_lock_is_not_committed(self) -> None:
        files = {"Cargo.toml": "[dependencies]\nlibc = '0.2'\n", "src/main.rs": "", "Cargo.lock": ""}
        self.assertEqual(_run_in_git(files, ("Cargo.toml", "src")).status, Status.WARN)
        self.assertEqual(_run_in_git(files, ("Cargo.toml", "src", "Cargo.lock")).status, Status.PASS)


class GoTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, dependency_management, files, GO)

    def test_required_modules_need_go_sum(self) -> None:
        go_mod = "module m\n\ngo 1.23\n\nrequire (\n\tgolang.org/x/text v0.14.0\n)\n"
        self.assertEqual(
            self._run({"go.mod": go_mod}), _not_locked("go.mod", "Go modules", GO_MODULES_MANAGER.lock_hint)
        )
        self.assertEqual(self._run({"go.mod": go_mod, "go.sum": ""}), _declared("go.mod", "Go modules", "go.sum"))

    def test_a_module_without_requirements_has_no_dependencies(self) -> None:
        self.assertEqual(self._run({"go.mod": "module m\n"}), NO_DEPENDENCIES)
        self.assertEqual(self._run({"main.go": "package main\n"}), NO_DEPENDENCIES)


class NestedLockTests(unittest.TestCase):
    """A lockfile deeper in a unit locks it only for a manager whose lockfiles do (`requirements/dev.txt`)."""

    def test_a_manager_whose_lockfiles_lock_only_beside_them(self) -> None:
        files = {"Cargo.toml": '[package]\nname = "app"\n[dependencies]\nserde = "1"\n', "src/main.rs": ""}
        files |= {"builders/linux/Cargo.lock": ""}
        cargo = PackageManager(name="Cargo", languages=frozenset({"Rust"}), lock=Lock.APPLICATIONS)
        with temp_project(files) as root:
            facts = make_context(root).facts
            nested = dependency_answer("Rust", facts, (cargo,))
            beside = dependency_answer("Rust", facts, (replace(cargo, nested_locks=False),))
        self.assertEqual(nested.locked, ("builders/linux/Cargo.lock",))
        self.assertEqual(beside.locked, ())
