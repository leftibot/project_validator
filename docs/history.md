# History

How project_validator came to its design ([docs/architecture.md](architecture.md)): the rearchitecture from
per-language rules to extractors, facts, questions and policy, one pull request a step, each with every gate green.
This is a log; the design as it is now is in the architecture document, which stays current while this one grows.

## Migration

Each step is one pull request with every gate green. The snapshots (`tests/snapshots`: for each fixture, its
behaviour in `<fixture>.json`, the results and the answers, and what was learned in `<fixture>.facts.json`, the
facts and the project map) must be reproduced exactly,
except where a step deliberately changes results and says so.

1. **Discovery and derived expectations.** Built-in profiles are discovered like checks; each profile's fixtures,
   test layouts (`tests/layouts/<name>.py`) and documentation page (`docs/ecosystems/<name>.md`) are named after its
   module; tests derive their language lists from the registry; the README describes each check without per-language
   detail; the skip message stops listing every language.
2. **Facts and the CI command graph**, in three parts:
   1. The fact store (`project_validator/facts`) and the CI facts: each provider extracts its jobs (one per matrix
      combination), the commands each one runs (split by `project_validator/facts/shell.py`) with the step's
      condition, the actions it uses with their inputs, and what it could not read. `--facts` prints them.
   2. Command expansion (`project_validator/facts/expansion.py`): a `CommandExpander` says what a command runs in
      turn, and the commands found are expanded again, each with `via`, the chain that led to it. Expanders live
      with what they know and are found, not listed: package.json scripts and Deno tasks in the JavaScript profile,
      Composer scripts in the PHP profile, Make and CMake's custom targets (`cmake --build --target`) in
      `project_validator/build_systems`, pre-commit in `project_validator/tools`. Rake tasks and Maven lifecycle
      phases follow when their profiles move onto facts; presets and phases are settings rather than commands.
   3. The jobs the checks judge are built from the facts. A GitHub step or job whose condition is false for a
      combination yields no facts, and known expressions are evaluated (`project_validator/ci/github_expressions.py`).
      A job's evidence is what it runs: commands (with the variables its environment defines), image, environment,
      and action inputs whose values are known; step names and conditions are not evidence. Each build system reads
      the build types from its own commands (`BuildSystem.build_types`). Whether a job uses a toolchain, or builds
      with an ecosystem, is read from the commands it runs, by program and subcommand (`ToolchainPatterns.programs`,
      `Ecosystem.ci_programs`: `raco cover` is Racket's, `cover` alone Perl's); compilers and toolchain versions
      are still matched in that evidence as text, matrix values first (an action input that is switched off is not
      evidence); reading them structurally is the toolchain step (5).
