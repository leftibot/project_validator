# Swift

Recognised by `.swift` sources, SwiftPM (`Package.swift`) or Xcode projects. `Package.swift` and the Xcode build
settings and schemes count as CI configuration.

## `tests-run`

`XCTestCase` classes or Swift Testing `@Test` functions, run by `swift test` or `xcodebuild test`.

## `coverage`

Swift's coverage counts regions, not branches, so Swift needs region coverage: `swift test --enable-code-coverage`,
or `xcodebuild test` with `-enableCodeCoverage YES` or a scheme (or test plan) that turns code coverage on.

## `platform-matrix`

The toolchains are Swift or Xcode versions.

## `ci-build-types`

Every OS/toolchain combination builds debug and release (SwiftPM's `-c release` or its debug default, or
xcodebuild's `-configuration`), each with and without sanitizers.

## `compiler-warnings`

SwiftLint runs and concurrency is checked completely: Swift 6 language mode, `-strict-concurrency=complete`,
`StrictConcurrency`, or Xcode's `SWIFT_STRICT_CONCURRENCY = complete`.

## `warnings-as-errors`

`-warnings-as-errors`, SwiftPM's `treatAllWarnings(as: .error)` or Xcode's `SWIFT_TREAT_WARNINGS_AS_ERRORS = YES`.

## `hardening`

Releases keep the language's runtime safety checks: no build uses `-Ounchecked` or unchecked exclusivity.

## `mutation-testing`

Muter (`muter`, settings in `muter.conf.yml`).

## `code-formatting`

`swift format lint --strict` (or `swift-format lint -s`; plain `lint` only warns) or `swiftformat --lint`.
They have a default style, so CI enforcement alone passes; `swift format -i` and `swiftformat` only rewrite files.

## `security-scanning`

No security lints of its own here: CodeQL, GitLab SAST or semgrep in CI.

## `function-limits`

lizard runs in CI with a length limit, or SwiftLint runs with `function_body_length` on (it is on by default;
`disabled_rules` naming it, or `only_rules` leaving it out, turns it off).

## `static-analysis`

SwiftLint (`swiftlint`, not fixing), or its build tool plugin when CI builds the package.

## `dependency-management`

An application (an Xcode project, or a package with an executable) commits `Package.resolved`.

## `dependency-audit`

Swift has no audit tool of its own, so only the multi-ecosystem scanners (osv-scanner, `trivy fs`, `snyk test`) count.

## `committed-artifacts`

SwiftPM's `.build/`, Xcode's `xcuserdata/` and `DerivedData/`.

## `vcs-ignore`

SwiftPM's `.build/`, or Xcode's `xcuserdata/` or `DerivedData/`.
