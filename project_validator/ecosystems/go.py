"""Go: built with Go modules, judged by the Go versions CI runs and the go tool's own test, vet and format commands."""

import re
import shlex
from collections.abc import Callable, Iterator

from project_validator.core import Context
from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts import Command, Fact, Facts, Origin, Setting, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import has_option, positional, starts_with
from project_validator.facts.audit import audited, auditor
from project_validator.facts.axes import versions_axis
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.dependencies import PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.expansion import Action, CommandExpander, Expansion, Launched
from project_validator.facts.formatting import Enforcement, flagged, format_tool, formatted
from project_validator.facts.fuzzing import FuzzTargets, PropertyTests, fuzzed, fuzzer
from project_validator.facts.limits import Rule, limiter
from project_validator.facts.mutation import incremental_when, mutated, mutation_tool
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import SettingsReader, file_reader, json_settings, toml_settings, yaml_settings
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Definition, Run, all_of, defined_by, either, starts, when, with_option
from project_validator.text import pattern
from project_validator.tools.audits import multi_ecosystem_audits
from project_validator.tools.limits import function_length_limiters
from project_validator.tools.scanners import multi_language_scanners

_USE = re.compile(r"^\s*(?:use\s+)?(?:\(\s*)?(\.{1,2}/[^\s)]*|\.)\s*\)?\s*$", re.MULTILINE)


def _go_work_members(text: str) -> tuple[str, ...]:
    """The modules a go.work file uses (`use ./api`, or a `use (...)` block)."""
    if not re.search(r"^\s*use\b", text, re.MULTILINE):
        return ()
    return tuple(match[1] for match in _USE.finditer(text) if match[1] != ".")


GO_LANGUAGE = frozenset({"Go"})
GO_MODULES = BuildSystem(
    name="Go modules",
    files=("go.mod", "go.sum", "go.work", "go.work.sum"),
    languages=GO_LANGUAGE,
    members=_go_work_members,
)

GOLANGCI_CONFIG_FILES = (".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json")
RUNS_GOLANGCI_LINT = r"\bgolangci-lint\b(?!\s+fmt)|\bgolangci/golangci-lint-action\b"


# gofmt and the tools in its style list the files they would change (`-l`, `-d`), which CI fails on
# (`test -z "$(gofmt -l .)"`), or rewrite them (`-w`; `go fmt` runs `gofmt -l -w`).
_GOFMT_STYLE = (("gofmt",), ("gofumpt",), ("goimports",))

_GO_RUN_VALUES = frozenset({"-C", "-exec", "-tags", "-ldflags", "-gcflags", "-mod", "-modfile", "-o", "-p"})


def _go_run(command: Command, _context: Context) -> list[Expansion] | None:
    """`go run <package>[@version] args` and `go tool <name> args` run the program the package's last element names
    (`go run github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.6.1 run`); a local package (`.`) is the
    project's own code."""
    argv = resolved(command)
    if not starts_with(argv, ("go", "run"), ("go", "tool")):
        return None
    words, _ = positional(argv[1:], _GO_RUN_VALUES)
    if not words or words[0].startswith((".", "/")) or words[0].endswith(".go"):
        return []
    name = words[0].partition("@")[0].rstrip("/").rsplit("/", 1)[-1]
    return [Launched(argv=(name, *argv[argv.index(words[0]) + 1 :]))]


GO_RUN = CommandExpander(name="go run and go tool", expand=_go_run)

# golangci-lint runs the formatters its configuration enables (`formatters.enable` since v2, `linters.enable` before).
_GOFMT_FORMATTERS = frozenset({"gofmt", "gofumpt", "goimports", "gci", "golines", "swaggo"})


def _read_golangci(path: str, text: str) -> Iterator[Fact]:
    if path.endswith(".json"):
        return json_settings("golangci-lint", path, text)
    if path.endswith(".toml"):
        return toml_settings("golangci-lint", path, text)
    return yaml_settings("golangci-lint", path, text)


GOLANGCI_SETTINGS = SettingsReader(name="golangci-lint", files=GOLANGCI_CONFIG_FILES, read=_read_golangci)


