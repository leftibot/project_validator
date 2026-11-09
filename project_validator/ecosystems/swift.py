"""Swift: built with SwiftPM or Xcode, judged by the Swift and Xcode versions CI runs.

A Swift build reads its settings from Package.swift or the Xcode project, so those count as evidence of what CI builds.
"""

import re
from collections.abc import Iterator

from project_validator.build_configurations import build_type_kinds
from project_validator.ecosystems.model import BuildSystem, Ecosystem, toolchain_patterns
from project_validator.facts import Command, Fact, Facts, Setting, Unknown, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import has_option, option_values, starts_with
from project_validator.facts.axes import versions_axis
from project_validator.facts.coverage import Granularity, coverage_tool, measured
from project_validator.facts.dependencies import Lock, PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.expansion import Action
from project_validator.facts.formatting import Enforcement, flagged, format_tool, formatted
from project_validator.facts.limits import Rule, limiter
from project_validator.facts.mutation import mutated, mutation_tool
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.facts.settings import (
    SettingsReader,
    file_reader,
    json_settings,
    matched_settings,
    settings,
    xml_root,
    yaml_settings,
)
from project_validator.facts.testing import TestFiles, test_runner, tested, tests_of
from project_validator.facts.tools import Run, all_of, any_of, defined_by, starts, when, with_option
from project_validator.text import pattern
from project_validator.tools.audits import multi_ecosystem_audits
from project_validator.tools.limits import function_length_limiters
from project_validator.tools.scanners import multi_language_scanners

SWIFT_LANGUAGE = "Swift"
SWIFT_ONLY = frozenset({SWIFT_LANGUAGE})
PACKAGE_SWIFT = "Package.swift"


def swiftpm_build_types(command: Command) -> frozenset[str]:
    """The configuration `swift build`, `test` or `run` builds: `-c` / `--configuration`, or SwiftPM's default
    (debug)."""
    argv = resolved(command)
    if argv[:1] != ("swift",) or len(argv) < 2 or argv[1] not in ("build", "test", "run"):
        return frozenset()
    return build_type_kinds(*(option_values(argv, "-c", "--configuration") or ["debug"]))


def xcode_build_types(command: Command) -> frozenset[str]:
    """The configuration xcodebuild builds, when it names one; without `-configuration`, the scheme decides."""
    argv = resolved(command)
    return build_type_kinds(*option_values(argv, "-configuration")) if argv[:1] == ("xcodebuild",) else frozenset()


SWIFTPM = BuildSystem(
    name="SwiftPM",
    files=(PACKAGE_SWIFT,),
    languages=SWIFT_ONLY,
    build_types=swiftpm_build_types,
)
SWIFTPM_BUILD_DIRECTORY = BuildOutput(
    name="the .build directory",
    languages=SWIFT_ONLY,
    build_systems=frozenset({"SwiftPM"}),
    globs=ignored_at_top_level(r"\.build"),
    paths=directories(".build"),
    hint="consider ignoring .build/",
    artifacts=(".build/",),
)
XCODE = BuildSystem(
    name="Xcode",
    files=("*.xcodeproj/", "*.xcworkspace/"),
    languages=SWIFT_ONLY,
    build_types=xcode_build_types,
)
XCODE_DATA = BuildOutput(
    name="Xcode's user data and derived data",
    languages=SWIFT_ONLY,
    build_systems=frozenset({"Xcode"}),
    globs=ignored_at_top_level(r"xcuserdata|DerivedData"),
    paths=directories("xcuserdata", "DerivedData"),
    hint="consider ignoring xcuserdata/ and DerivedData/",
    artifacts=("xcuserdata/", "DerivedData/"),
)
# Xcode keeps a project's build settings and its schemes inside the project directory.
XCODE_SETTINGS = re.compile(r"\.xc(?:odeproj|workspace)/(?:.+/)?(?:project\.pbxproj|[^/]+\.xcscheme)$")


SWIFT_FORMAT_FILES = file_reader("swift-format", (".swift-format",))
SWIFTFORMAT_FILES = file_reader("SwiftFormat", (".swiftformat",))


def _swift_format(command: Command, facts: Facts) -> Run | None:
    """`swift format lint --strict` (or `swift-format lint -s`) checks, as plain `lint` only warns; `swift format -i`
    (its default `format` subcommand) applies."""
    argv = resolved(command)
    prefix = starts_with(argv, ("swift", "format"), ("swift-format",))
    if prefix is None:
        return None
    words = argv[len(prefix) :]
    if words[:1] == ("lint",):
        return formatted(command, facts, checks=has_option(argv, "--strict", "-s"), applies=False)
    return formatted(command, facts, checks=False, applies=has_option(argv, "-i", "--in-place"))


