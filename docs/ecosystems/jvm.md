# JVM

Java and Kotlin, recognised by `.java` and `.kt` sources and Maven (`pom.xml`) or Gradle builds. The Maven or Gradle
build counts as CI configuration when CI runs it (`mvn verify`, `gradle check`), since that is where its plugins are
wired in.

## `tests-run`

`@Test` methods or Kotest specs under `src/test/java` or `src/test/kotlin`, run by `mvn test` / `verify` or
`gradle test` / `check` / `build`.

## `coverage`

JaCoCo (`jacoco:report`, `jacocoTestReport`, or `jacoco-maven-plugin` with its `report` goal bound when CI runs
`mvn verify`) or Kover (a `kover…Report` task, or its plugin when CI runs `gradle check`).

## `platform-matrix`

The toolchains are JDK versions.

## `compiler-warnings`

javac's `-Xlint:all`; a Kotlin-only project passes on Kotlin's default warnings.

## `warnings-as-errors`

`-Werror` for javac or kotlinc, or Kotlin's `allWarningsAsErrors`.

## `mutation-testing`

PIT, run by `mvn pitest:mutationCoverage` or the `pitest` Gradle task, or by a verification (`mvn verify`,
`gradle check`) that brings in the `pitest-maven` plugin (with a `mutationCoverage` goal bound) or the
`info.solidsoft.pitest` Gradle plugin. `pitest:scmMutationCoverage`, or `-DwithHistory` (Maven) or
`--features=+history` (Gradle), counts as running on the changes only.

## `code-formatting`

Spotless (`spotless:check` or `spotlessCheck`, or the plugin bound to `check` in pom.xml or applied in a Gradle
build, run by `mvn verify` or `gradle check`) and fmt-maven-plugin for Java and Kotlin or Java; google-java-format
(`--set-exit-if-changed`) for Java; ktfmt (`--set-exit-if-changed`) and ktlint (without `-F`, or `ktlintCheck`) for
Kotlin. They have a default style, so CI enforcement alone passes.

## `function-limits`

Java: lizard runs in CI with a length limit, or Checkstyle runs with a configuration that has the `MethodLength`
module. Kotlin: lizard, or detekt runs with `LongMethod` active (it is on by default; `active: false` on the rule or
on the `complexity` rule set turns it off).

## `static-analysis`

SpotBugs (Java and Kotlin); PMD, Checkstyle and Error Prone (Java); detekt (Kotlin). Each runs by its goal or
task (`spotbugs:check`, `pmd:check`, `checkstyleMain`, `detekt`), or by the plugin a build's verification brings in
(bound to `check` in pom.xml, or applied in a Gradle script or convention plugin, run by `mvn verify` or `gradle
check`). Error Prone, a compiler plugin, runs on every build that compiles.

## `security-scanning`

SpotBugs with Find Security Bugs, or PMD with its `category/java/security.xml` rules, where the build runs them. In CI,
where the tool runs (a setting alone, which nothing CI runs reads, does not count); CodeQL, GitLab SAST or semgrep count
too.

## `dependency-management`

Dependencies declared in `pom.xml` are verified when Maven runs with `--strict-checksums` (in `.mvn/maven.config`,
or on a CI command line); those declared in a Gradle build by a committed `gradle/verification-metadata.xml` or
`gradle.lockfile`.

## `dependency-audit`

OWASP dependency-check (`dependency-check:check`, `dependency-check-maven` bound to `check` or `aggregate` and run
by `mvn verify`, `dependencyCheckAnalyze`, its CLI, or its action). The Gradle plugin adds no task to `check`.

## `committed-artifacts`

`*.class`, plus Maven's `target/` or Gradle's `build/` and `.gradle/`.

## `vcs-ignore`

Maven's `target/` or Gradle's `build/`.
