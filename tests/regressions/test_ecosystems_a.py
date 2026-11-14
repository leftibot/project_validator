"""Expected failures for the ecosystem gaps the corpus audit found (upstream #256 to #264): R, Ruby, Dart, Go,
Docker, Ansible and Kubernetes, Terraform, Typst and the BEAM. Each test asserts the behaviour the issue asks for; it
starts passing (an "unexpected success") when the gap is closed, and its decorator goes."""

from __future__ import annotations

import json
import unittest
from collections.abc import Mapping

from project_validator.core import Check, Status
from project_validator.facts import Command, Facts, Unknown
from tests.support import (
    GITHUB_WORKFLOW,
    checks_named,
    github_action,
    github_job,
    github_steps,
    make_context,
    run_in_layout,
    temp_project,
)

CODE_FORMATTING, COMPILER_WARNINGS, PLATFORM_MATRIX, SANITIZERS, SECURITY_SCANNING, STATIC_ANALYSIS, TESTS_RUN = (
    checks_named(
        "code-formatting",
        "compiler-warnings",
        "platform-matrix",
        "sanitizers",
        "security-scanning",
        "static-analysis",
        "tests-run",
    )
)
CI = "ubuntu-latest"
# A case: the layout to judge in, the check, and the files added to the layout's.
Case = tuple[str, Check, dict[str, str]]


def _ci(*lines: str) -> dict[str, str]:
    return github_job(CI, *lines)


def _workflow(document: dict[str, object]) -> dict[str, str]:
    """A GitHub workflow that is `document` as a whole (its triggers, its jobs' `if:` and `uses:`)."""
    return {GITHUB_WORKFLOW: json.dumps(document)}


def _gitlab(*lines: str, image: str | None = None) -> dict[str, str]:
    """A GitLab CI pipeline with one job that runs `lines`, in the container `image` if given."""
    job: dict[str, object] = {"script": list(lines)}
    if image is not None:
        job["image"] = image
    return {".gitlab-ci.yml": json.dumps({"check": job})}


def _facts(files: dict[str, str]) -> Facts:
    with temp_project(files) as root:
        return make_context(root).facts


def _all_pass(test: unittest.TestCase, cases: Mapping[str, Case]) -> None:
    """Each of `cases` passes its check in its layout, as a sub-test."""
    for name, (layout, check, files) in cases.items():
        with test.subTest(case=name):
            result = run_in_layout(test, layout, check, files)
            test.assertEqual(result.status, Status.PASS, result)


# --- R (#256) --------------------------------------------------------------------------------------------------------

R_PACKAGE = "R package"
CHECK_R_PACKAGE = github_action("r-lib/actions/check-r-package@v2")
# r-lib's pr-commands.yaml: styler runs only when a maintainer comments `/style` on a pull request.
STYLE_ON_COMMENT: dict[str, object] = {
    "on": {"issue_comment": {"types": ["created"]}},
    "jobs": {
        "style": {
            "runs-on": CI,
            "if": "${{ github.event.issue.pull_request && startsWith(github.event.comment.body, '/style') }}",
            "steps": [{"run": "Rscript -e 'styler::style_pkg()'"}, {"run": "git commit -am 'Style'"}],
        }
    },
}


class RTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #256: tests/*.R, sanitizer images and issue_comment styler jobs unread
    def test_check_runs_tests_r_sanitizer_images_sanitize_and_a_comment_job_enforces_nothing(self) -> None:
        """`R CMD check` runs every `tests/*.R` script, so they are tests (data.table); a job in a `rocker/r-devel-san`
        image runs under ASan and UBSan (data.table); styler in an `issue_comment` job gates no push (testthat)."""
        _all_pass(
            self,
            {
                "tests/*.R": (
                    R_PACKAGE,
                    TESTS_RUN,
                    {"tests/main.R": "stopifnot(total(c(1, 2)) == 3)\n", **CHECK_R_PACKAGE},
                ),
                "sanitizer image": (
                    R_PACKAGE,
                    SANITIZERS,
                    {
                        "src/shop.c": "",
                        **_gitlab("R CMD build .", "R CMD check shop_0.1.0.tar.gz", image="rocker/r-devel-san"),
                    },
                ),
            },
        )
        with self.subTest(case="styler on issue_comment"):
            result = run_in_layout(self, R_PACKAGE, CODE_FORMATTING, _workflow(STYLE_ON_COMMENT))
            self.assertNotEqual(result.status, Status.PASS, result)