# swift-format and SwiftFormat have a default style; their lint modes fail only when told to.
SWIFT_FORMAT = format_tool(
    name="swift-format",
    languages=SWIFT_ONLY,
    can={Enforcement.CHECK: "swift format lint --strict", Enforcement.APPLY: "swift format -i"},
    formats=_swift_format,
    style=defined_by(files=("swift-format",)),
)
SWIFTFORMAT = format_tool(
    name="SwiftFormat",
    languages=SWIFT_ONLY,
    can={Enforcement.CHECK: "swiftformat --lint", Enforcement.APPLY: "swiftformat"},
    formats=flagged(("swiftformat",), checks=("--lint",)),
    style=defined_by(files=("SwiftFormat",)),
)

MUTER_SETTINGS = file_reader("Muter", ("muter.conf.yml",))

MUTER = mutation_tool(
    name="Muter",
    languages=SWIFT_ONLY,
    how="muter",
    runs=when(starts(("muter",)), mutated),
    defined=defined_by(files=(MUTER_SETTINGS.name,)),
)

SWIFT_TEST_FILES = TestFiles(
    name="XCTestCase classes or Swift Testing @Test functions",
    languages=SWIFT_ONLY,
    path=re.compile(r"\.swift$"),
    contains=re.compile(r"\bXCTestCase\b|^\s*@(?:Test|Suite)\b", re.MULTILINE),
)


_XCODEBUILD_TESTS = all_of(starts(("xcodebuild",)), with_option("test", "test-without-building"))
_swift_tests = when(any_of(starts(("swift", "test")), _XCODEBUILD_TESTS), tested)


SWIFT_TESTS = test_runner(
    name="swift test or xcodebuild test",
    languages=SWIFT_ONLY,
    how="swift test or xcodebuild test",
    runs=_swift_tests,
    tests=tests_of(SWIFT_TEST_FILES.name),
)


_swift_test = when(
    all_of(starts(("swift", "test")), with_option("--enable-code-coverage")),
    lambda: measured(Granularity.LINE, Granularity.REGION),
)


def _read_xcode_settings(path: str, text: str) -> Iterator[Fact]:
    """A scheme's test action attributes, or a test plan's options."""
    if path.endswith(".xctestplan"):
        yield from json_settings("Xcode", path, text)
        return
    root = xml_root("Xcode", path, text)
    if isinstance(root, Unknown):
        yield root
        return
    for action in root.iter("TestAction"):
        yield from settings("Xcode", path, ((f"TestAction.{name}", value) for name, value in action.attrib.items()))


XCODE_TEST_SETTINGS = SettingsReader(name="Xcode", files=("*.xcscheme", "*.xctestplan"), read=_read_xcode_settings)


def _turns_on_coverage(setting: Setting) -> bool:
    if setting.key == "TestAction.codeCoverageEnabled":
        return setting.value == "YES"
    return setting.key.startswith("defaultOptions.codeCoverage") and setting.value is not False


def _xcodebuild(command: Command, facts: Facts) -> Run | None:
    """`xcodebuild test`, with code coverage turned on by its options, the scheme it runs or a test plan (any scheme
    when it names none)."""
    argv = resolved(command)
    if not _XCODEBUILD_TESTS(command):
        return None
    if "YES" in option_values(argv, "-enableCodeCoverage"):
        return measured(Granularity.LINE, Granularity.REGION)
    schemes = tuple(f"/{name}.xcscheme" for name in option_values(argv, "-scheme")) or (".xcscheme",)
    read = [
        setting
        for setting in facts.settings("Xcode")
        if setting.path.endswith((*schemes, ".xctestplan")) and _turns_on_coverage(setting)
    ]
    return measured(Granularity.LINE, Granularity.REGION, read=read) if read else None


SWIFTPM_COVERAGE = coverage_tool(
    name="swift test",
    languages=SWIFT_ONLY,
    can={
        Granularity.LINE: "swift test --enable-code-coverage",
        Granularity.REGION: "swift test --enable-code-coverage",
    },
    measures=_swift_test,
)
XCODE_COVERAGE = coverage_tool(
    name="Xcode",
    languages=SWIFT_ONLY,
    can={
        Granularity.LINE: "xcodebuild test -enableCodeCoverage YES",
        Granularity.REGION: "xcodebuild test -enableCodeCoverage YES",
    },
    measures=_xcodebuild,
    reads=("Xcode",),
)

