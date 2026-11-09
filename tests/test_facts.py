"""The fact database: the facts CI configuration yields, and how shell scripts are split into commands."""

import json
import unittest

from project_validator.ci.github_actions import EXPRESSION
from project_validator.facts import ActionStep, CiConfiguration, CiJob, Command, Facts, Origin, Unknown, as_dict
from project_validator.facts.build import Applies, CompilerOption
from project_validator.facts.conditions import DIMENSIONS
from project_validator.facts.jobs import Job
from project_validator.facts.shell import ShellCommand, Unsplittable, split_script
from project_validator.facts.tools import ToolRun
from tests.support import GITHUB_WORKFLOW, make_context, temp_project


def _facts(files: dict[str, str]) -> Facts:
    with temp_project(files) as root:
        return make_context(root).facts


def _argvs(facts: Facts) -> list[tuple[str, ...]]:
    return [command.argv for command in facts.of(Command)]


class ShellTests(unittest.TestCase):
    def _split(self, script: str) -> list[tuple[str, ...]]:
        return [found.argv for found in split_script(script) if isinstance(found, ShellCommand)]

    def test_operators_separate_commands_and_continuations_join_lines(self) -> None:
        script = "cmake -S . -B build && cmake --build build \\\n  --config Release\nctest || exit 1; echo ok | tee x\n"
        self.assertEqual(
            self._split(script),
            [
                ("cmake", "-S", ".", "-B", "build"),
                ("cmake", "--build", "build", "--config", "Release"),
                ("ctest",),
                ("exit", "1"),
                ("echo", "ok"),
                ("tee", "x"),
            ],
        )

    def test_quotes_comments_and_redirections(self) -> None:
        script = (
            "gcovr --gcov-executable 'llvm-cov gcov' -DX=\"a b\" # coverage\nmake 2>&1 > log.txt\n# only a comment\n"
        )
        self.assertEqual(self._split(script), [("gcovr", "--gcov-executable", "llvm-cov gcov", "-DX=a b"), ("make",)])

    def test_assignments_are_the_commands_environment(self) -> None:
        [found] = split_script("CC=gcc-14 CXX=g++-14 cmake -S .")
        self.assertEqual(
            found,
            ShellCommand(
                argv=("cmake", "-S", "."),
                env=(("CC", "gcc-14"), ("CXX", "g++-14")),
                line="CC=gcc-14 CXX=g++-14 cmake -S .",
            ),
        )

    def test_compound_command_keywords_are_not_commands(self) -> None:
        script = "if [ -f x ]; then ctest; fi\nfor f in a b; do echo $f; done\n"
        self.assertEqual(
            self._split(script), [("[", "-f", "x", "]"), ("ctest",), ("for", "f", "in", "a", "b"), ("echo", "$f")]
        )

    def test_opaque_text_keeps_its_quotes(self) -> None:
        [found] = split_script("""echo "a ${{ x == 'y' }}" '${{ z }}'""", EXPRESSION)
        self.assertEqual(found, ShellCommand(argv=("echo", "a ${{ x == 'y' }}", "${{ z }}"), env=(), line=found.line))
        [unsplittable] = split_script("echo ${{ 'a' }} 'open", EXPRESSION)
        self.assertEqual(unsplittable, Unsplittable(line="echo ${{ 'a' }} 'open", reason="No closing quotation"))

    def test_command_substitutions_run_before_their_command(self) -> None:
        for script, expected in (
            ('test -z "$(gofmt -l .)"', [("gofmt", "-l", "."), ("test", "-z", "$(gofmt -l .)")]),
            ("echo `git rev-parse HEAD` x", [("git", "rev-parse", "HEAD"), ("echo", "`git rev-parse HEAD`", "x")]),
            ("cd $(dirname $(pwd)) && ls", [("pwd",), ("dirname", "$(pwd)"), ("cd", "$(dirname $(pwd))"), ("ls",)]),
            ("echo $((1 + 2)) '$(not run)'", [("echo", "$", "((", "1", "+", "2", "))", "$(not run)")]),
            ('echo "\\$(not run)" \\`x', [("echo", "\\$(not run)", "`x")]),
            ("echo $(unclosed", [("echo", "$", "unclosed")]),
            ("echo `unclosed", [("echo", "`unclosed")]),
        ):
            with self.subTest(script=script):
                self.assertEqual(self._split(script), expected)

    def test_quoted_and_escaped_operator_characters_are_text(self) -> None:
        for script, expected in (
            ("awk -F '|' '{print $1}' f", [("awk", "-F", "|", "{print $1}", "f")]),
            ("find . -exec rm {} ';' && ls", [("find", ".", "-exec", "rm", "{}", ";"), ("ls",)]),
            ("find . -exec rm {} \\; | wc", [("find", ".", "-exec", "rm", "{}", ";"), ("wc",)]),
            ('echo "a > b" "x\\"|y" > out', [("echo", "a > b", 'x"|y')]),
            ("X='a;b' run", [("run",)]),
        ):
            with self.subTest(script=script):
                self.assertEqual(self._split(script), expected)

    def test_a_quoted_string_may_span_lines(self) -> None:
        script = 'gh api x --jq ".runs[]\n | .id" | xargs echo\nls\n'
        self.assertEqual(
            self._split(script), [("gh", "api", "x", "--jq", ".runs[]\n | .id"), ("xargs", "echo"), ("ls",)]
        )

    def test_an_unbalanced_quote_cannot_be_split(self) -> None:
        self.assertEqual(
            list(split_script('echo "open')), [Unsplittable(line='echo "open', reason="No closing quotation")]
        )


