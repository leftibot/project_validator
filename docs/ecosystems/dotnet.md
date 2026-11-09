# .NET

C# and F#, recognised by `.cs` and `.fs` sources and MSBuild project and solution files. Project files and
`Directory.Build.props` count as CI configuration when CI builds.

## `tests-run`

A test project referencing `Microsoft.NET.Test.Sdk` (or `MSTest.Sdk`) with `[Fact]`, `[Test]` or `[TestMethod]`
tests, run by `dotnet test`.

## `coverage`

coverlet (`dotnet test --collect "XPlat Code Coverage"`, `CollectCoverage=true` on the command line or in the MSBuild
settings `dotnet test` builds with, a `.runsettings` file it is given that adds the collector, or the `coverlet`
console tool), `dotnet-coverage collect` or `dotnet test --coverage`.

## `platform-matrix`

The toolchains are .NET SDK versions.

## `compiler-warnings`

C# projects set `AnalysisMode` (or `AnalysisLevel`) to Recommended or All, `EnforceCodeStyleInBuild` and `Nullable`
`enable` in a project file or `Directory.Build.props`; F#-only projects turn on more compiler warnings (`<WarnOn>`,
`--warnon:`).

## `warnings-as-errors`

`TreatWarningsAsErrors` or `-warnaserror`.

## `mutation-testing`

Stryker.NET (`dotnet stryker`; settings in `stryker-config.json`). `dotnet stryker --since` (or `--since:<branch>`)
counts as running on the changes only.

## `code-formatting`

`dotnet format --verify-no-changes` (style in `.editorconfig`) and `csharpier check` (or `--check`) for C#;
`fantomas --check` for F#; run directly or as `dotnet` local tools. They have a default style, so CI enforcement alone
passes.

## `function-limits`

lizard runs in CI with a length limit. lizard does not measure F#, and no known tool limits the length of F#
functions, so F# is skipped.

## `static-analysis`

For C#, an analyzer package beyond the SDK's own (Roslynator, SonarAnalyzer, StyleCop.Analyzers or
Meziantou.Analyzer) referenced by a project or `Directory.*.props`, which runs when CI builds (`dotnet build`, `test`,
`pack`, `publish`, `msbuild`); for F#, FSharpLint (`dotnet fsharplint lint`).

## `security-scanning`

The analyzers' Security category (`AnalysisModeSecurity`, or `category-Security` severity warning or error in
`.editorconfig` or `.globalconfig`), or Security Code Scan, when CI builds. In CI, where the tool runs (a setting alone,
which nothing CI runs reads, does not count); CodeQL, GitLab SAST or semgrep count too.

## `dependency-management`

NuGet `PackageReference`s are locked by committed `packages.lock.json` files.

## `dependency-audit`

`NuGetAuditMode` `all` in the MSBuild files, when CI restores or builds (restoring then audits transitive packages
too), or `dotnet list package --vulnerable`.

## `license`

`PackageLicenseExpression`.

## `committed-artifacts`

`obj/`, `*.dll`, `*.pdb` and `*.nupkg`.

## `vcs-ignore`

`bin/` or `obj/`.

`hardening` is not judged for .NET yet.