RUNS_SWIFTLINT = r"(?<![\w-])swiftlint\b(?!\.yml)(?![^\n]*\s(?:--fix|autocorrect)\b)|\bSwiftLintPlugin\b"
SWIFTLINT = pattern("SwiftLint", RUNS_SWIFTLINT)
COMPLETE_CONCURRENCY = pattern(
    "complete concurrency checking",
    r"swift-tools-version:\s*6|\bswiftLanguageModes?\s*:\s*\[\s*\.v6|-strict-concurrency=complete"
    r"|\bStrictConcurrency\b|\bSWIFT_STRICT_CONCURRENCY\s*=\s*complete\b|\bSWIFT_VERSION\s*=\s*6",
)


SWIFT_BUILD_SETTINGS_FILES = (PACKAGE_SWIFT, "*.pbxproj", "*.xcconfig", "*.xcscheme")
_SWIFT_WARNINGS = (required(SWIFTLINT, tools=("SwiftLint",)), required(COMPLETE_CONCURRENCY))
WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=SWIFT_ONLY,
    requirements=always(*_SWIFT_WARNINGS),
    reads=("Swift build settings",),
    words=Wording(
        kind="Swift warning settings",
        hint="run SwiftLint and check concurrency completely (Swift 6 language mode, or -strict-concurrency=complete)",
    ),
)

_SWIFT_WARNINGS_AS_ERRORS = (
    required(
        pattern(
            "-warnings-as-errors",
            r"-warnings-as-errors\b|\btreatAllWarnings\s*\(\s*as:\s*\.error\b"
            r"|\bSWIFT_TREAT_WARNINGS_AS_ERRORS\s*=\s*YES\b",
        )
    ),
)
SWIFT_BUILD_SETTINGS = requirement_reader(
    "Swift build settings", SWIFT_BUILD_SETTINGS_FILES, (*_SWIFT_WARNINGS, *_SWIFT_WARNINGS_AS_ERRORS)
)
WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=SWIFT_ONLY,
    requirements=always(*_SWIFT_WARNINGS_AS_ERRORS),
    any_one=True,
    reads=(SWIFT_BUILD_SETTINGS.name,),
    words=Wording(
        kind="warnings as errors",
        searched="CI configuration, Package.swift or the Xcode build settings",
        hint="build with -Xswiftc -warnings-as-errors (SwiftPM 6.2: treatAllWarnings(as: .error); Xcode: "
        "SWIFT_TREAT_WARNINGS_AS_ERRORS = YES)",
    ),
)

# Compiling away Swift's bounds, overflow and exclusivity checks removes the safety the language builds in.
UNCHECKED = (
    pattern("-Ounchecked", r"-Ounchecked\b|\bSWIFT_OPTIMIZATION_LEVEL\s*=\s*\"?-Ounchecked"),
    pattern("unchecked exclusivity", r"-enforce-exclusivity=unchecked\b|\bSWIFT_ENFORCE_EXCLUSIVE_ACCESS\s*=\s*off\b"),
)


_UNCHECKED = tuple(required(option) for option in UNCHECKED)
SWIFT_HARDENING_SETTINGS = requirement_reader("Swift optimization settings", SWIFT_BUILD_SETTINGS_FILES, _UNCHECKED)
HARDENING = Practice(
    name=PracticeName.HARDENING,
    languages=SWIFT_ONLY,
    requirements=always(*_UNCHECKED),
    reads=(SWIFT_HARDENING_SETTINGS.name,),
    forbids=True,
    words=Wording(
        kind="Swift's runtime safety checks",
        hint="build releases with -O (the default), which keeps bounds, overflow and exclusivity checks",
        passed="release builds keep Swift's runtime safety checks (no -Ounchecked)",
        failed="Swift's runtime safety checks are compiled away",
    ),
)

SWIFTLINT_CONFIG = ".swiftlint.yml"
SWIFTLINT_SETTINGS = SettingsReader(
    name="SwiftLint", files=(SWIFTLINT_CONFIG,), read=lambda path, text: yaml_settings("SwiftLint", path, text)
)
_SWIFTLINT_PLUGIN = re.compile(r"\bSwiftLint(?:Build)?Plugin\b")
SWIFTLINT_PLUGIN = SettingsReader(
    name="SwiftLint plugin",
    files=(PACKAGE_SWIFT,),
    read=lambda path, text: matched_settings("SwiftPM", path, text, {"plugin": (_SWIFTLINT_PLUGIN, "SwiftLint")}),
)
# The commands that build a Swift package, and so run its build tool plugins.
_BUILDS = (("swift", "build"), ("swift", "test"), ("xcodebuild",))


def _swiftlint(command: Command, facts: Facts) -> Run | None:
    """`swiftlint` (or `swiftlint lint`), which reports what it finds unless told to fix it, or a build that runs its
    build tool plugin."""
    argv = resolved(command)
    if starts_with(argv, ("swiftlint",)):
        fixes = has_option(argv, "--fix", "--autocorrect") or argv[1:2] in (("--fix",), ("autocorrect",))
        return None if fixes else analysed()
    builds = starts_with(argv, *_BUILDS) is not None
    read = facts.where(Setting, tool="SwiftPM", key="plugin", value="SwiftLint")
    return analysed(read=read) if builds and read else None