class ShellDepthTests(unittest.TestCase):
    def test_deeply_nested_substitutions_are_unsplittable(self) -> None:
        found = list(split_script("echo " + "$(" * 5000 + "x" + ")" * 5000))
        self.assertEqual([type(item) for item in found], [Unsplittable])
        assert isinstance(found[0], Unsplittable)  # noqa: S101
        self.assertEqual(found[0].reason, "nested too deeply to split")


class ShellLineDepthTests(unittest.TestCase):
    def test_only_the_line_nested_too_deeply_is_lost(self) -> None:
        deep = "echo " + "$(" * 2000 + "x" + ")" * 2000
        found = list(split_script(f"cmake --build build\nctest\n{deep}\n"))
        self.assertEqual(
            [item.argv if isinstance(item, ShellCommand) else item.line for item in found],
            [("cmake", "--build", "build"), ("ctest",), deep],
        )


class GitHubActionsFactTests(unittest.TestCase):
    WORKFLOW = """\
        env:
          GLOBAL: "1"
        jobs:
          test:
            runs-on: ${{ matrix.os }}
            env:
              CC: ${{ matrix.cc }}
            strategy:
              matrix:
                os: [ubuntu-latest, windows-latest]
                cc: [gcc]
            steps:
              - uses: actions/checkout@v4
              - uses: aminya/setup-cpp@v1
                with:
                  compiler: ${{ matrix.cc }}
              - name: test
                if: runner.os != 'Windows'
                working-directory: build
                run: |
                  cmake -S .. -B . && ctest -C Debug
          container-job:
            runs-on: ubuntu-latest
            container: python:3.14
            steps:
              - run: python -m unittest
          computed:
            strategy:
              matrix: ${{ fromJSON(needs.setup.outputs.matrix) }}
            runs-on: ubuntu-latest
          reuse:
            uses: org/repo/.github/workflows/build.yml@v1
        """

    def setUp(self) -> None:
        self.facts = _facts({GITHUB_WORKFLOW: self.WORKFLOW})

    def test_each_matrix_combination_is_a_job(self) -> None:
        jobs = {job.id: job for job in self.facts.of(CiJob)}
        self.assertEqual(
            list(jobs),
            [
                f"{GITHUB_WORKFLOW}:test[0]",
                f"{GITHUB_WORKFLOW}:test[1]",
                f"{GITHUB_WORKFLOW}:container-job",
                f"{GITHUB_WORKFLOW}:computed",
            ],
        )
        first = jobs[f"{GITHUB_WORKFLOW}:test[0]"]
        self.assertEqual(
            (first.os, dict(first.matrix), dict(first.env)),
            ("linux", {"os": "ubuntu-latest", "cc": "gcc"}, {"GLOBAL": "1", "CC": "gcc"}),
        )
        self.assertEqual(jobs[f"{GITHUB_WORKFLOW}:test[1]"].os, "windows")
        self.assertEqual(jobs[f"{GITHUB_WORKFLOW}:container-job"].image, "python:3.14")
        computed = jobs[f"{GITHUB_WORKFLOW}:computed"]
        # Its runner is still read; its steps run with their matrix values unknown.
        self.assertEqual((computed.name, computed.os), ("computed (matrix computed by an expression)", "linux"))

    def test_commands_carry_their_step_and_environment(self) -> None:
        commands = [command for command in self.facts.of(Command) if command.job.endswith("test[0]")]
        self.assertEqual(
            [command.argv for command in commands], [("cmake", "-S", "..", "-B", "."), ("ctest", "-C", "Debug")]
        )
        self.assertEqual(
            (str(commands[0].origin), commands[0].directory, commands[0].condition, commands[0].env["CC"]),
            (f"{GITHUB_WORKFLOW}:jobs.test.steps[2].run", "build", None, "gcc"),
        )

    def test_a_step_runs_only_where_its_condition_holds(self) -> None:
        # The test step's `if: runner.os != 'Windows'` holds on Linux, so it has no condition left there; on
        # Windows it does not run at all.
        windows = [command for command in self.facts.of(Command) if command.job.endswith("test[1]")]
        self.assertEqual(windows, [])

    def test_actions_carry_their_inputs(self) -> None:
        steps = [step for step in self.facts.of(ActionStep) if step.job.endswith("test[1]")]
        self.assertEqual([step.uses for step in steps], ["actions/checkout@v4", "aminya/setup-cpp@v1"])
        self.assertEqual(dict(steps[1].inputs), {"compiler": "gcc"})

    def test_expressions_are_evaluated_by_github_before_the_shell_splits_the_line(self) -> None:
        workflow = """\
            jobs:
              build:
                strategy:
                  matrix:
                    type: [Debug]
                    include:
                      - type: Release
                        generator: TBZ2
                runs-on: ubuntu-latest
                steps:
                  - run: >-
                      cmake -DCOVERAGE=${{ matrix.type == 'Debug' }} -DSHA=${{ github.sha }}
                      && cpack -G ${{ matrix.generator }}
            """
        commands = _facts({GITHUB_WORKFLOW: workflow}).of(Command)
        self.assertEqual(
            [command.argv for command in commands],
            [
                ("cmake", "-DCOVERAGE=true", "-DSHA=${{ github.sha }}"),  # an unknown value stays as written
                ("cpack", "-G"),  # a key the combination lacks is empty
                ("cmake", "-DCOVERAGE=false", "-DSHA=${{ github.sha }}"),
                ("cpack", "-G", "TBZ2"),
            ],
        )

    def test_what_cannot_be_read_is_unknown(self) -> None:
        unknown = {fact.subject: fact.reason for fact in self.facts.of(Unknown)}
        self.assertEqual(
            unknown,
            {
                "the matrix of job computed": "it is computed by an expression",
                "job reuse": (
                    "it calls the reusable workflow org/repo/.github/workflows/build.yml@v1, which is not read"
                ),
            },
        )