3. **Coverage end to end.** Coverage extractors for every supported language, the coverage question and its policy;
   the `coverage` check moves to them and the `CoverageTools` rules are deleted.
   - A coverage tool records the languages it measures and each granularity it can measure (line, statement,
     region, branch, path) with how to ask for it, and claims the commands that run it by program and subcommand
     (since 3¾ an ordinary `Tool` with a `coverage` aspect). A claimed command is a run, joined with the
     configuration that command reads (`pytest` with its `addopts` and coverage.py's settings, `phpunit`
     with its XML, `dotnet test` with the MSBuild settings and `.runsettings`, `xcodebuild test` with the scheme,
     `cmake` configuring with the CMake files): a setting alone, which nothing CI runs reads, counts for nothing.
   - Launchers are command expanders that yield `Launched` commands: `bundle exec rake` runs `rake`, `npx c8` runs
     `c8`, `python -m coverage` runs `coverage`, `uv run pytest` runs `pytest`.
   - Components (command expanders and coverage tools) are found by `project_validator/components.py` in the
     shared build systems and tools and in the profiles (and their modules), never listed.
   - The coverage question (`project_validator/questions/coverage.py`) answers per language and granularity; the
     policy (`project_validator/policy/coverage.py`) requires branch coverage, or the finest granularity a known tool
     can measure, and reports path coverage as a bonus. An unknown answer is an error, naming what was not read
     (see Policy).
   - `--answers` prints the answers. gcov, gcovr, lcov and llvm-cov are shared tools (`tools/coverage.py`): gcov's
     family covers what GCC compiles, Fortran included.

   **3½. Foundations: structure and settings as facts, and the query layer.** Step 3 showed that without shared
   layers each question would read files and join settings in its own extractor. Before the remaining practices
   move:
   - **Structure facts** (`project_validator/facts/structure.py`): every source file with its language
     (`SourceFile`), every build file with the languages it builds (`BuildFile`), what content probes found
     (`ContentLanguages`), and the suffixes no ecosystem accounts for. Vendored code (a `vendor`/`third_party`-style
     directory, a minified `*.min.js`) is recorded but makes no language the project's. The project map (`--map`)
     is a view over these facts, with the vendored files listed.
   - **Setting facts** (`project_validator/facts/settings.py`): a `SettingsReader` component reads one tool's
     settings from the files it reads by default and from the configuration files CI commands name
     (`--rcfile`, `-c`, `--settings`). Each file read is a `ConfigurationFile` fact; each setting a `Setting`
     (tool, dotted key, value, origin), flagged `heuristic` when matched in code (a Jest config, a Gradle script).
     Format helpers cover TOML, INI, JSON, XML and `key = value` files. A file that does not parse is an `Unknown`
     scoped to its tool, so it makes unknown only the answers that depend on that tool.
   - **Queries** (`Facts`): indexed by kind, with `where(kind, **fields)`, `settings(tool, paths=…)`,
     `setting(tool, key, paths=…)`, `configured(tool, paths)` (the first file with the tool's settings) and
     `first_file(reader, paths)` (the first file that exists).
   - **Extraction stages** (`project_validator/extraction.py`, which `Context.facts` calls): structure, then CI and
     command expansion, then settings (which need the commands that name configuration files), then the tools those
     commands run.
   - **Coverage, rebuilt on them**: coverage tools are pure functions of a command and the facts; none reads a
     file. Each declares the settings tools it `reads`, which scopes the unknowns that matter to its answers.
   - **Questions are components** (`Question` in `project_validator/questions`), found like the others, so
     `--answers` lists whatever questions exist.

   **3¾. One tool model, and units.** So that no practice builds its own copy of the machinery, and so that
   monorepos and mixed-language projects are judged where their code is:
   - **One tool model** (`project_validator/facts/tools.py`). A `Tool` records the languages it handles and, per
     *aspect* it can provide (`coverage` now; `lint`, `format`, `analysis`, `audit`, `type-check` as practices
     move), the levels it can provide and how to ask for each. It claims commands (`claims(command, facts)`) and
     reads only facts. A claimed command is a `ToolRun`: job, tool, languages, the aspects and levels that run
     provides, the settings files it read, and its scope (its working directory). Each question reads the runs of
     its aspect; a tool that serves several practices (ruff formats and lints) is one tool with several aspects.
     Coverage is spelled with `coverage_tool` and `measured` (`project_validator/facts/coverage.py`), which only
     fill in the `coverage` aspect.
   - **One way a command runs another.** Wrappers (`sudo`, `env CC=clang`, `nice`, `emcmake`, `xvfb-run`,
     `ccache`, `timeout 5m`; `project_validator/tools/wrappers.py`) are launchers like `bundle exec` and `npx`: the command they
     run is a `Launched` command of its own, with the variables they set. `resolved` only substitutes variables.
   - **One way to read a command line** (`project_validator/facts/arguments.py`): `program`, `option_values`,
     `has_option`, `short_flags`, `positional`.
   - **Units** (`Unit` facts, `project_validator/facts/structure.py`). A unit is the outermost directory with a
     build system's files (a CMake project's subdirectories and a Maven project's modules belong to it), or a
     member of a workspace a build file declares (`BuildSystem.members`: npm, yarn and bun workspaces, Cargo and
     uv workspaces, go.work). A unit's languages are those of its own sources (outside the units below it), and
     what its build files build unless they only declare a workspace; sources outside every unit belong to the
     root unit. `--map` lists the units.
   - **Roles.** Every source file and unit has a role, told by the directories it is in (above any source root
     such as `src` or `lib`, so `com/example/App.java` is product code): `product`, `test` (tests and test-fixture
     projects), `example`, `docs`, `tooling`, `benchmark`, or `vendored` (below a vendor directory anywhere, or a
     minified bundle). A role names code; it judges none: every source outside vendored directories is the
     product's, whatever its role, and adds its language to its unit (a C++ library's `scripts/release.py` makes
     Python a language of the root unit, held to every practice). `--auxiliary` dials that back
     (`project_validator.facts.auxiliary`): what it names, by role (`tooling`), by language or ecosystem (`python`,
     `c/c++`) or by directory (`scripts/`), is recorded as a fact (`AuxiliaryCode`) and resolved once per project
     (`selectors`). Code it names adds no language to its unit; a language only such code is written in is still
     judged by every practice, in the units that code is in (`per_unit` and `language_wide` fall back to
     `auxiliary_units_of`; `LanguageAnswers.auxiliary` says what named the code, by unit, and the answers count runs
     and manifests in that code), but the judging layer makes its failures warnings that say so and name the dial
     (`judging._advisory`), and labels them `(auxiliary: tooling)` (`Placed.auxiliary`, shown by the JSON report and
     the markdown grid). The policies know nothing of it. Vendored code is never judged, named or not.
   - **Unknowns say what they may hide** (`Unknown.hides`): whole `jobs`, `commands` of a job, a job's `matrix`
     values, or `settings` of named tools. A question counts only the unknowns that may hide what it asks about:
     an unreadable matrix does not make coverage unknown, and a broken `phpunit.xml` does not make a Python
     project's coverage unknown.
   - **Reading more of what CI runs.** A quoted string may span lines, and quoted or escaped operator characters
     are text (`awk -F '|'`, `find -exec … ';'`). `cd` changes where the rest of a script runs. Commands in a
     directory the project does not contain (another checkout, a build tree CI generates, `cd /tmp`) are not
     expanded and cover none of the project's code. A job that calls a reusable workflow of the same repository
     runs that workflow's jobs; a workflow that runs only `on: workflow_call` runs only where it is called.
     Workspace-wide script runs (`pnpm -r`, `--filter`, `npm --workspaces`, `turbo run`, `lerna run`,
     `nx run-many`) run each workspace package's script (npm, yarn and bun workspaces, `pnpm-workspace.yaml`).
   - **Questions answer per language per unit.** A run covers the units at or below its working directory, and the
     unit that directory belongs to (the deepest unit containing it), so a run from the root covers every unit, a
     run in `src/` covers the root unit, and a run in `packages/a` covers only that package (since step 4; before,
     it covered the root unit above it too).
     A project with one unit is judged as before. In a monorepo, findings name the unit (`packages/b: no branch
     coverage …`); in a mixed-language project each language is judged in the units that have it (a C++ project
     with Python bindings in `python/` needs Python coverage there).
