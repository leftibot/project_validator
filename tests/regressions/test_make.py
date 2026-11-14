"""Expected failures for the task-runner reading gaps the corpus audit found: Make variables and makefile
reading, tox and hatch environments, `php` as a launcher, `deno task` options, Maven and Gradle build settings.

Each test asserts the behaviour the upstream issue asks for; it fails until the bug is fixed, when its decorator goes.
"""

from __future__ import annotations

import json
import unittest

from project_validator.core import Status
from project_validator.facts import Command, Facts, Unknown
from tests.support import GITHUB_WORKFLOW, checks_named, github_job, make_context, run_in_layout, temp_project

COMPILER_WARNINGS, STATIC_ANALYSIS, TESTS_RUN, WARNINGS_AS_ERRORS = checks_named(
    "compiler-warnings", "static-analysis", "tests-run", "warnings-as-errors"
)
CI = "ubuntu-latest"


def _facts(files: dict[str, str]) -> Facts:
    with temp_project(files) as root:
        return make_context(root).facts


def _expanded(files: dict[str, str]) -> list[tuple[str, ...]]:
    """The commands CI's commands run in turn (through a makefile, a task runner, a launcher)."""
    return [command.argv for command in _facts(files).of(Command) if command.via]


def _unknowns(files: dict[str, str]) -> list[tuple[str, str]]:
    return [(unknown.subject, unknown.reason) for unknown in _facts(files).of(Unknown)]


def _make(makefile: str, *lines: str, **files: str) -> dict[str, str]:
    """A project whose `Makefile` is `makefile`, with `files`, and a CI job that runs `lines`."""
    return {"Makefile": makefile, **files, **github_job(CI, *lines)}


class MakeVariableTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #197: Make variables in recipes are kept literal, never expanded
    def test_assignments_and_command_line_overrides_are_expanded_into_recipes(self) -> None:
        """`GO ?= go` then `$(GO) test` runs `go test`; `make run FLAGS=-race` fills `$(FLAGS)` (gin, protovalidate,
        golang-migrate, swift-composable-architecture, dune)."""
        cases = {
            "?=": (_make("GO ?= go\ntest:\n\t$(GO) test -race ./...\n", "make test"), ("go", "test", "-race", "./...")),
            ":=": (
                _make("BIN := ./_boot/dune.exe\ntest:\n\t$(BIN) runtest\n", "make test"),
                ("./_boot/dune.exe", "runtest"),
            ),
            "=": (_make("CMD = xcodebuild $(ARG)\nt:\n\t$(CMD)\n", "make ARG=test t"), ("xcodebuild", "test")),
            "override": (
                _make("test:\n\tmake run FLAGS='-race -cover'\nrun:\n\tgo test $(FLAGS) ./...\n", "make test"),
                ("go", "test", "-race", "-cover", "./..."),
            ),
        }
        for name, (files, expected) in cases.items():
            with self.subTest(assignment=name):
                self.assertIn(expected, _expanded(files))

    @unittest.expectedFailure  # upstream #197: a recipe whose program is an undefined variable is silently kept
    def test_a_program_that_is_an_unknown_variable_is_reported_unknown(self) -> None:
        """`$(BUF) breaking` with no value for BUF the reader can apply is an Unknown, not a command called `$(BUF)`
        (opentelemetry-proto, swiper's `$(EMACS)` through `EMACS_BATCH`)."""
        files = _make("check:\n\t$(BUF) breaking --against .git#branch=main\n", "make check")
        self.assertNotIn(("$(BUF)", "breaking", "--against", ".git#branch=main"), _expanded(files))
        self.assertTrue(any("BUF" in reason for _, reason in _unknowns(files)), _unknowns(files))


class MakefileReadingTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #198: rule lines with a trailing comment are not rules
    def test_a_rule_with_a_trailing_comment_is_read(self) -> None:
        """`lint: deps ## Lint the spec` is a rule (the self-documenting Makefile idiom: digitalocean/openapi,
        jupyter/docker-stacks)."""
        files = _make("lint: deps ## Lint the OpenAPI spec\n\tspectral lint api.yaml\ndeps:\n", "make lint")
        self.assertEqual(_expanded(files), [("spectral", "lint", "api.yaml")])

    @unittest.expectedFailure  # upstream #198: included makefiles are not followed, missing targets are silent
    def test_included_makefiles_are_followed_and_a_missing_target_is_unknown(self) -> None:
        """`include other.mk` brings its rules (cowboy's erlang.mk, koreader); a goal no rule defines is an Unknown."""
        included = _make("include other.mk\n", "make check", **{"other.mk": "check:\n\trebar3 dialyzer\n"})
        with self.subTest(case="include"):
            self.assertEqual(_expanded(included), [("rebar3", "dialyzer")])
        with self.subTest(case="missing target"):
            self.assertTrue(any("dialyze" in subject for subject, _ in _unknowns(_make("all:\n", "make dialyze"))))

    @unittest.expectedFailure  # upstream #198: pattern rules (`%:`, `lint-%:`) are not matched to goals
    def test_pattern_rules_match_the_goals_they_cover(self) -> None:
        """`make html` through sphinx-quickstart's `%:` rule runs `sphinx-build -M html` (python/devguide);
        `make lint-full` through `lint-%:` runs clippy (clap-rs/clap)."""
        cases = {
            "%": (_make("%: Makefile\n\tsphinx-build -M $@ . _build\n", "make html"), ("sphinx-build", "-M", "html")),
            "lint-%": (_make("lint-%:\n\tcargo clippy -- -D warnings\n", "make lint-full"), ("cargo", "clippy")),
        }
        for name, (files, prefix) in cases.items():
            with self.subTest(rule=name):
                self.assertTrue(any(argv[: len(prefix)] == prefix for argv in _expanded(files)), _expanded(files))

    @unittest.expectedFailure  # upstream #198: make after an in-source `cmake .` has "no makefile where make runs"
    def test_make_after_an_in_source_cmake_configure_runs_cmake_targets(self) -> None:
        """After `cmake .`, `make coverage` runs the `coverage` custom target's command (uber/h3)."""
        files = {
            "CMakeLists.txt": "cmake_minimum_required(VERSION 3.21)\nproject(p LANGUAGES C)\n"
            "add_custom_target(coverage COMMAND lcov --capture)\n",
            "src/a.c": "",
            **github_job(CI, "cmake -DENABLE_COVERAGE=ON .", "make", "make coverage"),
        }
        self.assertNotIn(("the makefile", "none is found where make runs"), _unknowns(files))
        self.assertIn(("lcov", "--capture"), _expanded(files))


HATCH_PYPROJECT = '[tool.hatch.envs.lint.scripts]\ncheck = "ruff check ."\n'


def _tox_project(tox_ini: str, job: dict[str, object]) -> dict[str, str]:
    """A project with `tox_ini` and a CI workflow whose one job is `job`."""
    return {"tox.ini": tox_ini, GITHUB_WORKFLOW: json.dumps({"jobs": {"build": {"runs-on": CI, **job}}})}


class PythonTaskRunnerTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #199: `tox -e env -- posargs` runs nothing: `--` is read as a subcommand
    def test_an_env_run_with_positional_arguments_runs_its_commands(self) -> None:
        """`tox -e winpy -- -n 2 test` runs `[testenv]`'s pytest, the posargs after `--` notwithstanding (sqlfluff's
        Windows job); without the `--` part the same env is expanded."""
        tox_ini = "[tox]\nenvlist = py312, winpy\n[testenv]\ncommands = pytest {posargs}\n"
        for line in ("tox -e winpy -- -n 2 test", "python -m tox -e winpy -- -n 2 test"):
            with self.subTest(line=line):
                found = _expanded(_tox_project(tox_ini, {"steps": [{"run": line}]}))
                self.assertTrue(any(argv[:1] == ("pytest",) for argv in found), found)

    @unittest.expectedFailure  # upstream #199: TOX_ENV in the job's environment does not select the env
    def test_tox_env_selects_the_environment_a_bare_tox_runs(self) -> None:
        """`tox run` with `TOX_ENV: py311` runs only py311's commands, not `docs` (pallets/flask)."""
        tox_ini = (
            "[tox]\nenv_list = py311, docs\n[testenv]\ncommands = pytest\n"
            "[testenv:docs]\ncommands = sphinx-build -W docs\n"
        )
        job: dict[str, object] = {"env": {"TOX_ENV": "py311"}, "steps": [{"run": "tox run"}]}
        found = _expanded(_tox_project(tox_ini, job))
        self.assertIn(("pytest",), found)
        self.assertNotIn(("sphinx-build", "-W", "docs"), found)

    @unittest.expectedFailure  # upstream #199: `hatch run env:script` leaves `env:script` as the program
    def test_hatch_run_resolves_the_environment_script(self) -> None:
        """`hatch run lint:check` runs the script of `[tool.hatch.envs.lint.scripts]` (mkdocs)."""
        files = {"pyproject.toml": HATCH_PYPROJECT, **github_job(CI, "hatch run lint:check")}
        self.assertIn(("ruff", "check", "."), _expanded(files))