def _golangci_formatters(command: Command, facts: Facts) -> Run | None:
    """`golangci-lint run`, which fails on what the formatters its configuration enables would change."""
    argv = resolved(command)
    if not starts_with(argv, ("golangci-lint", "run")):
        return None
    read = [
        setting
        for setting in facts.settings("golangci-lint")
        if setting.key in ("formatters.enable", "linters.enable")
        and isinstance(setting.value, tuple)
        and _GOFMT_FORMATTERS & set(map(str, setting.value))
    ]
    return formatted(command, facts, checks=True, read=read) if read else None


GOLANGCI_LINT_ACTION = Action(
    name="golangci/golangci-lint-action",
    runs=lambda inputs: (("golangci-lint", "run", *shlex.split(inputs.get("args", ""))),),
)

GOFMT = format_tool(
    name="gofmt",
    languages=GO_LANGUAGE,
    can={Enforcement.CHECK: 'test -z "$(gofmt -l .)"', Enforcement.APPLY: "gofmt -w ."},
    formats=either(
        flagged(*_GOFMT_STYLE, checks=("-l", "-d"), applies=("-w",)),
        flagged(("go", "fmt"), checks=()),
        flagged(("golangci-lint", "fmt"), checks=("--diff", "-d")),
        _golangci_formatters,
    ),
    style=defined_by(),
    reads=("golangci-lint",),
)

# The go tool measures statement coverage only.
_COVER = ("-cover", "-coverprofile", "-covermode", "-coverpkg")


def _go_cover(command: Command, _: Facts) -> Run | None:
    """`go test -cover` (or `go build -cover`), which counts statements (and so lines): nothing finer."""
    argv = resolved(command)
    if not starts_with(argv, ("go", "test"), ("go", "build")) or not has_option(argv, *_COVER):
        return None
    return measured(Granularity.LINE, Granularity.STATEMENT)


GO_COVER = coverage_tool(
    name="go test -cover",
    languages=GO_LANGUAGE,
    can={Granularity.LINE: "go test -cover", Granularity.STATEMENT: "go test -cover"},
    measures=_go_cover,
)

GO_TEST_FILES = TestFiles(
    name="Test functions in *_test.go files",
    languages=GO_LANGUAGE,
    path=re.compile(r"_test\.go$"),
    contains=re.compile(r"^func\s+(?:Test|Fuzz|Example)\w*\s*\(", re.MULTILINE),
)

GO_FUZZ_TARGETS = FuzzTargets(
    name="Fuzz functions (func FuzzXxx(f *testing.F))",
    languages=GO_LANGUAGE,
    path=re.compile(r"_test\.go$"),
    contains=re.compile(r"^func\s+Fuzz\w*\s*\(\w+\s+\*testing\.F\)", re.MULTILINE),
)
GO_PROPERTY_TESTS = PropertyTests(
    name="rapid and gopter tests",
    languages=GO_LANGUAGE,
    path=re.compile(r"_test\.go$"),
    contains=re.compile(r"pgregory\.net/rapid|leanovate/gopter"),
)
GO_FUZZ = fuzzer(
    name="go test -fuzz",
    languages=GO_LANGUAGE,
    how="go test -fuzz=Fuzz -fuzztime=30s",
    runs=when(all_of(starts(("go", "test")), with_option("-fuzz")), fuzzed),
    targets=(GO_FUZZ_TARGETS,),
)


GO_TEST = test_runner(
    name="go test",
    languages=GO_LANGUAGE,
    how="go test",
    runs=when(starts(("go", "test"), ("gotestsum",)), tested),
    tests=tests_of(GO_TEST_FILES.name),
)


# The Go compiler has no warnings; go vet and staticcheck report what other compilers warn about.
# golangci-lint runs both by default.
GO_LINTS = (
    pattern("go vet", rf"\bgo\s+vet\b|{RUNS_GOLANGCI_LINT}"),
    pattern("staticcheck", rf"\bstaticcheck\b|{RUNS_GOLANGCI_LINT}"),
)


WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=GO_LANGUAGE,
    requirements=always(*(required(lint, in_files=False, tools=("golangci-lint",)) for lint in GO_LINTS)),
    words=Wording(
        kind="Go linters",
        hint="run go vet and staticcheck (golangci-lint runs both) in CI",
    ),
)