4. **The remaining practices**, one at a time, each deleting its rule type from `rules.py`. Each becomes settings
   readers, an aspect of the shared `Tool` model, a question answered per language per unit, and a policy. What
   every practice needs is shared: `project_validator/questions/__init__.py` has the units of a language, the runs
   of an aspect in a unit and the unknowns that matter to some tools (`per_unit`, `runs_of`, `unknowns_for`), and
   `project_validator/judging.py` makes a question and a policy into a check (`answered_check`), labelling results
   by language and unit.

   **4a. Formatting** (`code-formatting`; the `Formatter` rule is deleted).
   - **The `format` aspect** (`project_validator/facts/formatting.py`) has two levels: `check`, a run that fails on
     unformatted code, and `apply`, one that rewrites it. Applying it enforces it where a change fails CI or is kept:
     a pre-commit hook (pre-commit fails when a hook changes a file), a job that runs `git diff --exit-code` or
     `--quiet`, or commits (`git commit`, `stefanzweifel/git-auto-commit-action`). A run that only prints the
     formatted code is not a formatter run. `flagged(prefixes, checks=…, applies=…)` spells most formatters' claims
     (`flagged(("ruff", "format"), checks=("--check", "--diff"))`); `either` combines claims.
   - **Where a tool's behaviour is defined** (`Tool.definitions`, a `Definition` per aspect): the files that define
     its style, found as the files a settings reader read (`defined_by(files=…)`: a `.clang-format`, whatever it
     holds; `file_reader` records such files without reading settings) or the files holding a tool's settings
     (`defined_by(settings=…)`: `[tool.ruff]` in pyproject.toml), and whether the tool has a default of its own. A
     definition applies to the units at or below its directory, and to the unit it is in. Linters and analyzers will
     use the same for their rules.
   - **Actions run commands** (`Action`, in `project_validator/facts/expansion.py`): a reusable CI step that runs a
     known command (`psf/black` runs `black --check --diff .`) is expanded into that command, so tools only ever
     claim commands.
   - **Reading more of what CI runs**: commands inside a command substitution (`test -z "$(gofmt -l .)"`) run before
     the command they are part of, and `xargs` launches its command. A local composite action (`uses:
     ./.github/actions/build` or `$/…`) runs its steps in the calling job, with its inputs in place (a missing one
     is unknown; a JavaScript or Docker action runs its own code). An action's `working-directory` input is where
     its command runs. A job that shows a diff for a later step to fail on (`DIFF=$(git diff)`) is taken to enforce
     what its formatter applied, as a heuristic run.
   - **Settings outside vendored code**: a settings reader reads the files it finds by name only outside vendored
     directories (a `deps/jemalloc/.clang-format` is not the project's); a file a command names is read wherever
     it is. Roles moved to `project_validator/facts/roles.py`, shared by structure and settings.
   - **The formatting question** answers per language per unit: whether CI enforces the formatting (yes, no,
     unknown, or impossible when no known tool formats the language), with which tools, which only rewrite files,
     which files define the style, and which tools CI runs whose style needs a definition the project lacks. Each
     formatter handles only its own languages: ktlint formats Kotlin, not Java; Fantomas F#, not C#.
   - **The policy** passes enforcement with a defined style (a file, or the tool's own), fails a style that is not
     defined, a run that only rewrites files, or no run; warns when a style is defined but CI does not enforce it;
     an unknown answer is an error unless `--allow-unknown`. Hints come from the tools (`can`), not from profiles.
   - **Plugins add components** (`project_validator/components.py`, `add_plugin_modules`): a plugin module's tools,
     settings readers, expanders and actions are found like the built-in ones, and a check made of a question
     applies to the languages its tools now handle (`Check.languages_from`).
   **4b. Static analysis and type checking** (`static-analysis`, `type-checking`; the `Analyzer`, `StaticAnalysis`
   and `TypeChecking` rules are deleted).
   - **One answer for every tool-based practice** (`project_validator/questions/tooling.py`): `ToolAnswer` holds,
     for one aspect of one language in one unit, the known tools (how each provides each level, whether it needs a
     definition, whether it is required alongside the others), the tools CI runs with the levels they provide and
     the settings files they read, the files that define each, and the unknowns. A practice's question is
     `aspect_answers(aspect, level)`; formatting moved onto it. Policies live in `project_validator/policy/`, one
     module per practice, with the wording helpers they share.
   - **Aspects**: `analysis` (one level, `checks`: an analyzer's `Definition` is where its checks are chosen; clang-tidy
     and golangci-lint need one) and `type-check` (`checks`, and `strict` as a bonus), spelled by `analyzer`,
     `analysed`, `type_checker` and `type_checked` (`project_validator/facts/analysis.py`). `Tool.required` marks an
     analyzer that must run alongside the others (clang-tidy and cppcheck). `combined` makes one tool of the same
     program's aspects (RuboCop and Standard format and lint; biome formats and lints; PHPStan and Psalm analyse and
     type check).
   - **Build-wired analyzers**: CMake's `CMAKE_<LANG>_CLANG_TIDY`/`_CPPCHECK` run their analyzer in a build CI
     configures; JVM analyzers run by their goals and tasks or by the plugins a build's verification brings in, Error
     Prone by every compiling build; .NET analyzer packages (`PackageReference`, now read from MSBuild files) by every
     build; SwiftLint's build tool plugin by a package build. `go run <package>@<version>` and `go tool` launch the
     program the package names.
   - **pre-commit.ci** (`project_validator/ci/pre_commit_ci.py`) is a CI provider: a `.pre-commit-config.yaml` with
     a `ci:` section (`CiProvider.recognises`) runs its hooks, but those in `ci.skip` (pre-commit's `SKIP`). Its job
     never `builds` (`CiJob.builds`), so it is no platform or build configuration. A pre-commit hook counts only where
     CI runs it; before, any hook counted.
   - **Each tool for its own languages**: Error Prone, PMD and Checkstyle analyse Java, detekt Kotlin; .NET analyzer
     packages C#, FSharpLint F#.
   - Components may be defined as module-level tuples (one analyzer per NuGet package), and settings readers may name
     files by the end of their path (`sorbet/config`). `defined_by(named=…)` counts a file by existing (an empty
     `ty.toml`).
   - Profiles that grew past one module became packages (`python`, `javascript`, `jvm`), each with an `analysis`
     module.
   - **Reading more of what CI runs** (from the corpus): tox environments (`tox -e`/`-f`/`run`/`p`, the env list,
     factor-conditional commands, braces, `tox.ini`/`tox.toml`/`[tool.tox]`; a factor from a variable matches every
     section it may be); the project's shell scripts (`bash ci/lint.sh`, `./ci/lint.sh`); GitLab local `include:`
     files, `extends:` and `!reference` (YAML values with local tags are `Tagged`; other includes are unknowns that
     hide jobs); PowerShell scripts (a step's `shell: pwsh`, or a Windows runner's default) split with PowerShell's
     escape character; and a GitHub job whose matrix is an expression runs its steps with the matrix values unknown
     (before, its steps were lost).
   - **Auxiliary code does not speak for the product**: with `--auxiliary example`, a run only in an example's
     directory (tsc in `examples/app`) covers no product code, and the example's own configuration defines no tool of
     the unit it is in; both count for the advisory answer about the examples. tsc reads the configuration it uses (`-p`, or `tsconfig.json` where it runs, and the local
     ones it extends). Findings list at most three files, and how many more.

   **4c. Tests** (`tests-run`; the `TestSuite` rule is deleted).
   - **The `test` aspect** (`project_validator/facts/testing.py`), one level, `runs`. A runner's `Definition` is where
     the tests it runs are: the `TestFile` facts of the kinds it runs, or what a build system registers (CTest's
     `add_test` after `enable_testing()`, Meson's `test()`, read as settings). A `TestFiles` component says what a
     language's test file is (a path, and what it contains); test files are a structure stage. `Definition.describe`
     says what defines a tool for findings, and `from_test_units` lets a separate test project's tests
     (`tests/App.Tests`) count for every unit.
   - **Probes** (`Probe`) run the project's own tools when asked (`--build`): the C/C++ profile's builds the project
     and counts what ctest lists (`BuiltTests`); a build that cannot run is an unknown that hides ctest's tests.
     `ToolAnswer.unknown_definitions` keeps the unknowns that may hide a definition apart from those that may hide a
     run, so that "no tests found" is said only when that is known.
   - `coverage run -m <module>` launches the module, as `python -m` does; a sourced script (`. ci/test.sh`) runs its
     commands.
   - A directory a variable names (`cd $BUILD_DIR`) is unknown rather than outside the project: nothing is expanded
     there, but a tool run there covers the whole project, heuristically (most often it is the project's build tree).
     Before, such runs covered nothing.
   - Roles: a unit's own directory name tells its role first, below a source root too (`internal/tools`, a Go tools
     module, is tooling); fuzz and stress tests, and directories named `tests-…`, are test code. So a crate of fuzz
     targets or a tools module is not held to having tests of its own.

   **4d. Dependency audit** (`dependency-audit`; the `DependencyAudit` rule and `MULTI_ECOSYSTEM_AUDITS` are deleted).
   - **The `audit` aspect** (`project_validator/facts/audit.py`), one level, `runs`. Auditors that serve every ecosystem
     (osv-scanner, trivy of the file system, snyk) are made by `multi_ecosystem_audits(languages)` in
     `project_validator/tools/audits.py`; each profile makes them its own, for its languages, so a language whose
     ecosystem has nothing to audit (C/C++) is not judged. Their actions are shared.
   - Audits that a build performs are claims on the build: a restore with `NuGetAuditMode` `all`, a Composer install
     with `roave/security-advisories` required, dependency-check bound to Maven's verification.
   - `starts(*prefixes)` and `when(matches, run)` (`project_validator/facts/tools.py`) spell the commonest claim: a
     program, and the subcommands after it.

   **4e. Security scanning** (`security-scanning`; the `SecurityLints` rule is deleted).
   - **The `security` aspect** (`project_validator/facts/security.py`), one level, `scans`. CodeQL, GitLab SAST and
     semgrep are made by `multi_language_scanners(languages)` (`project_validator/tools/scanners.py`) for each
     profile's languages (CodeQL not for PHP, which it does not analyse). A language's security lints are claims on
     the tool that runs them with the settings that turn its security rules on: ruff with `S`, golangci-lint with
     gosec, eslint with eslint-plugin-security, Psalm's taint analysis, SpotBugs with Find Security Bugs, PMD with its
     security rules, a .NET build with the Security category turned up, a cargo build with `unsafe_code` forbidden.
     A setting alone, which nothing CI runs reads, no longer counts.
   - **GitLab's known templates** (`Security/SAST`, `Dependency-Scanning`, `Secret-Detection`, ...) are jobs that
     build nothing and run the template as a marker command (`gitlab-template <name>`), which the scanners claim;
     other templates stay unknowns that hide jobs.
   - Settings readers may name files in hidden directories (`.cargo/config.toml`); those directories are read.
   - The same result for every ecosystem is said once (`combined`), rather than labelled ecosystem by ecosystem.

   **4f. Function length** (`function-limits`; the `FunctionLimits` rule is deleted).
   - **The `function-length` aspect** (`project_validator/facts/limits.py`): a run `measures` function length, and
     `limits` it when it fails on a function longer than a limit. lizard is a shared tool
     (`function_length_limiters(languages)` in `project_validator/tools/limits.py`), made by each profile for the
     languages lizard measures; it limits when told a length (`-L`, `--length`, `-T length=`).
   - **A linter's rule** is a `limiter`: the linter's own claim (when it runs) and a `Rule` read from its settings,
     on by default unless they turn it off (RuboCop's Metrics/MethodLength, SwiftLint's function_body_length,
     detekt's LongMethod) or only once they turn it on (clang-tidy's readability-function-size with a threshold,
     golangci-lint's funlen, eslint's max-lines-per-function, Checkstyle's MethodLength, PHPMD's
     ExcessiveMethodLength). Their settings are read structurally where the format allows it (`.clang-tidy`,
     `.rubocop.yml`, `.swiftlint.yml`, detekt, Checkstyle and PHPMD XML); eslint's, which is code, is matched.
   - lizard named only in CMake files no longer counts: it is judged by what CI runs, like every other tool, until
     CMake custom targets are read (step 5).

   **4g. Dependency management** (`dependency-management`; the `DependencyManagement` rule is deleted).
   - **Facts** (`project_validator/facts/dependencies.py`): settings readers of each package manager's manifests and
     lockfiles record a manifest that `Declared` dependencies, a lockfile (or setting) that `Locked` them, and whether
     a package is an `Application` or a `Library`. A `PackageManager` says when its lock is asked for (always, for
     applications, or never), how to lock, which CI commands verify dependencies (`mvn --strict-checksums`), and
     which files are its vendored output.
   - **`Untracked`**, a structural fact: a file git does not track, so an ignored lockfile locks nothing.
   - The question is answered per language and unit: a manifest belongs to the unit that owns it (not the docs' or
     tooling's), a lockfile locks its directory and those below it (a workspace's lock locks its members). A manifest
     that does not parse makes the answer unknown.

   **4h. Build outputs** (`vcs-ignore`, `committed-artifacts`; the `BuildOutputs` rule is deleted).
   - **`BuildOutput` components** (`project_validator/facts/outputs.py`): what a language's builds (or one build
     system's: SwiftPM's `.build`, Maven's `target`) write. A language's outputs are those of the build systems the
     project uses, or its own when none has one; every build system in use has its outputs ignored.
   - **The repository stage** (`project_validator/facts/repository.py`) reads git's tracked files once: the files it
     does not track (`Untracked`) and the tracked files that are a build output (`CommittedOutput`), which the
     settings readers cannot see, as build trees are not walked.
   - **Ignore entries** are facts read from `.gitignore`, `.hgignore`, `.bzrignore` and Fossil's `ignore-glob`
     (`project_validator/tools/version_control.py`).

   **4i. License** (`license`; the `DeclaredLicense` rule is deleted).
   - **Facts** (`project_validator/facts/licenses.py`): each `LicenseFile` with the licenses it holds (read by
     `project_validator/tools/licenses.py`), and each manifest's `DeclaredLicense`, read by the profiles.
   - The project's license is that of the license files at its root (and REUSE's `LICENSES/`). A product manifest
     is compared with the license files nearest to it, in its directory or the nearest above it, so a monorepo member
     may hold its own; the manifests of the docs, examples, tooling and tests are not compared.

5. **Shared build systems, toolchains and tools**: CMake, Meson, MSBuild, Gradle and Xcode, and the GCC, Clang and
   MSVC flag knowledge, leave the C/C++ profile; llvm-cov, gcov and osv-scanner become shared tools.
   - A build file sets options and settings for some builds only: those of one compiler (`if(MSVC)`), platform,
     configuration (`$<CONFIG:Debug>`) or language, or behind something only configuring decides (an option, a
     compiler check). A `Condition` (`project_validator/facts/conditions.py`) is a set of builds, kept as a reduced,
     shared multi-valued decision diagram over those dimensions and the requirements not understood, so that the
     many branches of a real build file stay exact and cheap; `CompilerOption` and `BuildSetting` facts
     (`project_validator/facts/build.py`) each hold one disjunct of it, as `Applies`.
   - CMake is read without running it (`project_validator/build_systems/cmake`): its files are parsed by the
     language's grammar and evaluated as configuring would evaluate them, from each top-level CMakeLists.txt through
     `include()`, `add_subdirectory()` and the project's own functions and macros, with variables in their scopes
     and every branch followed in the builds it holds in. Presets add their cache variables, in the builds configured
     with them. A file nothing reaches is evaluated as if included, a function nothing calls as if called, each
     under that requirement. CTest registrations, CPM and FetchContent, and the analyzers a build runs
     (`CMAKE_CXX_CLANG_TIDY`) are read from the same evaluation; `cmake --build` expands to the commands of the
     custom targets it builds.
   - Meson is read the same way (`project_validator/build_systems/meson`): meson.build files are parsed and evaluated
     from each top-level one through `subdir()`, every `if` branch followed in the builds it holds in; the compiler
     (`cc.get_id()`, `cc.get_argument_syntax()`), the host system and the build type are understood, other options
     and compiler checks (`cc.has_argument()`, `cc.get_supported_arguments()`) are requirements. `default_options`,
     a target's `override_options` and meson.options defaults are `BuildSetting`s; project, global and target
     arguments are `CompilerOption`s; `test()` registers tests; `meson compile <target>` (or `ninja <target>`) runs a
     run target's command. `Dimension` (`project_validator/facts/conditions.py`) is how each build system names a
     dimension's values (CMake's `GNU`, Meson's `gcc`).
   - Each build system turns its own settings into the compiler options they pass (`implied_options`): CMake's
     `COMPILE_WARNING_AS_ERROR` passes GCC `-Werror` and MSVC `/WX`, Meson's `warning_level` (1 by default) and
     `werror` theirs. The C and C++ compilers' flag vocabulary is a shared tool (`project_validator/tools/toolchains.py`).
   - What CI builds with is a fact: a `Job` (`project_validator/facts/jobs.py`) holds each CI job's OS, compilers (or
     the runner's default), toolchains, build configurations and ecosystems, extracted once after the jobs' commands
     are expanded.
   - Practices that ask for settings (`compiler-warnings`, `warnings-as-errors`) are `Practice` components
     (`project_validator/facts/practices.py`) in the profile that knows the language: the `Requirement`s it asks
     for, all of them or any one, each met by a CI command or reusable step (matched in it, with its variables and
     inputs), a run of a tool, the profile's settings files (matched heuristically by a `requirement_reader` until
     they are read structurally), or facts such as the `CompilerOption`s that apply to a compiler. C and C++ are judged
     for each compiler CI builds with, by the flags that apply to it; every language by its own requirements (Java
     and Kotlin, C# and F#, apart). The answers are per language (`project_validator/questions/practices.py`).
     `hardening` is a practice too: GCC's, Clang's and MSVC's hardening flags for C and C++ (GCC's `-fhardened`
     meets them all, for GCC only), release overflow checks for Rust, position-independent executables for Go (a
     project that builds no Go program is skipped), and for Swift a practice that forbids: compiling the runtime
     safety checks away (`-Ounchecked`).
   - `cxx-extensions` is a practice met by any one setting: CMake's `CMAKE_<LANG>_EXTENSIONS` off for the whole
     build (preferred) or a target, or Meson's standard `cpp_std`; C and C++ each by their own.
   - What varies between a language's CI jobs besides the OS is a `ToolchainAxis` component
     (`project_validator/facts/axes.py`): compilers for C and C++, toolchain versions for the others; a compiled
     language's axis asks `ci-build-types` of it. `platform-matrix` and `ci-build-types` answer from the `Job` facts
     (`project_validator/questions/platforms.py`). With that, `rules.py` and the per-practice dispatch (`practice`,
     `Ecosystem.rules`, `rule_for`) are gone: every check is a question and its policy.
6. **Profiles shrink** to language recognition and the language's own tools: what they still hold that several
   ecosystems share moves to the shared build systems and tools.
   - The project-wide checks (copy-paste detection, secret scanning, CI linting) name the tools CI commands, steps
     and pre-commit hooks run, from facts; no check reads CI text any more.
   - CMake and Meson are whole build systems in `project_validator/build_systems` (their definitions, build types,
     ctest and `meson test`), and `BuildSystem` itself lives there (`build_systems/model.py`); the C/C++ profile keeps
     recognition, its formatters, analyzers and package managers, and its practices.
7. **Proof**: add Fortran using only extractors and a recognition module.
   - The Fortran profile (`project_validator/ecosystems/fortran.py`) holds recognition (its suffixes), fpm (a build
     system, its manifest, `fpm test`, its dependencies and the flags of its built-in profiles), the Fortran
     compilers' flags for the practices (gfortran, ifx and ifort, flang) and the Fortran tools (fprettify,
     fortitude). CMake's and Meson's facts, ctest, `meson test`, gcov and its reports and lizard serve it unchanged.
   - What the shared layers had to learn, as extractors: CMake reads the languages a `project()` or
     `enable_language()` enables (it took every CMake project to be C and C++), Meson's `'fortran'`, the flang
     compiler family, and gfortran, ifx and flang in CI jobs. ctest and `meson test` run the tests of whatever their
     build system compiles, and CPM, FetchContent and Meson wraps became the build systems' own package managers.

