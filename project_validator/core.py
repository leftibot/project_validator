"""Core types shared by the validator, its checks and its CI providers."""

import enum
import os
import shutil
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from project_validator.ci import CiAnalysis, CiFile, CiProvider
    from project_validator.facts import Facts
    from project_validator.project_map import ProjectStructure


class Status(enum.StrEnum):
    PASS = "PASS"  # noqa: S105 - a result status, not a password
    WARN = "WARN"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIP = "SKIP"

    @property
    def severity(self) -> int:
        """How bad the status is, for the worst of several to win: SKIP < PASS < WARN < FAIL < ERROR."""
        return _SEVERITY.index(self)


_SEVERITY = (Status.SKIP, Status.PASS, Status.WARN, Status.FAIL, Status.ERROR)


@dataclass(frozen=True, slots=True, kw_only=True)
class Result:
    status: Status
    message: str
    details: tuple[str, ...] = ()
    # The results this one was folded from, one per ecosystem in each unit; not compared, not printed as text or JSON.
    places: tuple[Placed, ...] = field(default=(), compare=False)

    @classmethod
    def passed(cls, message: str, *details: str) -> Result:
        return cls(status=Status.PASS, message=message, details=details)

    @classmethod
    def warned(cls, message: str, *details: str) -> Result:
        return cls(status=Status.WARN, message=message, details=details)

    @classmethod
    def failed(cls, message: str, *details: str) -> Result:
        return cls(status=Status.FAIL, message=message, details=details)

    @classmethod
    def skipped(cls, message: str, *details: str) -> Result:
        """The check does not apply (to the project, or to this language in it): not a finding."""
        return cls(status=Status.SKIP, message=message, details=details)

    def with_details(self, *details: str) -> Result:
        return Result(status=self.status, message=self.message, details=self.details + details, places=self.places)


@dataclass(frozen=True, slots=True, kw_only=True)
class Placed:
    """One ecosystem's result in one unit ("." for the root, "" for the whole project), with the tools that ran for
    the practice there."""

    ecosystem: str  # the label; "" until by_ecosystem names it
    unit: str
    result: Result
    tools: tuple[str, ...] = ()


DEFAULT_MAX_FILE_SIZE = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True, kw_only=True)
class Options:
    build: bool = False
    cmake: str = "cmake"
    ctest: str = "ctest"
    # Committed files larger than this, in bytes, belong in Git LFS or DVC.
    max_file_size: int = DEFAULT_MAX_FILE_SIZE
    # Actions published by GitHub (actions/, github/) may be pinned to tags.
    allow_official_tags: bool = False
    # Judge answers that depend on configuration that could not be read by what could, instead of erroring.
    allow_unknown: bool = False


_SKIPPED_DIRECTORIES = frozenset({"node_modules", "__pycache__"})


def _is_cmake_file(name: str) -> bool:
    return name == "CMakeLists.txt" or name.endswith(".cmake")


