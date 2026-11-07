"""The fact database: what the extractors learned about a project, each fact with where it was found.

Facts are immutable records. Extractors (CI providers first; build systems, toolchains and tools later) record them;
questions query them (see docs/architecture.md). Nothing here judges a project.
"""

import dataclasses
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType

type Location = tuple[str | int, ...]

NOTHING: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True, slots=True, kw_only=True)
class Origin:
    """Where a fact was found: a file, and the place inside it (`("jobs", "test", "steps", 3, "run")`)."""

    path: str
    at: Location = ()

    def __str__(self) -> str:
        """`.github/workflows/ci.yml:jobs.test.steps[3].run`."""
        place = ""
        for part in self.at:
            place += f"[{part}]" if isinstance(part, int) else f".{part}" if place else part
        return f"{self.path}:{place}" if place else self.path


@dataclass(frozen=True, slots=True, kw_only=True)
class Fact:
    origin: Origin


@dataclass(frozen=True, slots=True, kw_only=True)
class CiConfiguration(Fact):
    """A CI configuration file of `provider`, whether or not any job is read from it."""

    provider: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CiJob(Fact):
    """One CI job as it runs: one combination of its matrix, on one runner.

    `id` is unique in the project and names the job in other facts. `heuristic` jobs come from configuration that is
    not parsed; their commands are unknown. A job that never `builds` the project (pre-commit.ci, which only runs
    hooks) runs tools, but is no platform or build configuration the project is built on.
    """

    id: str
    provider: str
    name: str
    os: str
    matrix: Mapping[str, str] = NOTHING
    image: str | None = None
    env: Mapping[str, str] = NOTHING
    heuristic: bool = False
    builds: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class Command(Fact):
    """A command a CI job runs: its arguments as the shell splits them, after matrix values are substituted.

    `line` is the command as written. Arguments still holding an expression the validator cannot evaluate
    (`${{ secrets.TOKEN }}`) are kept as written.
    """

    job: str
    argv: tuple[str, ...]
    line: str
    env: Mapping[str, str] = NOTHING
    directory: str | None = None
    # The condition the step runs under (GitHub's `if:`), as written after matrix values are substituted.
    condition: str | None = None
    # The commands that ran this one in turn, outermost first (CI's `npm test`, then the package's test script).
    via: tuple[Origin, ...] = ()


_VARIABLE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")


def resolved(command: Command) -> tuple[str, ...]:
    """The command's arguments with the shell variables its environment defines (`$BUILD_TYPE`) put in place; a
    word that is one variable becomes the words of its value.

    A command that runs another (`sudo make`, `bundle exec rake`) is expanded into that command by a launcher (see
    `project_validator.facts.expansion.launcher`)."""

    def value(match: re.Match[str]) -> str:
        return command.env.get(match[1] or match[2], match[0])

    def words(word: str) -> tuple[str, ...]:
        """A word that is one variable splits into the words of its value, as the shell splits an unquoted
        expansion (`$CABAL v2-test` with `CABAL="cabal -v"`)."""
        expanded = _VARIABLE.sub(value, word)
        whole = _VARIABLE.fullmatch(word) is not None and expanded != word
        return tuple(expanded.split()) if whole and expanded.strip() else (expanded,)

    return tuple(found for word in command.argv for found in words(word))


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionStep(Fact):
    """A reusable step a CI job runs, such as a GitHub action, with its inputs."""

    job: str
    uses: str
    inputs: Mapping[str, str] = NOTHING
    condition: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Unknown(Fact):
    """Something an extractor could not read, so that its absence is not taken for "no".

    `hides` says what it may hide: whole `jobs` (a reusable workflow in another repository, a provider scanned
    heuristically), `commands` of a job (a line that cannot be split, a script that cannot be expanded), the
    `matrix` values of a job, or `settings` of the `tools` named. A question counts the unknowns that may hide what it
    asks about.
    """

    subject: str
    reason: str
    hides: str = "commands"
    tools: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Setting(Fact):
    """A setting of a tool, as a configuration file writes it: `key` is dotted (`run.branch`) and `value` is a string,
    number, boolean, or tuple of those. `heuristic` settings are matched in text that is not parsed (code)."""

    tool: str
    key: str
    value: object
    heuristic: bool = False

    @property
    def path(self) -> str:
        return self.origin.path


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfigurationFile(Fact):
    """A file a settings reader (`reader`, named after its tool) read, whatever it holds."""

    reader: str

    @property
    def path(self) -> str:
        return self.origin.path