PHP_TEST = {"tests/AppTest.php": "<?php\nfinal class AppTest extends \\PHPUnit\\Framework\\TestCase {}\n"}
PHP_SCRIPTS = {"composer.json": json.dumps({"scripts": {"phpstan": "@php vendor/bin/phpstan analyse"}})}


class PhpLauncherTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #200: `php <script>` is not a launcher, so the tool run is missed
    def test_php_runs_the_script_that_follows(self) -> None:
        """`php "vendor/bin/phpunit"` runs PHPUnit and `@php vendor/bin/phpstan analyse` runs PHPStan
        (PHP_CodeSniffer, monolog, composer); `simple-phpunit` is PHPUnit too."""
        cases = {
            "php phpunit": (TESTS_RUN, {**PHP_TEST, **github_job(CI, 'php "vendor/bin/phpunit" --no-coverage')}),
            "composer @php phpstan": (
                STATIC_ANALYSIS,
                {**PHP_SCRIPTS, "phpstan.neon.dist": "parameters:\n  level: 8\n", **github_job(CI, "composer phpstan")},
            ),
            "simple-phpunit": (TESTS_RUN, {**PHP_TEST, **github_job(CI, "vendor/bin/simple-phpunit --verbose")}),
        }
        for name, (check, files) in cases.items():
            with self.subTest(case=name):
                result = run_in_layout(self, "Composer PHP", check, files)
                self.assertEqual(result.status, Status.PASS, result)


class DenoTaskTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #201: `deno task --cwd dir task` takes `--cwd` as the task name
    def test_options_before_the_task_name_are_skipped(self) -> None:
        """`deno task --cwd sub --config deno.json build` runs `build` of `sub/deno.json` (denoland/std)."""
        files = {
            "sub/deno.json": '{"tasks": {"build": "wasmbuild --check"}}',
            **github_job(CI, "deno task --cwd sub --config deno.json build"),
        }
        self.assertNotIn(("the task --cwd", "no deno.json defines it"), _unknowns(files))
        self.assertIn(("wasmbuild", "--check"), _expanded(files))


POM_WITH_DEFAULT_GOAL = (
    "<project><build><defaultGoal>verify checkstyle:check</defaultGoal><plugins>"
    "<plugin><artifactId>maven-checkstyle-plugin</artifactId></plugin></plugins></build></project>\n"
)
CONVENTION_PLUGIN = (
    "tasks.withType<JavaCompile>().configureEach {\n"
    '    options.compilerArgs.addAll(listOf("-Xlint:all", "-Werror"))\n}\n'
)


class JvmBuildSettingTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #202: a bare `mvn` runs the POM's <defaultGoal>, which is not read
    def test_a_bare_mvn_runs_the_default_goal(self) -> None:
        """`mvn -B` with `<defaultGoal>verify checkstyle:check</defaultGoal>` runs tests and Checkstyle
        (apache/commons-lang)."""
        files = {
            "pom.xml": POM_WITH_DEFAULT_GOAL,
            "src/test/java/AppTest.java": "import org.junit.jupiter.api.Test;\nclass AppTest { @Test void a() {} }\n",
            **github_job(CI, "mvn -B"),
        }
        for check in (TESTS_RUN, STATIC_ANALYSIS):
            with self.subTest(check=check.name):
                result = run_in_layout(self, "Maven Java", check, files)
                self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #202: compiler flags in Gradle convention plugins are not read
    def test_compiler_flags_in_a_convention_plugin_are_the_build_settings(self) -> None:
        """`-Xlint:all -Werror` set in `buildSrc/.../my.java-conventions.gradle.kts` are the project's warning
        settings (junit-team/junit5's gradle/plugins)."""
        files = {
            # Kotlin's own settings are in the build script, so only Java's come from the convention plugin.
            "build.gradle.kts": 'plugins {\n    kotlin("jvm")\n    id("my.java-conventions")\n}\n'
            "kotlin { compilerOptions { allWarningsAsErrors = true } }\n",
            "buildSrc/src/main/kotlin/my.java-conventions.gradle.kts": CONVENTION_PLUGIN,
            "src/main/java/App.java": "",
            **github_job(CI, "./gradlew build"),
        }
        for check in (COMPILER_WARNINGS, WARNINGS_AS_ERRORS):
            with self.subTest(check=check.name):
                result = run_in_layout(self, "Gradle Kotlin", check, files)
                self.assertEqual(result.status, Status.PASS, result)
