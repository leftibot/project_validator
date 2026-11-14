# Architecture

project_validator learns as much as it can about a project into a database of facts, answers questions about the
project from those facts, and judges the answers against a policy. Knowing how to read a build system, a tool or a CI
configuration is kept apart from deciding what a well-run project needs.

```
 project files ──► extractors ──► facts ──► questions ──► answers ──► policy ──► check results
                   (parse)        (database)  (query)     (machine-     (judge)
                                                          readable)
```

This document describes the design as it is. How the code got here, one pull request at a time, is
[docs/history.md](history.md).

## Why

Before this design, each language profile supplied a typed rule to each practice: the regular expressions that
recognised its tools, where to look for them, and what counted as passing. Detection and requirements were mixed in
one object, so adding a language touched about 25 shared files and the snapshot of every other fixture; knowledge
that was not about one language had to live in one (CMake in the C/C++ profile, although it also builds Fortran;
gcov, lizard and the sanitizers copied per profile); and a profile that could not meet a requirement (Go has no
branch coverage) needed a special case in the profile and in the tests.

Now a language is recognition plus extractors. What it cannot do follows from what its tools can do, what is shared
is shared, and a check is a question and a policy that name no language.

## The run

`project-validator <path>`:

1. **Discovery** (`project_validator/plugins.py`): the checks (`project_validator/checks`, one module each) and CI
   providers (`project_validator/ci`) are found in their packages; the built-in ecosystems are registered from the
   profile modules (`project_validator/ecosystems`, one ecosystem per module, found rather than listed); a plugin
   directory's modules add their checks, providers, ecosystems and components the same way.