8. **What a second new language taught.** A trial of Haskell (branch `language-trial-haskell`) found what made
   it harder than a recognition module and extractors; each fix is shared:
   - The CI layer: `$GITHUB_ENV` carries to later steps; a word that is one variable splits; a program that is a
     variable nothing sets is unknown; matrix objects are read as written.
   - Conditions are open: a profile adds its compiler (GHC) and language to their dimensions when it is imported
     (`extend`), so that its options scope `CompilerOption` facts like CMake's, and every run knows the same values. Compiler flags are requirements built once
     (`project_validator/facts/flags.py`): on a command line, as an option's value, in the build files' options for
     the language and compiler, with hints derived from the flag's spellings; the Meson and CMake settings that set
     them are the build systems' (`tools/toolchains.py`).
   - A tool run on files its job wrote, and none of the project's, covers none of the project's code; project-wide
     tools' hints name tools for every language.
   - Build outputs name the build systems that write them (several), and only the project's languages' are looked
     for; JSON nested deeper than Python recurses is read without recursion; a monorepo licensed per package warns;
     a package manager says whether its lockfiles lock from deeper in a unit (`nested_locks`).
   - A toolchain can be named by something other than its version (`ToolchainPatterns.labelled`: a Stackage
     snapshot), and `python -m project_validator.scaffold` starts a profile with everything the contract asks for.