def _golangci_enables(linter: str) -> Callable[[Facts], list[Setting]]:
    """The golangci-lint settings that enable `linter`: among the linters `linters.enable` names, or all of them; none
    when `linters.disable` names it."""

    def enabled(facts: Facts) -> list[Setting]:
        found = facts.settings("golangci-lint")
        if any(setting.key == "linters.disable" and _names(setting, linter) for setting in found):
            return []
        return [
            setting
            for setting in found
            if (setting.key == "linters.enable" and _names(setting, linter))
            or (setting.key == "linters.enable-all" and setting.value is True)
            or (setting.key == "linters.default" and setting.value == "all")
        ]

    return enabled


def _names(setting: Setting, linter: str) -> bool:
    return isinstance(setting.value, tuple) and linter in setting.value


def _golangci_gosec(command: Command, facts: Facts) -> Run | None:
    """`golangci-lint run` with gosec among the linters its configuration enables (or all of them)."""
    if not starts(("golangci-lint", "run"))(command):
        return None
    read = _golangci_enables("gosec")(facts)
    return scanned(read=read) if read else None


SECURITY_SCANNERS = (
    scanner(name="gosec", languages=GO_LANGUAGE, how="gosec ./...", scans=when(starts(("gosec",)), scanned)),
    scanner(
        name="golangci-lint's gosec",
        languages=GO_LANGUAGE,
        how="gosec enabled in .golangci.yml",
        scans=_golangci_gosec,
        reads=("golangci-lint",),
    ),
    *multi_language_scanners(GO_LANGUAGE),
)
GOSEC_ACTION = Action(
    name="securego/gosec", runs=lambda inputs: (("gosec", *shlex.split(inputs.get("args", "./..."))),)
)

AUDITORS = (
    auditor(
        name="govulncheck",
        languages=GO_LANGUAGE,
        how="govulncheck ./...",
        audits=when(starts(("govulncheck",)), audited),
    ),
    *multi_ecosystem_audits(GO_LANGUAGE),
)
GOVULNCHECK_ACTION = Action(name="golang/govulncheck-action", runs=lambda _inputs: (("govulncheck", "./..."),))

MAIN_PACKAGE = re.compile(r"^package\s+main\b", re.MULTILINE)
PIE = pattern("-buildmode=pie", r"-buildmode[=\s]+pie\b|\bbuildmode:\s*[\"']?pie\b")
BUILD_SETTINGS_FILES = ("Makefile", "GNUmakefile", "makefile", "justfile", ".goreleaser.yml", ".goreleaser.yaml")


def _read_programs(context: Context) -> Iterator[Fact]:
    """Whether a Go program (package main, outside the tests) is built: a library has no binary to harden."""
    project = context.project
    sources = (path for path in project.files() if path.endswith(".go") and not path.endswith("_test.go"))
    program = next((path for path in sources if MAIN_PACKAGE.search(project.read_text(path))), None)
    if program is not None:
        yield Setting(origin=Origin(path=program), tool="Go programs", key="main", value=True)


GO_PROGRAMS = SettingsReader(name="Go programs", files=("go.mod",), read_project=_read_programs)


def _no_program(facts: Facts) -> str | None:
    if facts.where(Setting, tool="Go programs"):
        return None
    return "no Go program (package main) is built; a library has no binary"


_PIE = required(PIE)
GO_BUILD_SETTINGS = requirement_reader("Go build settings", BUILD_SETTINGS_FILES, (_PIE,))
# Go is memory safe and bounds checked; what the build adds is a position-independent executable, so that the
# program's own code is randomised in memory (ASLR). That is the default on Windows and macOS, not on Linux.
HARDENING = Practice(
    name=PracticeName.HARDENING,
    languages=GO_LANGUAGE,
    requirements=always(_PIE),
    reads=(GO_BUILD_SETTINGS.name,),
    skipped=_no_program,
    words=Wording(
        kind="hardening options",
        hint="build them with -buildmode=pie (GOFLAGS=-buildmode=pie, or buildmode: pie in .goreleaser.yaml); "
        "it is the default on Windows and macOS but not on Linux",
        failed="Go programs are not built as position-independent executables",
    ),
)