# --- Ruby (#257) -----------------------------------------------------------------------------------------------------

BUNDLER = "Bundler Ruby"
MINITEST = {
    "test/test_shop.rb": 'require "minitest/autorun"\n\nclass ShopTest < Minitest::Test\n'
    "  def test_adds = assert_equal(3, 1 + 2)\nend\n"
}
# fluentd's Rakefile: the test task runs Ruby with warnings on.
WARNING_TASK = {"Rakefile": 'require "rake/testtask"\n\nRake::TestTask.new(:test) do |t|\n  t.warning = true\nend\n'}
# puma's test/runner: the project's own Minitest runner script.
RUNNER = {
    "test/runner": '#!/usr/bin/env ruby\nrequire "minitest/autorun"\n'
    'Dir["test/test_*.rb"].each { |f| require_relative f }\n'
}
FEATURE = {"features/shop.feature": "Feature: totals\n  Scenario: adds\n    Then the total of 1 and 2 is 3\n"}


class RubyTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #257: Rakefile warning = true, Cucumber features, runner scripts unread
    def test_rakefile_warnings_count_and_cucumber_runner_scripts_and_ruby_run_the_tests(self) -> None:
        """A `Rake::TestTask`'s `warning = true` is the Ruby warning setting when CI runs `rake test` (fluentd);
        Cucumber features are tests (rspec); `test/runner` (puma) and `ruby test/test_x.rb` (fzf) run Minitest."""
        _all_pass(
            self,
            {
                "warning = true": (
                    BUNDLER,
                    COMPILER_WARNINGS,
                    {**WARNING_TASK, **MINITEST, **_ci("bundle exec rake test", "bundle exec rubocop")},
                ),
                "cucumber": (BUNDLER, TESTS_RUN, {**FEATURE, **_ci("bundle exec cucumber")}),
                "test/runner": (BUNDLER, TESTS_RUN, {**RUNNER, **MINITEST, **_ci("test/runner --verbose")}),
                "ruby test/*.rb": (BUNDLER, TESTS_RUN, {**MINITEST, **_ci("ruby test/test_shop.rb --verbose")}),
            },
        )


# --- Dart (#258) -----------------------------------------------------------------------------------------------------

DART_PACKAGE = "Dart package"
FLUTTER_APPLICATION = "Flutter application"
STRICT_MODES = (
    "analyzer:\n  language:\n    strict-casts: true\n    strict-inference: true\n    strict-raw-types: true\n"
)
LINT_OPTIONS = {
    # dart-lang/http: the team lint set, which itself includes lints/recommended.
    "team lints": "include: package:dart_flutter_team_lints/analysis_options.yaml\n" + STRICT_MODES,
    # felangel/bloc's packages: the Dart 3 list form of `include:`.
    "list include": "include:\n  - package:lints/recommended.yaml\n",
    # felangel/bloc's root: no include, the rules spelled out.
    "explicit rules": STRICT_MODES + "linter:\n  rules:\n    - always_declare_return_types\n    - avoid_print\n",
}
INTEGRATION_TEST = {
    "example/integration_test/client_test.dart": "import 'package:flutter_test/flutter_test.dart';\n\n"
    "void main() {\n  testWidgets('gets', (tester) async {});\n}\n"
}
EMULATOR_SCRIPT = github_action(
    "reactivecircus/android-emulator-runner@v2", script="cd example && flutter test integration_test/"
)


class DartTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #258: list-form or explicit lint sets and integration_test unrecognised
    def test_every_include_form_is_a_lint_set_and_integration_tests_are_tests(self) -> None:
        """A lint set is one however it is included (dart-lang/http, bloc); `example/integration_test/*_test.dart`
        run by `flutter test integration_test/`, in an emulator action's `script:` or not, are tests (http)."""
        analysed = {
            name: (
                DART_PACKAGE,
                COMPILER_WARNINGS,
                {"analysis_options.yaml": options, **_ci("dart analyze --fatal-infos")},
            )
            for name, options in LINT_OPTIONS.items()
        }
        tested: dict[str, Case] = {
            "emulator script": (FLUTTER_APPLICATION, TESTS_RUN, {**INTEGRATION_TEST, **EMULATOR_SCRIPT}),
            "flutter test": (
                FLUTTER_APPLICATION,
                TESTS_RUN,
                {**INTEGRATION_TEST, **_ci("cd example && flutter test integration_test/")},
            ),
        }
        _all_pass(self, {**analysed, **tested})


# --- Go (#259) -------------------------------------------------------------------------------------------------------

GO_TEST_FILE = {"app_test.go": 'package app\n\nimport "testing"\n\nfunc TestAdd(t *testing.T) {}\n'}


class GoTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #259: richgo test, a go test output wrapper, is not go test
    def test_richgo_test_is_go_test(self) -> None:
        """`richgo test ./...` is `go test` with coloured output, run directly or through a Makefile target (cobra)."""
        _all_pass(
            self,
            {
                "direct": ("Go module", TESTS_RUN, {**GO_TEST_FILE, **_ci("richgo test -v ./...")}),
                "make richtest": (
                    "Go module",
                    TESTS_RUN,
                    {**GO_TEST_FILE, "Makefile": "richtest:\n\trichgo test -v ./...\n", **_ci("make richtest")},
                ),
            },
        )


# --- Docker (#260) ---------------------------------------------------------------------------------------------------

HADOLINT_HOOK = {
    ".pre-commit-config.yaml": "repos:\n  - repo: https://github.com/hadolint/hadolint\n    rev: v2.12.0\n"
    "    hooks:\n      - id: hadolint-docker\n",
    ".hadolint.yaml": "ignored: [DL3018]\n",
}


class DockerTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #260: the hadolint-docker pre-commit hook id does not match hadolint
    def test_the_hadolint_docker_hook_runs_hadolint(self) -> None:
        """The `hadolint-docker` hook of hadolint's own pre-commit repo runs hadolint on the Dockerfiles, so hadolint
        lints and scans when CI runs pre-commit (jupyter/docker-stacks)."""
        files = {**HADOLINT_HOOK, **_ci("pre-commit run --all-files")}
        with self.subTest(check=STATIC_ANALYSIS.name):
            result = run_in_layout(self, "Dockerfile", STATIC_ANALYSIS, files)
            self.assertEqual((result.status, result.message), (Status.PASS, "hadolint (.hadolint.yaml) runs"))
        _all_pass(self, {SECURITY_SCANNING.name: ("Dockerfile", SECURITY_SCANNING, files)})


# --- Ansible and Kubernetes (#261) -----------------------------------------------------------------------------------

ANSIBLE_PLAYBOOK = "Ansible playbook"
KUBERNETES_MANIFESTS = "Kubernetes manifests"
UNITTESTS = {
    "charts/shop/Chart.yaml": "apiVersion: v2\nname: shop\nversion: 0.1.0\n",
    "charts/shop/unittests/deployment_test.yaml": "suite: deployment\ntests:\n  - it: runs\n    asserts: []\n",
}
# prometheus-community/helm-charts: chart-testing runs helm-unittest on every changed chart.
CT_CONFIG = {"ct.yaml": "additional-commands:\n  - helm unittest --strict --file 'unittests/**/*.yaml' {{ .Path }}\n"}
SCENARIO = {"molecule/default/molecule.yml": "driver:\n  name: docker\nplatforms:\n  - name: debian\n"}
# kubespray: molecule's verify stage runs the scenario's testinfra tests.
VERIFIER = {
    "molecule/default/tests/test_default.py": "def test_docker_runs(host):\n"
    "    assert host.service('docker').is_running\n"
}
COLLECTION = {
    "galaxy.yml": "namespace: shop\nname: web\nversion: 1.0.0\n",
    "antsibull-nox.toml": "[sessions.ansible_test_integration]\n",
    "tests/integration/targets/shop/tasks/main.yml": "- name: Check\n  ansible.builtin.ping:\n",
}
# community.general: the whole CI is antsibull-nox's reusable workflow, driven by the repository's own configuration.
NOX_WORKFLOW: dict[str, object] = {
    "jobs": {"nox": {"uses": "ansible-community/antsibull-nox/.github/workflows/reusable-nox-matrix.yml@main"}}
}


class AnsibleKubernetesTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #261: unittests/ suites, ct.yaml, molecule verifiers, antsibull-nox unread
    def test_helm_unittest_suites_molecule_verifiers_and_antsibull_nox_sessions_are_tests_run(self) -> None:
        """`charts/*/unittests/*_test.yaml` run by chart-testing's `additional-commands` are tests (prometheus
        helm-charts); a molecule scenario's `tests/test_*.py` is run by `molecule test` (kubespray); antsibull-nox's
        sessions run ansible-test (community.general)."""
        _all_pass(
            self,
            {
                "ct additional-commands": (
                    KUBERNETES_MANIFESTS,
                    TESTS_RUN,
                    {**UNITTESTS, **CT_CONFIG, **_ci("ct lint --config ct.yaml")},
                ),
                "unittests directory": (
                    KUBERNETES_MANIFESTS,
                    TESTS_RUN,
                    {**UNITTESTS, **_ci("helm unittest charts/shop")},
                ),
                "molecule verifier": (ANSIBLE_PLAYBOOK, TESTS_RUN, {**SCENARIO, **VERIFIER, **_ci("molecule test")}),
                "antsibull-nox": (ANSIBLE_PLAYBOOK, TESTS_RUN, {**COLLECTION, **_workflow(NOX_WORKFLOW)}),
            },
        )


# --- Terraform (#262) ------------------------------------------------------------------------------------------------

TERRAFORM = "Terraform configuration"
# terraform-aws-modules: the Terraform versions tested are the min and max of `required_version`, from an action.
MIN_MAX_WORKFLOW: dict[str, object] = {
    "jobs": {
        "min": {
            "runs-on": CI,
            "steps": [
                {"id": "minMax", "uses": "clowdhaus/terraform-min-max@v1"},
                {
                    "uses": "hashicorp/setup-terraform@v3",
                    "with": {"terraform_version": "${{ steps.minMax.outputs.minVersion }}"},
                },
                {"run": "terraform validate"},
            ],
        }
    }
}


def _chdir_pipeline(cli: str) -> dict[str, str]:
    """kubespray's GitLab jobs: `-chdir=<dir>` before the subcommand."""
    return _gitlab(
        f'{cli} -chdir="infra" init', f'{cli} -chdir="infra" validate', f"{cli} -chdir=infra fmt -check -diff"
    )


class TerraformTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #262: -chdir= before the subcommand, .tftpl/.tpl, terraform-min-max unread
    def test_chdir_before_the_subcommand_templates_and_min_max_versions_are_read(self) -> None:
        """`tofu -chdir=dir validate` validates and `fmt -check` checks (kubespray); `.tftpl` and `.tpl` are Terraform
        templates (terraform-google-kubernetes-engine, terraform-aws-eks); a terraform-min-max version is two versions
        or unknown, not none (terraform-aws-vpc)."""
        _all_pass(
            self,
            {
                f"{cli} {check.name}": (TERRAFORM, check, {"infra/main.tf": "", **_chdir_pipeline(cli)})
                for cli in ("tofu", "terraform")
                for check in (CODE_FORMATTING, STATIC_ANALYSIS)
            },
        )
        with (
            self.subTest(case="templates"),
            temp_project({"main.tf": "", "templates/init.tftpl": "", "templates/user_data.tpl": ""}) as root,
        ):
            self.assertEqual(make_context(root).structure.unrecognised_suffixes, ())
        with self.subTest(case="terraform-min-max"):
            result = run_in_layout(self, TERRAFORM, PLATFORM_MATRIX, _workflow(MIN_MAX_WORKFLOW))
            self.assertTrue(result.status is Status.ERROR or "2 Terraform version(s)" in result.message, result)


# --- Typst (#263) ----------------------------------------------------------------------------------------------------