9. **What a review of the whole found** (steps 9a–): two defects (a step conditioned on a matrix computed by an
   expression was dropped; requirements sharing a pattern shared a match cache), then what was written more than
   once: one way to say which commands a tool claims (`facts.arguments.starts_with`; `starts`, `with_option`,
   `all_of` and `any_of` in `facts.tools`); `Job` in `facts/jobs.py`, so that extractors depend on facts only and
   nothing imports inside a function to break a cycle; the extraction stages in `project_validator/extraction.py`;
   a project's files listed once. In the judging layer: a policy is a `Judge` (a protocol, so checks name the
   policy itself); what settles an answer before a policy judges it (`skipped_or_unknown`: no known tool, or an
   unknown that is not allowed) is said once, as is a policy that only advises (`policy/tooling.advised`: security
   scanning and dependency audits); `Result.skipped`; and one `combined` merges results, whether by ecosystem or
   by language and unit. A compiler's warning set, warnings as errors and hardening become requirements through
   `facts.flags` (`warning_requirements`, `errors_requirements`, `flag_requirements`), which C/C++ and Fortran both
   call, and `hardening_flags` picks a back end's subset; every answer's JSON starts with `answer_dict`. What a
   profile writes for a new language shrank: a `Practice` is what it asks (requirements, what it reads, its
   compilers) and, apart, its `Wording` (what the settings are called, how to set them, the sentences the policy's
   do not fit); a CI toolchain is `toolchain_patterns(...)`, which spells the setup action, its version input and
   the container image once for the nine languages that name theirs that way; and the scaffold writes a package
   with those filled in. Then the tidy-ups: the practices' names are a `PracticeName` enum, so a profile's own
   `WARNINGS` practice no longer collides with the constant; a `Command` resolves its `words` once when it is made,
   and `Facts.shared` holds what is made of the facts once, instead of module-level caches keyed by `id()`; a
   `Check`'s languages are always asked of its components (`languages_from`), never copied; the project map is
   `project_validator/project_map.py`; the non-recursive JSON reader is `text.check_json`. Every profile of more
   than a few hundred lines is a package laid out as the scaffold writes one: `__init__.py` recognises the
   ecosystem (its build systems, toolchain, package managers, outputs), `tools.py` holds its tools and their
   settings readers, `practices.py` its practices.