@dataclass(frozen=True, slots=True)
class Project:
    """Read-only view of the source tree being validated; paths are POSIX and relative to `root`."""

    root: Path
    excluded: frozenset[PurePosixPath] = frozenset()
    # The files listed so far, by what was asked: the tree is walked once, as it is when first asked.
    _listed: dict[object, list[str]] = field(default_factory=dict, repr=False, compare=False)

    def exists(self, relative: str) -> bool:
        """Whether the file exists, with its name spelled exactly so (`makefile` is not `Makefile`, even where file
        names are compared without case, as on Windows and macOS)."""
        path = self.root / relative
        return path.is_file() and path.name in os.listdir(path.parent)

    def read_text(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8", errors="replace")

    def read_head(self, relative: str, size: int = 4096) -> str:
        """The first `size` bytes of a file as text: enough for a content probe, cheap for a large file."""
        with (self.root / relative).open("rb") as file:
            return file.read(size).decode("utf-8", errors="replace")

    def files_in(self, relative_directory: str, suffixes: tuple[str, ...]) -> list[str]:
        directory = self.root / relative_directory
        if not directory.is_dir():
            return []
        return sorted(
            str(PurePosixPath(relative_directory, entry.name))
            for entry in directory.iterdir()
            if entry.is_file() and entry.name.endswith(suffixes)
        )

    def size(self, relative: str) -> int:
        return (self.root / relative).stat().st_size

    def files(self, *, hidden: frozenset[str] = frozenset()) -> list[str]:
        """Every file of the project, skipping hidden, excluded and vendored directories and build trees.

        `hidden` names hidden top-level directories (`.github`) to include all the same.
        """
        if ("files", hidden) not in self._listed:
            self._listed[("files", hidden)] = sorted(self._walk_files(hidden))
        return list(self._listed[("files", hidden)])

    def tracked_files(self) -> list[str]:
        """The files git tracks in the project, or every file when it is not a git checkout; exclusions apply."""
        if "tracked" not in self._listed:
            self._listed["tracked"] = self._git_tracked_files()
        return list(self._listed["tracked"])

    def _git_tracked_files(self) -> list[str]:
        git = shutil.which("git")
        if git is None:
            return self.files()
        listed = subprocess.run(  # noqa: S603 - argv list, no shell
            [git, "-C", str(self.root), "ls-files", "-z"], capture_output=True, check=False
        )
        if listed.returncode != 0:
            return self.files()
        paths = listed.stdout.decode("utf-8", errors="replace").split("\0")
        return sorted(path for path in paths if path and not self._excludes(path) and (self.root / path).is_file())

    def _excludes(self, relative: str) -> bool:
        return any(parent in self.excluded for parent in PurePosixPath(relative).parents)

    def cmake_files(self) -> list[str]:
        return [path for path in self.files() if _is_cmake_file(PurePosixPath(path).name)]

    def _walk_files(self, hidden: frozenset[str]) -> Iterator[str]:
        from project_validator.ecosystems import is_build_tree

        for directory, subdirectories, files in os.walk(self.root):
            current = Path(directory)
            relative = PurePosixPath(current.relative_to(self.root).as_posix())
            subdirectories[:] = [
                name
                for name in subdirectories
                if (not name.startswith(".") or (current == self.root and name in hidden))
                and name not in _SKIPPED_DIRECTORIES
                and relative / name not in self.excluded
                and not is_build_tree(current / name)
            ]
            yield from (str(PurePosixPath(relative, name)) for name in files)


class Context:
    """Everything a check may inspect; CI discovery is computed once and shared between checks."""

    def __init__(self, project: Project, providers: tuple[CiProvider, ...], options: Options) -> None:
        self.project = project
        self.providers = providers
        self.options = options
        self._shared: dict[str, object] = {}

    def shared[T](self, key: str, compute: Callable[[], T]) -> T:
        """What `compute` returns, computed once: extractors that read the same files (CMake's, for its facts and its
        custom targets) share the work."""
        if key not in self._shared:
            self._shared[key] = compute()
        return cast(T, self._shared[key])

    @cached_property
    def ci_files(self) -> tuple[CiFile, ...]:
        from project_validator.ci import find_ci_files

        return find_ci_files(self.project, self.providers)

    @cached_property
    def ci_analysis(self) -> CiAnalysis:
        """The CI jobs the facts show, as the checks judge them."""
        from project_validator.ci import ci_analysis

        return ci_analysis(self.facts)

    @cached_property
    def facts(self) -> Facts:
        """The fact database (see `project_validator.facts`), built in stages by `project_validator.extraction`."""
        from project_validator.extraction import extract_facts

        return extract_facts(self)

    @cached_property
    def structure(self) -> ProjectStructure:
        from project_validator.project_map import map_project

        return map_project(self.facts, self.ci_files, self.ci_analysis)

    @cached_property
    def tracked_files(self) -> tuple[str, ...]:
        """The files git tracks, or every file outside a git checkout (see `Project.tracked_files`)."""
        return tuple(self.project.tracked_files())

    def committed(self, relative: str) -> bool:
        return relative in self.tracked_files


type CheckFunction = Callable[[Context], Result]


def _no_languages() -> frozenset[str]:
    return frozenset()


@dataclass(frozen=True, slots=True, kw_only=True)
class Check:
    name: str
    description: str
    run: CheckFunction = field(repr=False)
    # Former names, still accepted by --only and --skip.
    aliases: tuple[str, ...] = ()
    # The languages of the components the check judges, asked when needed (plugins add components); none for a check
    # of every project.
    languages_from: Callable[[], frozenset[str]] = field(default=_no_languages, repr=False, compare=False)
    # The tool aspect the check judges (coverage, format): how the support matrix names its tools; None for a check
    # without tools.
    aspect: str | None = None

    @property
    def languages(self) -> frozenset[str]:
        """The languages the check judges, as now known; none for a check that judges every project."""
        return self.languages_from()

    def applies_to(self, languages: frozenset[str]) -> bool:
        """A check without languages is language agnostic; others apply to projects using one of their languages."""
        return not self.languages or bool(self.languages & languages)


def check(*, name: str, description: str, languages: frozenset[str] = frozenset()) -> Callable[[CheckFunction], Check]:
    """Turn a function taking a `Context` and returning a `Result` into a discoverable `Check`."""

    def wrap(function: CheckFunction) -> Check:
        return Check(name=name, description=description, run=function, languages_from=lambda: languages)

    return wrap