class GitLabFactTests(unittest.TestCase):
    PIPELINE = """\
        image: gcc:14
        variables:
          GLOBAL: "1"
        default:
          before_script:
            - apt-get update
        build:
          variables:
            BUILD_TYPE: Release
          parallel:
            matrix:
              - CXX: [g++, clang++]
          script:
            - cmake -S . -B build -DCMAKE_CXX_COMPILER=$CXX
        mac:
          tags: [macos]
          extends: .template
          script: ctest
        .template:
          script: never
        """

    def setUp(self) -> None:
        self.facts = _facts({".gitlab-ci.yml": self.PIPELINE})

    def test_parallel_matrix_combinations_are_jobs_with_variables(self) -> None:
        jobs = self.facts.of(CiJob)
        self.assertEqual(
            [job.id for job in jobs], [".gitlab-ci.yml:build[0]", ".gitlab-ci.yml:build[1]", ".gitlab-ci.yml:mac"]
        )
        self.assertEqual(dict(jobs[1].env), {"GLOBAL": "1", "BUILD_TYPE": "Release", "CXX": "clang++"})
        # Only Linux runners run jobs in Docker images.
        self.assertEqual(
            [(job.os, job.image) for job in jobs], [("linux", "gcc:14"), ("linux", "gcc:14"), ("macos", None)]
        )

    def test_default_scripts_run_before_the_jobs_own(self) -> None:
        self.assertEqual(
            _argvs(self.facts),
            [
                ("apt-get", "update"),
                ("cmake", "-S", ".", "-B", "build", "-DCMAKE_CXX_COMPILER=g++"),
                ("apt-get", "update"),
                ("cmake", "-S", ".", "-B", "build", "-DCMAKE_CXX_COMPILER=clang++"),
                ("apt-get", "update"),
                ("ctest",),
            ],
        )
        self.assertEqual(str(self.facts.of(Command)[0].origin), ".gitlab-ci.yml:default.before_script[0]")

    def test_extends_merges_the_templates_first(self) -> None:
        self.assertEqual(self.facts.of(Unknown), ())
        mac = [command.argv for command in self.facts.where(Command, job=".gitlab-ci.yml:mac")]
        self.assertEqual(mac, [("apt-get", "update"), ("ctest",)])

    def test_local_includes_references_and_missing_templates(self) -> None:
        pipeline = (
            "include:\n  - /ci/build.yml\n  - local: ci/test.yml\n  - project: other/repo\n    file: x.yml\n"
            "lint:\n  script:\n    - !reference [.setup, script]\n    - ruff check\n"
            "orphan:\n  extends: .missing\n  script: x\n"
        )
        facts = _facts(
            {
                ".gitlab-ci.yml": pipeline,
                "ci/build.yml": ".setup:\n  script: [uv sync]\nbuild:\n  script: cmake --build b\n",
                "ci/test.yml": "test:\n  extends: build\n  script: ctest --test-dir b\n",
            }
        )
        commands = {job: [c.argv for c in facts.where(Command, job=job)] for job in {c.job for c in facts.of(Command)}}
        self.assertEqual(commands[".gitlab-ci.yml:lint"], [("uv", "sync"), ("ruff", "check")])
        self.assertEqual(commands["ci/build.yml:build"], [("cmake", "--build", "b")])
        self.assertEqual(commands["ci/test.yml:test"], [("ctest", "--test-dir", "b")])
        self.assertEqual(
            [(unknown.subject, unknown.hides) for unknown in facts.of(Unknown)],
            [('the include {"project": "other/repo", "file": "x.yml"}', "jobs"), ("job orphan", "commands")],
        )

    def test_windows_runners_run_powershell(self) -> None:
        script = 'cmake --build build `\n  --config Release\n$root = "C:\\work\\"'
        facts = _facts({".gitlab-ci.yml": json.dumps({"win": {"tags": ["windows"], "script": [script]}})})
        self.assertEqual(facts.of(Unknown), ())
        self.assertIn(("cmake", "--build", "build", "--config", "Release"), [c.argv for c in facts.of(Command)])