class Facts:
    """Every fact about one project, in the order the extractors recorded them, with the queries questions use."""

    __slots__ = ("_kinds", "all")

    def __init__(self, found: Iterable[Fact] = ()) -> None:
        self.all = tuple(found)
        self._kinds: dict[type[Fact], tuple[Fact, ...]] = {}

    def __iter__(self) -> Iterator[Fact]:
        return iter(self.all)

    def __add__(self, more: Iterable[Fact]) -> Facts:
        return Facts((*self.all, *more))

    def of[F: Fact](self, kind: type[F]) -> tuple[F, ...]:
        """The facts of `kind` (or a subclass), in order."""
        if kind not in self._kinds:
            self._kinds[kind] = tuple(fact for fact in self.all if isinstance(fact, kind))
        return self._kinds[kind]  # type: ignore[return-value]

    def where[F: Fact](self, kind: type[F], **fields: object) -> tuple[F, ...]:
        """The facts of `kind` whose `fields` have the values given."""
        return tuple(
            fact for fact in self.of(kind) if all(getattr(fact, name) == value for name, value in fields.items())
        )

    def settings(self, tool: str, *, paths: Iterable[str] | None = None) -> tuple[Setting, ...]:
        """The settings of `tool`, in the files `paths` (in that order) or anywhere."""
        found = self.where(Setting, tool=tool)
        if paths is None:
            return found
        return tuple(setting for path in dict.fromkeys(paths) for setting in found if setting.path == path)

    def setting(self, tool: str, key: str, *, paths: Iterable[str] | None = None) -> Setting | None:
        """The first setting of `tool` called `key`, in the files `paths` (in that order) or anywhere."""
        return next((setting for setting in self.settings(tool, paths=paths) if setting.key == key), None)

    def first_file(self, reader: str, paths: Iterable[str]) -> str | None:
        """The first of `paths` that `reader` read: the file a tool reads when it reads the first that exists."""
        read = {found.path for found in self.where(ConfigurationFile, reader=reader)}
        return next((path for path in paths if path in read), None)

    def configured(self, tool: str, paths: Iterable[str]) -> str | None:
        """The first of `paths` that has a setting of `tool`: the file the tool reads, when it reads the first."""
        return next((setting.path for setting in self.settings(tool, paths=paths)), None)

    def as_dicts(self) -> list[dict[str, object]]:
        return [as_dict(fact) for fact in self.all]


def as_dict(fact: Fact) -> dict[str, object]:
    """A fact as JSON-ready data: its kind, then its fields, with the origin written out."""
    data: dict[str, object] = {"kind": type(fact).__name__}
    for item in dataclasses.fields(fact):
        value = getattr(fact, item.name)
        data[item.name] = _plain(value)
    return data


def _plain(value: object) -> object:
    if isinstance(value, Origin):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        # A value of a fact (where a build file's setting applies): its fields that say something.
        fields = ((item.name, getattr(value, item.name)) for item in dataclasses.fields(value))
        return {name: _plain(item) for name, item in fields if item is not None and item != frozenset()}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, frozenset):
        return sorted((_plain(item) for item in value), key=repr)
    return value


def collected(groups: Iterable[Iterable[Fact]]) -> Facts:
    return Facts(tuple(fact for group in groups for fact in group))


__all__ = [
    "NOTHING",
    "ActionStep",
    "CiConfiguration",
    "CiJob",
    "Command",
    "ConfigurationFile",
    "Fact",
    "Facts",
    "Origin",
    "Setting",
    "Unknown",
    "as_dict",
    "collected",
    "resolved",
]
