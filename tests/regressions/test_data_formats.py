"""Expected failures for data-format bugs the corpus audit found (upstream #232, #233, #271, #272, #273): JSON with
comments, YAML flow scalars and templates, API-description detection, schema examples and Protobuf modules. Each test
asserts the correct behaviour; it starts passing (an "unexpected success") when the bug is fixed, and its decorator
goes."""

from __future__ import annotations

import json
import unittest
from collections.abc import Mapping

from project_validator.checks.data_wellformed import data_wellformed
from project_validator.checks.link_check import link_check
from project_validator.checks.schema_declared import schema_declared
from project_validator.checks.schema_examples import schema_examples
from project_validator.checks.tests_run import tests_run
from project_validator.checks.type_checking import type_checking
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.openapi import API_FORMATS
from project_validator.runner import run_check
from tests.layouts.openapi import ASYNCAPI, OPENAPI
from tests.support import github_job, make_context, temp_project

# JSON files their tools read with `//` comments and trailing commas: pyright (llama.cpp), Turborepo (graphql-eslint),
# the Lua language server (koreader), Nerdbank.GitVersioning (Humanizer) and airspeed velocity (scikit-learn).
JSONC_BY_CONVENTION = {
    "pyrightconfig.json": '{\n  "disableBytesTypePromotions": false, // TODO: change once 3.12 is the minimum\n}\n',
    "turbo.json": '{"tasks": {"build": {// Run `build` in workspaces I depend on first\n"outputs": []}}}\n',
    ".luarc.json": '{"runtime.version": "LuaJIT",}\n',
    "version.json": '{"version": "1.0", // we release out of main\n "publicReleaseRefSpec": []}\n',
    "asv_benchmarks/asv.conf.json": '{\n    // The version of the config file format.\n    "version": 1\n}\n',
}
# drift's build.yaml: build_runner's `:target` names in a flow sequence, valid YAML 1.2.
FLOW_COLON_SCALARS = {"build.yaml": "targets:\n  $default:\n    dependencies: [:drift_regular, :web_worker]\n"}
# junit5's antora-playbook.yml: a template whose `@TOKEN@` placeholders Gradle substitutes before use.
TEMPLATE_PLACEHOLDERS = {
    "documentation/antora-playbook.yml": "content:\n  sources:\n  - url: @GIT_REPO_ROOT@\n    branches: @GIT_BRANCH@\n"
}

# JSON Schemas *about* API descriptions (SchemaStore's openapi-3.X.json, spec-json-schemas' asyncapi.json): the key is
# a property name indented inside `properties`, not the top-level version.
_SCHEMA_ABOUT = '{{\n  "$schema": "{}",\n  "properties": {{\n    "{}": {{"type": "string"}}\n  }}\n}}\n'
OPENAPI_SCHEMA = _SCHEMA_ABOUT.format("https://json-schema.org/draft/2020-12/schema", "openapi")
ASYNCAPI_SCHEMA = _SCHEMA_ABOUT.format("http://json-schema.org/draft-04/schema#", "asyncapi")
# Redocly's configuration: its top-level `openapi:` is the documentation-theme section (openapi-starter).
REDOCLY_PROJECT = {
    "redocly.yaml": "apis:\n  sample@v1:\n    root: openapi.yaml\nopenapi:\n  codeSamples: {}\n",
    "openapi.yaml": OPENAPI,
}
DECLARED_OPENAPI = Result.passed("1 OpenAPI file declares its version (openapi) and info.version")

# asyncapi/spec: every document under examples/ is an AsyncAPI document the CLI validates on every PR.
ASYNCAPI_EXAMPLES = {"examples/a.yaml": ASYNCAPI, **github_job("ubuntu-latest", "asyncapi validate examples/a.yaml")}
# OAI/OpenAPI-Specification: `yarn test` runs `oai-spec-test`, a program from a git dependency.
_OAI_PACKAGE = {
    "main": "index.js",
    "scripts": {"test": "oai-spec-test"},
    "devDependencies": {"@oai/build-infra": "git+https://github.com/OAI/build-infra.git#main"},
}
UNKNOWN_TEST_PROGRAM = {
    "package.json": json.dumps(_OAI_PACKAGE),
    "index.js": "",
    "a.test.js": "",
    **github_job("ubuntu-latest", "yarn test"),
}
# SchemaStore: the real jsconfig.json is strict; src/schemas/json/tsconfig.json is the *schema* for tsconfig files.
TSCONFIG_SCHEMA = (
    '{\n  "$schema": "http://json-schema.org/draft-07/schema#",\n'
    '  "$id": "https://json.schemastore.org/tsconfig.json",\n  "type": "object"\n}\n'
)
SCHEMA_STORE = {
    "index.js": "",
    "package.json": json.dumps({"main": "index.js"}),
    "jsconfig.json": '{"compilerOptions": {"strict": true, "checkJs": true}}\n',
    "schemas/tsconfig.json": TSCONFIG_SCHEMA,
    **github_job("ubuntu-latest", "npx tsc --project jsconfig.json"),
}
STRICT_JSCONFIG = Result.passed("tsc (jsconfig.json) runs; strict mode bonus: tsc (jsconfig.json)")