2. **A context** (`project_validator/core.py`): the project (its files, read with git's view of what is tracked),
   the options (`--strict`, `--allow-unknown`, `--auxiliary`, `--build`, `--exclude`) and the CI files found.
3. **Extraction**, once (`Context.facts`, `project_validator/extraction.py`): every extractor runs in its stage and
   the facts are kept. An extractor that raises is the validator's failure, not the project's: the one
   `ExtractionError` is kept, every check that needs facts reports `not judged` with its cause, the run fails and
   the CLI prints the cause and its traceback once.
4. **The checks** (`project_validator/runner.py`): a check that applies to none of the project's languages or
   formats is skipped; each other check asks its question and judges the answers by its policy. A failure in one
   check is that check's `ERROR`.
5. **Reports** (`project_validator/cli.py`, `grid.py`, `pretty.py`): text, JSON (each result with its places) or
   Markdown with the results laid out by ecosystem and unit. The exit code is 1 when a check fails or errs.

`--facts`, `--answers` and `--map` print the layers below the checks; `--list` and `--support-matrix` print what
the registry knows.

## Layers

### Extractors

An extractor reads one kind of thing it understands and records facts. Extractors are the plugin surface: adding a
language, a build system, a tool or a CI provider means adding extractors, and nothing else changes.

| Kind | Reads | Examples |
|---|---|---|
| CI provider | CI configuration | GitHub Actions, GitLab CI, CircleCI, pre-commit.ci: jobs, their OS, toolchains and environment, and the commands each step runs |
| Command expansion | what a command runs in turn | npm, Deno and Composer scripts, Rake tasks, Make recipes, CMake targets, tox environments, pre-commit hooks, the project's own shell scripts |
| Build system | build files | CMake, Meson, Bazel, Cargo, Gradle, Maven, MSBuild, SwiftPM, Xcode: the languages built, settings and their scope, build types, build trees and outputs, the test runner |
| Toolchain | compiler and interpreter settings | GCC, Clang, MSVC, gfortran, rustc, swiftc, CPython: warning, hardening, sanitizer and coverage instrumentation flags |
| Tool | a tool's invocation and configuration | gcovr, coverage.py, eslint, clang-tidy, lizard, osv-scanner, SwiftLint: what it measures or enforces, and for which files |
| Language | source files | which languages a project uses, by suffix and by content |
| Format | data files | JSON, TOML, YAML, XML: which formats a project's data and configuration are in, and whether each file parses |
| Repository | the files themselves | committed artifacts, ignore rules, licences, security policy, large files |

Extractors run in stages (`project_validator/extraction.py`), each one's facts ready for the next: the project's
structure; its data files; what the repository holds (untracked files, committed build outputs); its test files
(and, with `--build`, what the probes find by building it); CI, with the commands and reusable steps each job runs
and what each command runs in turn; what each job builds with and on; the settings the configuration files hold;
the tools the commands run. A plugin adds components to a stage; it never changes the order.

**Components are found, never listed** (`project_validator/components.py`). A tool, a settings reader, a command
expander, an action, a question, a parser, a practice, a toolchain axis or a build output is a module-level value of
a built-in module (the shared build systems and tools, the questions, the profiles and their modules) or of a plugin
module; `known(kind)` finds every component of a kind, and what is computed from them (the tools of an aspect, the
languages a check judges, the ecosystems it applies to) is computed once, until a plugin or an ecosystem is added
(`component_cache`, `forget`). A component lives with the only language that uses it (Cargo, Composer, Bundler)
until a second language needs it; then a small refactor moves it into a shared module before the second language is
added.

### Facts

A fact is a typed, immutable record (`project_validator/facts`). Every fact has:

- **a subject**: what was found, e.g. "gcovr runs with branch metrics", "`-Werror` is set", "job `linux-gcc13`
  exists".
- **a scope**: the languages, files or targets it covers, and the CI jobs (OS, toolchain, build configuration) it
  is in effect for. Scope is what lets one fact serve several languages: `add_compile_options(-Werror)` in CMake
  covers every language CMake compiles with a GCC-style compiler, Fortran included; `CMAKE_CXX_FLAGS` covers C++
  only.
- **provenance** (`Origin`): how it was found, for results and their details, e.g. `.github/workflows/ci.yml` job
  `test` → step 4 → `npm test` → `package.json` `scripts.test` → `vitest --coverage`.
- **confidence**: read from structured data, or matched by a heuristic.

A setting is in effect only when something CI runs reads it: an eslint configuration that enables
`max-lines-per-function` counts once eslint runs in a CI job, directly or through a script CI runs. Settings and
invocations are joined to decide what is in effect; a setting alone, which nothing CI runs reads, counts for nothing.

What could not be read is recorded too (`Unknown`): a matrix computed by an expression, a reusable workflow in
another repository, a command no extractor understands, a configuration file that does not parse. An unknown says
what it may hide (`Unknown.hides`: whole `jobs`, the `commands` of a job, a job's `matrix` values, or the `settings`
of named tools), so a question counts only the unknowns that may hide what it asks about: an unreadable matrix does
not make coverage unknown, and a broken `phpunit.xml` does not make a Python project's coverage unknown. Absence of a
fact is "no" only where nothing is unknown.

Commands are split into arguments (`Command.argv`, resolved with the variables the job's environment defines), and
extractors claim them by program and subcommand (`project_validator/facts/arguments.py`: `program`, `starts_with`,
`option_values`, `has_option`, `positional`), rather than searching command lines for a flag anywhere on the line.

Facts are dataclasses held in memory (`Facts`), indexed by kind, with `where(kind, **fields)`, `settings(tool,
paths=…)`, `setting(tool, key, paths=…)`, `configured(tool, paths)` and `first_file(reader, paths)`; `Facts.shared`
holds what is made of the facts once. They are exported as JSON by `--facts`.

**Build files are read, not run.** A build file sets options and settings for some builds only: those of one
compiler (`if(MSVC)`), platform, configuration (`$<CONFIG:Debug>`) or language, or behind something only configuring
decides. A `Condition` (`project_validator/facts/conditions.py`) is a set of builds, kept as a reduced, shared
multi-valued decision diagram over those dimensions and the requirements not understood; `CompilerOption` and
`BuildSetting` facts (`project_validator/facts/build.py`) each hold one disjunct of it, as `Applies`. CMake
(`project_validator/build_systems/cmake`) and Meson (`project_validator/build_systems/meson`) are parsed by their
grammars and evaluated as configuring would evaluate them, every branch followed in the builds it holds in; each
build system turns its own settings into the compiler options they pass (`implied_options`). A set of values open to
every value not named is written as what it leaves out (`all but msvc`), so a compiler named later changes no other
project's facts.

### Structure: languages, formats, units and roles

The structure stage (`project_validator/facts/structure.py`) records every source file with its language
(`SourceFile`: by suffix, or by name where the suffix tells nothing, `Ecosystem.source_names`), every build file with
the languages it builds (`BuildFile`), what content probes found (`ContentLanguages`: a language, or a format whose
files are another format's, like the YAML of a Kubernetes manifest or an Ansible playbook, which goes to the project's
and the root unit's formats), the suffixes no ecosystem accounts for, and the project's units. The project map (`--map`, `project_validator/project_map.py`)
is a view over these facts.

An ecosystem is a **language** or a **format** (`Ecosystem.kind`, `project_validator/ecosystems/model.py`). A format
is a kind of file that is not a program: JSON, YAML, TOML, XML, a Dockerfile, a Kubernetes manifest, a notebook, a
schema, a documentation site's configuration. It has no toolchain, coverage or dependencies; what can be asked of it
is hygiene: its files parse, validate against their schema (`schema-validation`), are formatted, are linted, are
scanned, are built or run where a tool does (a chart's tests, a notebook's execution, a site's build). Everything downstream of recognition is keyed on a name: a format's
`languages` hold its format names, so a tool that handles `"YAML"` makes its check apply to the format, and a
question answers for a format in the units whose files are in it (`Unit.formats`, beside `Unit.languages`). What is
kept apart is the project's languages: `--map` lists `formats` beside `languages`, a format never makes a C++ project
a "YAML project", and skip messages name languages only. A format's files are recognised in the hidden
configuration directories too (`.github`, `.vscode`), where a language's are not: configuration is data. The first
format ecosystem is `data` (`project_validator/ecosystems/data.py`), whose parsers make a `DataFile` fact of every
data file at extraction (`project_validator/facts/wellformed.py`); `data-wellformed` is its question and policy. A
format whose files are schemas defines a `Declares` (`project_validator/facts/declaration.py`): which files are its
schemas and what each declares (a dialect, an identifier), read once at extraction into `SchemaDeclaration` facts;
`schema-declared` is their question and policy.

A **unit** is the outermost directory with a build system's files (a CMake project's subdirectories and a Maven
project's modules belong to it), or a member of a workspace a build file declares (`BuildSystem.members`: npm, yarn
and bun workspaces, Cargo and uv workspaces, go.work). A unit's languages are those of its own sources (outside the
units below it), and what its build files build unless they only declare a workspace; sources outside every unit
belong to the root unit.

Every source file and unit has a **role** (`project_validator/facts/roles.py`), told by the directories it is in
(above any source root such as `src` or `lib`, so `com/example/App.java` is product code): `product`, `test`,
`example`, `docs`, `tooling`, `benchmark`, `template` (below a `templates` directory: rendered before it is read, so a
data file there is noted, not parsed), or `vendored` (below a vendor directory anywhere, or a minified bundle).
A role names code; it judges none: every source outside vendored directories is the product's, whatever its role,
and adds its language to its unit. `--auxiliary` dials that back (`project_validator/facts/auxiliary.py`): what it
names, by role (`tooling`), by language or ecosystem (`python`, `c/c++`) or by directory (`scripts/`), is recorded as
a fact (`AuxiliaryCode`) and resolved once per project (`selectors`). Code it names adds no language to its unit; a
language only such code is written in is still judged by every practice, in the units that code is in, but the
judging layer makes its failures warnings that say so and name the dial, and labels them `(auxiliary: tooling)`.
The policies know nothing of it. Vendored code is never judged, named or not.

### CI: jobs, and what each one runs

A CI provider (`CiProvider`, `project_validator/ci`) extracts its jobs (one per matrix combination, with a GitHub
step or job whose condition is false for a combination yielding no facts and known expressions evaluated), the
commands each one runs (split by `project_validator/facts/shell.py`, PowerShell's way on Windows steps) with the
step's condition, the reusable steps it uses with their inputs, and what it could not read. A job that calls a
reusable workflow of the same repository runs that workflow's jobs; a local composite action runs its steps in the
calling job; a known action that runs a known command (`psf/black`) is expanded into that command (`Action`), so
tools only ever claim commands. pre-commit.ci is a provider whose job never builds; GitLab's known security
templates are jobs that run the template as a marker command.

**Command expansion** (`project_validator/facts/expansion.py`): a `CommandExpander` says what a command runs in
turn (package.json scripts and Deno tasks, Composer scripts, Rake tasks, Make and CMake targets, tox environments,
pre-commit hooks, the project's own shell scripts, workspace-wide script runs), and the commands found are expanded
again, each with `via`, the chain that led to it. Launchers and wrappers (`bundle exec`, `npx`, `python -m`,
`uv run`, `go tool`, `sudo`, `env`, `xvfb-run`, `timeout`; `project_validator/tools/wrappers.py`) yield the command
they run as a `Launched` command of its own. `cd` changes where the rest of a script runs; commands in a directory the
project does not contain are not expanded and cover none of the project's code; a directory a variable names is
unknown, and a tool run there covers the whole project, heuristically.

**What a job builds with** is a fact (`Job`, `project_validator/facts/jobs.py`, from `ci.job_facts`): its OS, its
compilers (or the runner's default), its toolchains and versions, its build configurations, and the ecosystems it
builds with, and the service containers it runs beside itself (a database its tests use). A job's evidence is what
it runs: commands (with the variables its environment defines), image, environment, and action inputs whose values
are known; step names and conditions are not evidence. Whether a job
uses a toolchain, or builds with an ecosystem, is read from the commands it runs, by program and subcommand
(`ToolchainPatterns.programs`, `Ecosystem.ci_programs`: `raco cover` is Racket's, `cover` alone Perl's); versions
and compilers are matched in the evidence as text, matrix values first (`project_validator/platforms.py`).

### Tools

There is one tool model (`Tool`, `project_validator/facts/tools.py`). A tool records the languages it handles and,
per *aspect* it can provide (`coverage`, `format`, `analysis`, `type-check`, `test`, `audit`, `security`, `schema`, `examples`, `compatibility`,
`links`, `migrations`, `function-length`, `fuzz`, `mutation`), the levels it can provide and how to ask for each (`can`). It claims commands
(`claims(command, facts)`: `starts`, `when`, `flagged`, `with_option`, `all_of`, `any_of` spell the common claims)
and reads only facts. A claimed command is a `ToolRun`: job, tool, languages, the aspects and levels that run
provides, the settings files it read, and its scope (its working directory); only the tools of the project's own
languages and formats are asked, so a shared tool's run is recorded for the project, not for every language the tool
serves. A tool that serves several practices
(ruff formats and lints) is one tool with several aspects (`combined`); each tool handles only its own languages
(ktlint formats Kotlin, not Java). `Tool.required` marks an analyzer that must run alongside the others.

A **settings reader** (`SettingsReader`, `project_validator/facts/settings.py`) reads one tool's settings from the
files it reads by default and from the configuration files CI commands name; each file read is a
`ConfigurationFile` fact, each setting a `Setting`, flagged `heuristic` when matched in code. Readers find files by
name only outside vendored directories; a file a command names is read wherever it is. Where a tool's behaviour is
defined (`Tool.definitions`, a `Definition` per aspect: the files that define its style or its checks, or what a
build system registers for a test runner) applies to the units at or below its directory.

Build-wired tools are claims on the build: CMake's `CMAKE_<LANG>_CLANG_TIDY`, JVM analyzers bound to a build's
verification, .NET analyzer packages, SwiftLint's build tool plugin, a restore with `NuGetAuditMode`. Probes
(`Probe`) run the project's own tools when asked (`--build`): the C/C++ profile builds the project and counts what
ctest lists.

Shared tools (`project_validator/tools`) serve every language whose files they read: gcov, gcovr, lcov and llvm-cov
for what GCC and Clang compile; lizard; osv-scanner, trivy and snyk; CodeQL, semgrep and GitLab SAST; the secret
scanners; pre-commit; the version control systems' ignore files. Each profile makes them its own for its languages
(`multi_ecosystem_audits(languages)`, `function_length_limiters(languages)`), so a language that has nothing to audit
is not judged. The scanners and auditors know the languages they read (`CODEQL_LANGUAGES`, `OSV_SCANNER_LANGUAGES`,
…), so a profile gets only the tools that read one of its languages, for those languages: CodeQL for C#, not F#;
semgrep but no CodeQL for Lua; nothing for Erlang's rebar.lock.

### Practices

Practices that ask for settings rather than tools (`compiler-warnings`, `warnings-as-errors`, `hardening`,
`cxx-extensions`) are `Practice` components (`project_validator/facts/practices.py`) in the profile that knows the
language: the `Requirement`s it asks for, all of them or any one, each met by a CI command or reusable step, a run
of a tool, the profile's settings files, or facts such as the `CompilerOption`s that apply to a compiler; and, apart,
its `Wording` (what the settings are called, how to set them). Compiler flags are requirements built once
(`project_validator/facts/flags.py`: `warning_requirements`, `errors_requirements`, `flag_requirements`), with the
flag vocabulary of the C and C++ compilers a shared tool (`project_validator/tools/toolchains.py`); C and C++ are
judged for each compiler CI builds with, by the flags that apply to it. What varies between a language's CI jobs
besides the OS is a `ToolchainAxis` component (`project_validator/facts/axes.py`): compilers for C and C++, toolchain
versions for the others.

### Questions

A question (`Question`, `project_validator/questions`) is a query over the facts that answers one thing about the
project, per language (or format), in each unit of the project that has the language: "what coverage is reported
for Python?", "are warnings errors for C++?", "which OS/toolchain/configuration combinations does CI build?"
Questions are the stable, machine-readable interface (`--answers`); checks and other consumers depend on them, never
on extractors. A question says which kinds of ecosystem it is about (`Question.kinds`), so a format is not asked
about coverage; where a format is asked (tests, formatting, analysis, security, audit, outputs, schema validation),
`--answers` lists its answer only where some tool could give one, so the YAML every project holds adds no lines.

An answer is one of:

- **yes**, with the facts that show it;
- **no**;
- **unknown**, with the reason (an unreadable matrix, a remote workflow);
- **impossible**: no known tool can provide it for the language. Go's tools measure statements, not branches; Swift's
  measure regions; nothing measures F# function length.

"Impossible" follows from what the known tools can do: tools declare their capability by facts that do not name our
languages (the file suffixes lizard parses, the lockfiles osv-scanner reads, the languages CodeQL analyses), so a new
language picks up every tool that already supports it. The same capabilities give the suggestions in results: "tools
known to report branch coverage for Rust: cargo-llvm-cov, grcov".

What every question needs is in `project_validator/questions/__init__.py`, once: the units of a language
(`units_of`), the runs of an aspect in a unit (`runs_of`: a run covers the units at or below its working directory,
and the unit that directory belongs to), the unknowns that matter to some tools (`unknowns_for`), and the shape of
an answer per language with its units (`LanguageAnswers`, `per_unit`, `language_wide`). Every tool-based practice
answers with one `ToolAnswer` (`questions/tooling.py`: the known tools, the tools CI runs with the levels they
provide, the files that define each, the unknowns); its question is `aspect_answers(aspect, level)`. The others have
a question module of their own (coverage, practices, platforms, dependencies, outputs, license, pinning, secrets,
ci-lint, wellformed, declaration).

### Policy

A policy (`project_validator/policy`, one module per practice) maps answers to statuses. For coverage: branch
coverage is required (or the finest granularity possible for the language, when branch coverage is impossible), and
path or MC/DC coverage is a bonus; a run takes a granularity to one of three rungs (`Rung`: measured, reported where
the numbers can be seen, gated by a threshold CI fails under), measuring it passes and the next rung is suggested.
Checks are thin (`project_validator/checks`): a check names its question and its
policy (`answered_check`), and `--strict` and `--warnings-as-errors` adjust the policy, not the questions. The policy
is built in; it is a separate layer so that it can be made configurable later without touching extraction. Hints
come from the tools (`can`), not from profiles.

An **unknown** answer is a gap in the validator's tooling (configuration it cannot read, such as a CI provider it
only scans heuristically, or a matrix computed by an expression), not a finding about the project. So it is an
`ERROR`, which fails the run and names what was not read, unless the user passes `--allow-unknown`; then the answer
is judged by what could be read, as a no. What settles an answer before a policy judges it (no known tool, or an
unknown that is not allowed) is said once (`skipped_or_unknown`), as is a policy that only advises
(`policy/tooling.advised`).

### Judging and results

`project_validator/judging.py` makes a question and a policy into a check: the question is asked of each ecosystem
the project uses, the policy judges each answer, and the results are labelled by ecosystem, language and unit and
merged (`combined`); the same result for every ecosystem is said once. A folded result keeps the places it was folded
from (`Result.places`: one ecosystem in one unit, with the tools that ran, and whether the code was named
auxiliary), so `--format json` reports them and `--format markdown` lays the results out as a grid without
re-judging. CI appends that grid for this repository to the job summary of each
[run](https://github.com/cpp-best-practices/project_validator/actions/workflows/ci.yml?query=branch%3Amain).

A tool-based check records its aspect (`Check.aspect`), so the support matrix (`--support-matrix`) can name, for
each check and ecosystem, the tools the registry knows; a check's languages are always asked of its components
(`Check.languages_from`), never copied, so a plugin's tool for a new language makes the check apply to it. The
support matrix is not committed (a generated file would be, against `committed-artifacts`, and every new ecosystem
changes it): the `pages` workflow renders it, the README and the pages under docs/ to HTML (`tests/build_site.py`)
and publishes them to GitHub Pages from `main` on every push.

### Worked example: branch coverage in this repository

1. The GitHub Actions extractor records the job `coverage` and its command
   `["coverage", "run", "--branch", "-m", "unittest"]`.
2. The coverage.py extractor claims `coverage run` and records that coverage.py runs in that job, measuring lines
   and branches, for Python.
3. Without `--branch`, the same extractor reads the configuration coverage.py would read (`.coveragerc`, else the
   first of `setup.cfg`, `tox.ini` and `pyproject.toml` with coverage settings) for `branch = true`: the setting
   joins the run, and counts for nothing without one.
4. The coverage question answers for Python: lines yes, branches yes, paths impossible.
5. The coverage policy requires branches: PASS, with no path coverage suggestion, because none is possible.

## Profiles

A profile (`project_validator/ecosystems/<module>`) is everything the validator knows about one ecosystem:
recognition (its build systems with the files they are recognised by, its source suffixes, a content probe, how CI
names its toolchain's versions and the programs that show a job uses it), and its components, found rather than
listed. A profile of more than a few hundred lines is a package laid out as the scaffold writes one: `__init__.py`
recognises the ecosystem (build systems, toolchain, package managers, outputs), `tools.py` holds its tools and their
settings readers, `practices.py` its practices. A profile's fixtures (`tests/fixtures/well_configured_<module>`,
`bare_<module>`), test layouts (`tests/layouts/<module>.py`) and documentation page (`docs/ecosystems/<module>.md`)
are named after its module, and the ecosystem contract (`tests/test_ecosystem_contract.py`) checks that each
profile has them and that its well-configured fixture passes every check that applies to it.
`python -m project_validator.scaffold` starts one with everything the contract asks for.

A plugin (`--plugin-dir`) is a directory of modules read the same way: its ecosystems are registered (an ecosystem
may not claim another one's build file or source suffix), and its components are found beside the built-in ones.

## Invariants

Tests keep these:

- Adding a language, build system, tool or CI provider adds modules and fixtures and edits no shared list: built-in
  profiles and checks are discovered, and tests and documentation derive their expectations from the registry.
- A result names only the project's own languages; nothing in one fixture's results changes when an unrelated
  language is added.
- Checks do not name languages or tools, and never import a profile (`tests/test_architecture.py`).
- Policies read answers, never files or facts.
- The snapshots (`tests/snapshots`: for each fixture, its behaviour in `<fixture>.json`, the results and the
  answers, and what was learned in `<fixture>.facts.json`, the facts and the project map) are reproduced exactly,
  except where a change deliberately moves results and says so.
- The project corpus (`corpus/`: real repositories pinned to a commit) is recorded by `python -m corpus record` and
  two recordings compared by `python -m corpus diff`; CI records a pull request's head and its base over the same
  checkouts and shows what changed, so every parser runs over real inputs on every change. Nothing is recorded in the
  repository. Every ecosystem profile has a corpus project that stands for it, and a recording must detect it there
  (`tests/test_corpus.py`, `corpus record`). What the validator gets wrong on a corpus project is an upstream issue
  the manifest names; its fix shows in the corpus diff.