class OtherProviderFactTests(unittest.TestCase):
    def test_unparsed_configuration_is_a_heuristic_job_with_unknown_commands(self) -> None:
        facts = _facts({".travis.yml": "script: ctest -C Debug\n"})
        [job] = facts.of(CiJob)
        self.assertTrue(job.heuristic)
        # Each line that could be a command is taken for one.
        self.assertEqual(_argvs(facts), [("ctest", "-C", "Debug")])
        self.assertEqual(facts.of(Unknown)[0].reason, "Travis CI is scanned heuristically")

    def test_malformed_documents_yield_what_they_can(self) -> None:
        workflow = "jobs:\n  odd: text\n  build:\n    runs-on: ubuntu-latest\n    steps: [text, {run: ctest}]\n"
        facts = _facts({GITHUB_WORKFLOW: workflow, ".github/workflows/list.yml": "- a\n", ".gitlab-ci.yml": "- a\n"})
        self.assertEqual(_argvs(facts), [("ctest",)])
        # ctest is a test runner, so its command is a run too; the job builds, on Linux.
        found = [type(fact) for fact in facts if not isinstance(fact, CiConfiguration)]
        self.assertEqual(found, [CiJob, Command, Job, ToolRun])

    def test_invalid_yaml_is_unknown(self) -> None:
        facts = _facts({GITHUB_WORKFLOW: "jobs: [\n"})
        self.assertTrue(facts.of(CiJob)[0].heuristic)
        self.assertIn("invalid YAML", facts.of(Unknown)[0].reason)

    def test_a_line_that_cannot_be_split_is_unknown(self) -> None:
        facts = _facts({".gitlab-ci.yml": 'build:\n  script:\n    - echo "open\n'})
        self.assertEqual(facts.of(Unknown)[0].subject, "the command 'echo \"open'")


def _option(applies: Applies) -> CompilerOption:
    return CompilerOption(origin=Origin(path="CMakeLists.txt"), build_system="CMake", option="-Wall", applies=applies)


class SerialisationTests(unittest.TestCase):
    def test_a_fact_is_its_kind_and_fields(self) -> None:
        command = Command(
            origin=Origin(path="ci.yml", at=("jobs", "a", "steps", 0, "run")),
            job="ci.yml:a",
            argv=("make",),
            line="make",
        )
        self.assertEqual(
            as_dict(command),
            {
                "kind": "Command",
                "origin": "ci.yml:jobs.a.steps[0].run",
                "job": "ci.yml:a",
                "argv": ["make"],
                "line": "make",
                "env": {},
                "directory": None,
                "condition": None,
                "via": [],
            },
        )
        self.assertEqual(str(Origin(path="ci.yml")), "ci.yml")
        json.dumps(Facts((command,)).as_dicts())

    def test_an_open_set_of_values_is_written_as_what_it_leaves_out(self) -> None:
        """`if(NOT MSVC)` holds for every compiler, named or not, but MSVC: written as such, adding a compiler
        changes no other project's facts. A closed set names its members."""
        not_msvc = frozenset(DIMENSIONS["compilers"]) - {"msvc"}
        applies = Applies(compilers=not_msvc, languages=frozenset({"C++", "C"}))
        self.assertEqual(as_dict(_option(applies))["applies"], {"compilers": "all but msvc", "languages": ["C", "C++"]})
        gcc_or_clang = Applies(compilers=frozenset({"gcc", "clang"}), requires=frozenset({"ENABLE_X"}))
        self.assertEqual(
            as_dict(_option(gcc_or_clang))["applies"], {"compilers": ["clang", "gcc"], "requires": ["ENABLE_X"]}
        )
        self.assertEqual(as_dict(_option(Applies()))["applies"], {})