# protovalidate's examples/ and e2e/bzlmod/: separate buf modules whose buf.yaml turns PACKAGE_DEFINED off.
BUF_WITHOUT_PACKAGE_RULE = "version: v2\nlint:\n  use:\n    - STANDARD\n  except:\n    - PACKAGE_DEFINED\n"
UNPACKAGED_PROTO = 'syntax = "proto3";\n\nmessage Example {\n  int32 value = 1;\n}\n'
# opentelemetry-proto: Markdown documentation and a committed .lychee.toml, lychee run over it on every push.
MARKDOWN_DOCS_WITH_LYCHEE = {
    "docs/specification.md": "# Specification\n\nSee [the README](../README.md).\n",
    "README.md": "# OpenTelemetry Protocol\n",
    ".lychee.toml": "include_fragments = true\n",
    **github_job("ubuntu-latest", "lychee --config .lychee.toml --root-dir . ."),
}


def _run(selected: Check, files: Mapping[str, str]) -> Result:
    with temp_project(files) as root:
        return run_check(selected, make_context(root))


def _api_formats(files: Mapping[str, str]) -> frozenset[str]:
    """The API description formats a project of `files` is recognised as."""
    with temp_project(files) as root:
        return make_context(root).structure.formats & API_FORMATS


def _module_at(directory: str) -> dict[str, str]:
    """A buf module at `directory` whose lint rules do not require a package, with a packageless schema."""
    return {f"{directory}/buf.yaml": BUF_WITHOUT_PACKAGE_RULE, f"{directory}/example.proto": UNPACKAGED_PROTO}


class DataWellformedTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #232: JSONC-by-convention files fail the plain JSON parser
    def test_json_files_that_are_jsonc_by_their_tools_specification_parse(self) -> None:
        """A JSON file its tool documents as accepting `//` comments and trailing commas (pyright, Turborepo, the Lua
        language server, Nerdbank.GitVersioning, asv) parses: llama.cpp, graphql-eslint, koreader, Humanizer and
        scikit-learn were failed for files their tools read fine."""
        for path, text in JSONC_BY_CONVENTION.items():
            with self.subTest(path=path):
                result = _run(data_wellformed, {path: text})
                self.assertEqual(result.status, Status.PASS, result.details)

    @unittest.expectedFailure  # upstream #233: PyYAML rejects `[:a]` flow scalars; `@TOKEN@` templates are judged
    def test_yaml_flow_scalars_may_start_with_a_colon_and_templates_are_not_judged(self) -> None:
        """A plain scalar starting with `:` inside `[...]` is valid YAML 1.2 (drift's build.yaml, read by build_runner
        in every CI run) and parses; a file of `@TOKEN@` placeholders is a template (junit5's antora-playbook.yml),
        not YAML as committed, and is not failed."""
        with self.subTest(files="flow scalars"):
            result = _run(data_wellformed, FLOW_COLON_SCALARS)
            self.assertEqual(result.status, Status.PASS, result.details)
        with self.subTest(files="template"):
            result = _run(data_wellformed, TEMPLATE_PLACEHOLDERS)
            self.assertNotEqual(result.status, Status.FAIL, result.details)


class ApiDescriptionTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #272: the detection regex matches `"openapi":` property keys and redocly.yaml
    def test_schemas_about_descriptions_and_the_redocly_configuration_are_not_descriptions(self) -> None:
        """A JSON Schema that describes OpenAPI or AsyncAPI documents (SchemaStore, asyncapi/spec-json-schemas, OAI's
        archived schema.json) is not an API description; Redocly's `redocly.yaml` has a theme section called `openapi:`
        and declares no version (openapi-starter)."""
        for path, text in (("openapi-3.X.json", OPENAPI_SCHEMA), ("definitions/asyncapi.json", ASYNCAPI_SCHEMA)):
            with self.subTest(path=path):
                self.assertEqual(_api_formats({path: text}), frozenset())
        with self.subTest(path="redocly.yaml"):
            self.assertEqual(_run(schema_declared, REDOCLY_PROJECT), DECLARED_OPENAPI)


class JsonSchemaAndOpenApiGapTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #273: asyncapi validate on examples/, unknown test program, tsconfig schemas
    def test_examples_validated_unknown_test_programs_and_schemas_named_like_configs(self) -> None:
        """The AsyncAPI CLI run over `examples/` checks the schemas' examples (asyncapi/spec); a package `test` script
        whose program comes from a git dependency is unknown, not "no CI configuration runs ... (or npm test)"
        (OAI/OpenAPI-Specification); a JSON Schema called tsconfig.json is not a TypeScript configuration
        (SchemaStore)."""
        with self.subTest(check="schema-examples"):
            self.assertEqual(_run(schema_examples, ASYNCAPI_EXAMPLES).status, Status.PASS)
        with self.subTest(check="tests-run"):
            result = _run(tests_run, UNKNOWN_TEST_PROGRAM)
            self.assertNotIn(result.status, (Status.WARN, Status.FAIL), result.message)
        with self.subTest(check="type-checking"):
            self.assertEqual(_run(type_checking, SCHEMA_STORE), STRICT_JSCONFIG)


class ProtobufTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #271: buf.yaml's PACKAGE_DEFINED exception ignored; Markdown docs invisible
    def test_modules_without_the_package_rule_and_markdown_docs_with_a_link_checker(self) -> None:
        """A `.proto` file in a buf module whose `buf.yaml` excepts `PACKAGE_DEFINED` is not failed for its missing
        package (protovalidate's examples/ and e2e/bzlmod/); plain Markdown documentation that lychee checks in CI is
        a documentation unit the link check judges (opentelemetry-proto), not "no recognised language"."""
        for directory in ("examples", "e2e/bzlmod"):
            with self.subTest(module=directory):
                result = _run(schema_declared, _module_at(directory))
                self.assertNotEqual(result.status, Status.FAIL, result.details)
        with self.subTest(check="link-check"):
            result = _run(link_check, MARKDOWN_DOCS_WITH_LYCHEE)
            self.assertNotEqual(result.status, Status.SKIP, result.message)
