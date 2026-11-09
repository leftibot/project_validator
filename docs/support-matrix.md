# Support matrix

What project_validator checks for each ecosystem, and the tools it recognises for it. Generated: regenerate with
`python -m project_validator --support-matrix > docs/support-matrix.md` (a test fails while this page is stale). A
cell lists the tools the check recognises; `✓` means the check applies without naming tools; `—` means it does not
apply.

| Check | C/C++ | .NET | Fortran | Go | JavaScript/TypeScript | JVM | PHP | Python | Ruby | Rust | Swift |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `ci-build-types` | ✓ | — | ✓ | — | — | — | — | — | — | ✓ | ✓ |
| `code-formatting` | clang-format | dotnet format, CSharpier, Fantomas | fprettify | gofmt | prettier, deno fmt, oxfmt, dprint, biome | Spotless, fmt-maven-plugin, google-java-format, ktfmt, ktlint | PHP-CS-Fixer, PHP_CodeSniffer, Pint | ruff format, black | RuboCop, Standard, syntax_tree | rustfmt | swift-format, SwiftFormat |
| `committed-artifacts` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `compiler-warnings` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `coverage` | gcovr, lcov, gcov, llvm-cov, gcc -fcondition-coverage, gcc -fpath-coverage, clang -fcoverage-mcdc | coverlet, Microsoft code coverage | gcovr, lcov, gcov | go test -cover | c8, nyc, Jest, Vitest, deno test, node --test, bun test | JaCoCo, Kover | PHPUnit | coverage.py, pytest-cov | SimpleCov | cargo-llvm-cov, cargo-tarpaulin, grcov, rustc MC/DC | swift test, Xcode |
| `cxx-extensions` | ✓ | — | ✓ | — | — | — | — | — | — | — | — |
| `dependency-audit` | — | NuGet audit of every package, dotnet list package --vulnerable, GitLab Dependency Scanning, osv-scanner, trivy, snyk | — | govulncheck, GitLab Dependency Scanning, osv-scanner, trivy, snyk | npm audit, pnpm audit, yarn npm audit, bun audit, yarn audit, GitLab Dependency Scanning, osv-scanner, trivy, snyk | OWASP dependency-check, GitLab Dependency Scanning, osv-scanner, trivy, snyk | composer audit, roave/security-advisories, GitLab Dependency Scanning, osv-scanner, trivy, snyk | pip-audit, safety, GitLab Dependency Scanning, osv-scanner, trivy, snyk | bundler-audit, GitLab Dependency Scanning, osv-scanner, trivy, snyk | cargo audit, cargo deny, GitLab Dependency Scanning, osv-scanner, trivy, snyk | GitLab Dependency Scanning, osv-scanner, trivy, snyk |
| `dependency-management` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `function-limits` | clang-tidy's readability-function-size, lizard | lizard | lizard | golangci-lint's funlen, lizard | eslint's max-lines-per-function, lizard | Checkstyle's MethodLength, detekt's LongMethod, lizard | PHPMD's ExcessiveMethodLength, lizard | lizard | RuboCop's Metrics/MethodLength, lizard | lizard | SwiftLint's function_body_length, lizard |
| `hardening` | ✓ | — | ✓ | ✓ | — | — | — | — | — | ✓ | ✓ |
| `platform-matrix` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `security-scanning` | CodeQL, GitLab SAST, semgrep | .NET security analyzers, CodeQL, GitLab SAST, semgrep | — | gosec, golangci-lint's gosec, CodeQL, GitLab SAST, semgrep | eslint-plugin-security, CodeQL, GitLab SAST, semgrep | Find Security Bugs, PMD security rules, CodeQL, GitLab SAST, semgrep | Psalm taint analysis, phpcs-security-audit, GitLab SAST, semgrep | bandit, ruff's bandit rules, CodeQL, GitLab SAST, semgrep | brakeman, RuboCop Security cops, CodeQL, GitLab SAST, semgrep | unsafe_code forbidden, CodeQL, GitLab SAST, semgrep | CodeQL, GitLab SAST, semgrep |
| `static-analysis` | clang-tidy, cppcheck | Roslynator, SonarAnalyzer, StyleCop.Analyzers, Meziantou.Analyzer, FSharpLint | fortitude | golangci-lint | eslint, oxlint, deno lint, biome | SpotBugs, PMD, Checkstyle, detekt, Error Prone | PHPStan, Psalm, PHPMD, Phan | ruff check, pylint, flake8 | RuboCop, Standard, Reek | clippy | SwiftLint |
| `tests-run` | ctest, meson test | dotnet test | ctest, meson test, fpm test | go test | a JavaScript test runner | mvn test or gradle test | phpunit, pest or composer test | pytest, unittest, nox | rspec, rake test or rails test | cargo test | swift test or xcodebuild test |
| `type-checking` | — | — | — | — | tsc, deno check | — | PHPStan, Psalm | mypy, pyright, pyrefly, ty | Sorbet, Steep | — | — |
| `vcs-ignore` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `warnings-as-errors` | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ | — | — | — | ✓ |

Checks of every project, whatever its languages: `action-pinning`, `ci-lint`, `ci-present`, `copy-paste-detection`, `data-wellformed`, `dependency-updates`, `large-files`, `license`, `secret-scanning`, `security-policy`, `status-badges`.