TYTANIC_TEST = {"tests/total/test.typ": '#import "/main.typ": total\n#assert.eq(total((1, 2)), 3)\n'}
# touying: typstyle through its action, then the job fails on the diff.
TYPSTYLE_ACTION = github_steps("uses: typstyle-rs/typstyle-action@v1", "run: git diff --exit-code")


class TypstTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #263: tytanic's tt run and the typstyle action are unknown
    def test_tytanic_runs_the_tests_and_the_typstyle_action_formats(self) -> None:
        """`tt run` (tytanic) compiles every `tests/**/test.typ` against its reference, so it runs the tests (cetz,
        fletcher, touying); typstyle's action followed by `git diff --exit-code` enforces the style (touying)."""
        _all_pass(
            self,
            {
                "tt run": ("Typst document", TESTS_RUN, {**TYTANIC_TEST, **_ci("tt run")}),
                "typstyle action": ("Typst document", CODE_FORMATTING, TYPSTYLE_ACTION),
            },
        )


# --- BEAM (#264) -----------------------------------------------------------------------------------------------------

GLEAM = {
    "gleam.toml": 'name = "shop"\nversion = "1.0.0"\ntarget = "erlang"\n',
    "src/shop.gleam": "pub fn total(prices: List(Int)) -> Int {\n  prices |> list.fold(0, fn(a, b) { a + b })\n}\n",
    "test/shop_test.gleam": "import gleeunit\n\npub fn main() {\n  gleeunit.main()\n}\n",
}
# cowboy: erlang.mk is the build system; it generates rebar.config for Hex.
ERLANG_MK = {
    "Makefile": "PROJECT = shop\nPROJECT_VERSION = 1.0.0\nDEPS = cowlib\n"
    "dep_cowlib = git https://github.com/ninenines/cowlib 2.22.0\n\ninclude erlang.mk\n",
    "erlang.mk": "# Copyright (c) Loïc Hoguin\nERLC_OPTS ?= -Werror +debug_info +warn_export_vars\n",
    "rebar.config": '{deps, [{cowlib, "2.22.0"}]}.\n',
    "src/shop.erl": "-module(shop).\n",
}
# ecto: the integration tests run through an Earthly target.
EARTHLY = {
    "mix.exs": "defmodule Shop.MixProject do\n  use Mix.Project\nend\n",
    "test/shop_test.exs": 'defmodule ShopTest do\n  use ExUnit.Case\n  test "adds" do\n  end\nend\n',
    "Earthfile": "VERSION 0.8\nFROM elixir:1.17\n\nintegration-test:\n    COPY . .\n    RUN mix test\n",
    **_ci("earthly -P --ci +integration-test"),
}


class BeamTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #264: Gleam, erlang.mk and Earthly targets are unknown to the BEAM profile
    def test_gleam_is_a_language_erlang_mk_a_build_system_and_earthly_targets_are_read(self) -> None:
        """`.gleam` sources with `gleam.toml` are a Gleam project whose `gleam test` runs the tests (gleam-lang/stdlib);
        a Makefile including erlang.mk is the build system, not its generated rebar.config (cowboy); an Earthly target
        is read or unknown, never silent (ecto)."""
        with (
            self.subTest(case="gleam"),
            temp_project({**GLEAM, **_ci("gleam test", "gleam format --check src test")}) as root,
        ):
            context = make_context(root)
            self.assertIn("Gleam", context.structure.languages)
            self.assertNotIn(".gleam", dict(context.structure.unrecognised_suffixes))
            self.assertEqual(TESTS_RUN.run(context).status, Status.PASS)
            self.assertEqual(CODE_FORMATTING.run(context).status, Status.PASS)
        with self.subTest(case="erlang.mk"), temp_project(ERLANG_MK) as root:
            self.assertEqual(make_context(root).structure.build_systems, frozenset({"erlang.mk"}))
        with self.subTest(case="earthly"):
            facts = _facts(EARTHLY)
            expanded = [command.argv for command in facts.of(Command) if command.via]
            unknowns = [(unknown.subject, unknown.reason) for unknown in facts.of(Unknown)]
            self.assertTrue(
                ("mix", "test") in expanded or any("earthly" in f"{subject} {reason}" for subject, reason in unknowns),
                (expanded, unknowns),
            )