10. **What the review left open, decided** (steps 10a–10c). A set of a dimension's values that is open to every
    value not named (`if(NOT MSVC)`) is written as what it leaves out, `all but msvc` (`Applies.as_dict`): a
    compiler named later changes no other project's facts. `data-wellformed` judges the product's, docs' and
    tooling's data files by their path role, and reports a test suite's deliberately malformed data as details. The
    CI-facing checks that read the configuration themselves (`action-pinning`, `secret-scanning`, `ci-lint`) are
    questions and policies over facts; the repository-hygiene checks (`large-files`, `security-policy`,
    `status-badges`, `data-wellformed`) read the files, which is what they are about.

11. **Formats beside languages.** An ecosystem has a `kind`, language or format (see "Languages and formats");
    the registry answers `formats()`; a unit holds its `formats` beside its `languages`; a check applies to a
    project whose files are in one of its formats as to one written in one of its languages; `--answers` asks every
    question of each format. The `data` profile is the first format ecosystem: a `Parser` per format, each of the
    project's data files a `DataFile` fact parsed once at extraction, and `data-wellformed` a question and a policy
    judged per format and per unit, like every other check. `NOT_SOURCE_SUFFIXES` loses what the format claims.

12. **The ecosystem roadmap** (upstream #176, a stack of thirteen changes). Fourteen more ecosystems, most of them
    formats, which the design took without a new concept: sources recognised by name (`Ecosystem.source_names`, a
    Dockerfile); formats recognised by content (a probe may return formats, which go to the root unit); a `template`
    role, so a Helm chart's manifests are noted rather than parsed; test files written in another format
    (`TestFiles.written_in`, a chart's YAML tests); the formats' build outputs among what can be committed; a new
    aspect, `schema`, with the `schema-validation` check over it; `policy/tooling.required` beside `advised`. Shared
    at their second user: kcov, EditorConfig, the misconfiguration scanners, prettier. The tool runs recorded are
    the project's own languages' and formats', so a shared tool no longer grows every fixture's facts with each
    profile that adopts it; `--answers` lists a format's answers to the questions it is asked where a tool could give
    one.

13. **The schema practices** (#85, #86, #87, #88, #92; a stack of four changes). The tabular data profile (Frictionless
    Data Packages, a format by intent; `frictionless validate`), and three checks across the schema formats:
    `schema-declared`, a fact-based check like `data-wellformed` (a `Declares` per format in
    `facts/declaration.py`, `SchemaDeclaration` facts read at extraction; what a schema leaves out fails, a
    superseded dialect warns); `schema-examples` and `schema-compatibility`, two more aspects of the tool model
    (`examples`, `compatibility`) with advised policies, each a validator's or linter's second face (`combined`).
    The content probes learned to read a top-level key only, since a document quoting a schema (this validator's
    own facts snapshots) is no schema.

14. **The roadmap's last rows** (#89, #91, #92, #86, #10, #18, #23, #25, and the follow-ups #143 and #145 to #149; a
    stack of twelve changes). The last profile, GraphQL (a format by intent, with graphql-inspector, GraphQL Code
    Generator, graphql-schema-linter and rover); the documents of an XSD naming the schema's location; `link-check`
    and `migration-safety`, two more aspects of the tool model (`links`, `migrations`, the latter defining what it
    checks: the migrations themselves); `sanitizers` and the three build layout practices of C/C++, read from what an
    `if()` guards on, which both build evaluators now record as written. Then what building the profiles had shown:
    the shared scanners and auditors declare the languages they read; a setup action's inputs are read structurally
    for the toolchain they name (Flutter's channel); a toolchain axis may read the project's facts (the Scala
    versions a cross-build runs) and leave the OS out (the database engine versions a SQL project is tested against,
    from the service containers CI runs, now facts); a build system's outputs add to the language's own; the support
    matrix lists a shared tool once and the grid says when no ecosystem was recognised.
15. **The project corpus** (`corpus/`, one change). The fixtures are small and written to be judged; the corpus is the
    other half of the regression suite: 233 real repositories, one or more for every ecosystem profile, pinned to a
    commit. Nothing is recorded in the repository: `python -m corpus record` writes what the validator says about each
    (the project map, the results judged with `--allow-unknown`, and what strict judging adds: each check's status
    and the distinct reasons something could not be read) and `python -m corpus diff` compares two recordings; CI
    records a pull request's head and its base over the same checkouts and shows what changed, which also runs every
    parser over real inputs each time. An audit of every project's results against its repository found 556
    discrepancies, filed as upstream issues #180 to #290 and recorded, where a small project reproduces them, as
    expected-failure tests in `tests/regressions/`; the manifest names the issues open against each project, and a
    fix shows in the corpus diff of its pull request. The largest classes: a language present only in auxiliary files
    (fixtures, tooling, docs assets) becoming a product ecosystem whose failures decide the project; commands the
    readers cannot resolve (Make variables, `[[ ]]` tests, heredocs, custom shells, unknown composite actions) dropped
    silently instead of recorded as unknown; and per-ecosystem gaps in what counts as a test, a license or a coverage
    report. Two performance problems kept haskell/cabal and rust-lang/cargo out of the manifest until fixed.

`--facts` and `--answers` expose the database and the answers.