SWIFTLINT_TOOL = analyzer(
    name="SwiftLint",
    languages=SWIFT_ONLY,
    how="swiftlint --strict (or the SwiftLint build tool plugin)",
    analyses=_swiftlint,
    rules=defined_by(files=("SwiftLint",)),
    reads=("SwiftLint plugin",),
)
_BODY_LENGTH = "function_body_length"


def _body_length(facts: Facts, *, on: bool) -> list[Setting]:
    """The SwiftLint settings that turn function_body_length on (its thresholds, or `only_rules` naming it), or off
    (`disabled_rules` naming it, or `only_rules` leaving it out)."""
    found = []
    for setting in facts.settings("SwiftLint"):
        names = setting.value if isinstance(setting.value, tuple) else ()
        if setting.key == "only_rules":
            found += [setting] if (_BODY_LENGTH in names) == on else []
        elif setting.key == "disabled_rules" and _BODY_LENGTH in names:
            found += [] if on else [setting]
        elif setting.key == _BODY_LENGTH or setting.key.startswith(f"{_BODY_LENGTH}."):
            found += [setting] if on else []
    return found


# function_body_length is on by default.
BODY_LENGTH = limiter(
    name="SwiftLint's function_body_length",
    languages=SWIFT_ONLY,
    how="swiftlint --strict",
    runs=_swiftlint,
    rule=Rule(
        describe=f"{_BODY_LENGTH} on in {SWIFTLINT_CONFIG}",
        enabled=lambda facts: _body_length(facts, on=True),
        disabled=lambda facts: _body_length(facts, on=False),
        default=True,
    ),
    reads=("SwiftLint plugin", "SwiftLint"),
)
FUNCTION_LENGTH_LIMITERS = (BODY_LENGTH, *function_length_limiters(SWIFT_ONLY))
SWIFTLINT_ACTION = Action(name="norio-nomura/action-swiftlint", runs=lambda _inputs: (("swiftlint",),))

# osv-scanner reads Package.resolved; Swift has no audit tool of its own.
# osv-scanner audits the packages Package.resolved pins.
AUDITORS = multi_ecosystem_audits(SWIFT_ONLY)
# Swift has no security lints of its own here: CodeQL, GitLab SAST or semgrep scan it.
SECURITY_SCANNERS = multi_language_scanners(SWIFT_ONLY)

PACKAGE_DEPENDENCY = re.compile(r"\.package\s*\(")
EXECUTABLE = re.compile(r"\.executable(?:Target)?\s*\(")


PACKAGE_SWIFT_DEPENDENCIES = manifest_reader(
    name="SwiftPM dependencies",
    manager="SwiftPM",
    files=(PACKAGE_SWIFT,),
    declares=lambda _path, text: bool(PACKAGE_DEPENDENCY.search(text)),
    application=lambda _path, text: bool(EXECUTABLE.search(text)),
)
# An Xcode project builds an app.
XCODE_APPLICATIONS = manifest_reader(
    name="Xcode applications",
    manager="SwiftPM",
    files=("project.pbxproj",),
    declares=lambda _path, _text: False,
    application=lambda path, _text: ".xcodeproj/" in path,
)
PACKAGE_RESOLVED = lockfile_reader(manager="SwiftPM", files=("Package.resolved",))
# An app (an Xcode project, or a package with an executable) pins its packages; a library's users resolve them.
SWIFTPM_PACKAGES = PackageManager(
    name="SwiftPM",
    languages=SWIFT_ONLY,
    lock=Lock.APPLICATIONS,
    applications_by_default=False,
    lock_hint="commit Package.resolved, so the application is built with the package versions it was tested with",
)

SWIFT_TOOLCHAINS = versions_axis("Swift toolchain", SWIFT_LANGUAGE, SWIFT_ONLY, compiled=True)

SWIFT = Ecosystem(
    label=SWIFT_LANGUAGE,
    languages=SWIFT_ONLY,
    build_systems=(SWIFTPM, XCODE),
    source_suffixes={".swift": SWIFT_LANGUAGE},
    toolchain=toolchain_patterns(
        SWIFT_LANGUAGE,
        inputs=("swift-version",),
        images=("swift",),
        more=(r"\bxcode-version\W+(\d+(?:\.\d+)*|latest(?:-stable)?)", r"\bXcode_(\d+(?:\.\d+)*)\.app\b"),
        commands=r"\bswift\s+(?:build|test|run|package)\b|\bxcodebuild\b",
        setup=("swift",),
    ),
)