# golangci-lint enables a few linters by default; a configuration that enables more asks for more.
def _more_linters(facts: Facts) -> Iterator[str]:
    """The golangci-lint configurations that enable linters beyond its defaults (`linters.enable`, `enable-all`, or
    `linters.default: all`)."""
    enabling = {"linters.enable", "linters.enable-all"}
    for setting in facts.settings("golangci-lint"):
        more = setting.value not in ((), False, None) if setting.key in enabling else setting.value == "all"
        if setting.key in (*enabling, "linters.default") and more:
            yield setting.path


_golangci_lint = when(starts(("golangci-lint", "run")), analysed)


# go vet and staticcheck are required as warnings (see WARNINGS); static analysis asks for golangci-lint's others.
GOLANGCI_LINT = analyzer(
    name="golangci-lint",
    languages=GO_LANGUAGE,
    how="golangci-lint (with linters enabled beyond its defaults in a .golangci.yml)",
    analyses=_golangci_lint,
    rules=Definition(found=_more_linters, default=False),
    reads=("golangci-lint",),
)
FUNLEN = limiter(
    name="golangci-lint's funlen",
    languages=GO_LANGUAGE,
    how="golangci-lint with funlen enabled in .golangci.yml",
    runs=_golangci_lint,
    rule=Rule(describe="funlen enabled in .golangci.yml", enabled=_golangci_enables("funlen")),
    reads=("golangci-lint",),
)
FUNCTION_LENGTH_LIMITERS = (FUNLEN, *function_length_limiters(GO_LANGUAGE))


GREMLINS_SETTINGS = file_reader("gremlins", (".gremlins.yaml",))


# `gremlins unleash` (also as `go run github.com/go-gremlins/gremlins/cmd/gremlins@v0.5.0 unleash`) mutates only the
# changes since a branch when given `--diff`.
_GREMLINS = incremental_when("gremlins", "unleash", options=("--diff",))


GREMLINS = mutation_tool(
    name="gremlins",
    languages=GO_LANGUAGE,
    how="gremlins unleash",
    runs=_GREMLINS,
    defined=defined_by(files=(GREMLINS_SETTINGS.name,)),
    incremental_how="gremlins unleash --diff <branch>",
)
GO_MUTESTING = mutation_tool(
    name="go-mutesting",
    languages=GO_LANGUAGE,
    how="go-mutesting ./...",
    runs=when(starts(("go-mutesting",)), mutated),
)

REQUIRE = re.compile(r"^\s*require\b", re.MULTILINE)

GO_MOD = manifest_reader(
    name="Go module requirements",
    manager="Go modules",
    files=("go.mod",),
    declares=lambda _path, text: bool(REQUIRE.search(text)),
)
GO_SUM = lockfile_reader(manager="Go modules", files=("go.sum",))
GO_MODULES_MANAGER = PackageManager(
    name="Go modules",
    languages=GO_LANGUAGE,
    lock_hint="commit go.sum, which holds the checksum of every module go.mod requires",
    vendor_outputs=("vendor/modules.txt",),
)


BUILD_OUTPUTS = BuildOutput(
    languages=GO_LANGUAGE,
    name="Go test binaries and coverage profiles",
    globs=ignored_at_top_level(r"\*\.test|\*\.out|bin"),
    paths=(*directories("bin"), "app.test", "coverage.out"),
    hint="consider ignoring *.test and *.out (and bin/ if binaries are built there)",
    artifacts=("*.test", "*.out", "/bin/"),
)

_GO_VERSION = r"(\d+\.\d+(?:\.\d+|\.x)?|stable|oldstable)"

GO = Ecosystem(
    label="Go",
    languages=GO_LANGUAGE,
    build_systems=(GO_MODULES,),
    source_suffixes={".go": "Go"},
    toolchain=toolchain_patterns(
        "Go",
        version=_GO_VERSION,
        inputs=("go-version",),
        images=("golang",),
        image_version=r"(\d+\.\d+)",
        commands=r"\bgo\s+(?:build|test|vet|run|mod|install|generate)\b",
        setup=("go",),
    ),
)

GO_VERSIONS = versions_axis("Go version", "Go", GO_LANGUAGE)
