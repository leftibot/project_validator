# C/C++

Recognised by `.c`, `.cpp`, `.cc`, `.cxx`, `.hpp`, `.ixx`, `.cppm` and similar sources, and by CMake (`CMakeLists.txt`)
or Meson (`meson.build`). A project is judged by the rules of the build system it uses; one using neither is judged as
a CMake project.

## `tests-run`

With CMake: `enable_testing()` or `include(CTest)` is called, tests are registered (`add_test`, `*_discover_tests`,
...) and CI runs `ctest` (or `cmake --build … --target test`, or `cmake --workflow`); with `--build`, the project is
really configured and built, and `ctest` must list at least one test (a build that cannot run is unknown). With Meson:
`test()` is called in a `meson.build` and CI runs `meson test` (or ninja's `test` target).

## `fuzz-testing`

libFuzzer targets (files defining `LLVMFuzzerTestOneInput`) and AFL++ targets (`__AFL_LOOP`), run by a CI step that
passes a libFuzzer option to a binary (`./fuzz_tester -max_total_time=30`, a heuristic), by `afl-fuzz` (whose target, the words
after `--`, is not a `dotnet` program or a `.dll`), or by `ctest` when a CMake `add_test` passes a libFuzzer option to
its command (a test that only replays crash files does not count). The `ctest` command's `-R`/`-L` and `-E`/`-LE`
regexes are matched against the test's name. This is a heuristic: a fuzz test registered behind an option CI does not
turn on (`if(ENABLE_FUZZING)`) is still counted, and the run is credited to the CMake files' unit. RapidCheck tests alone warn: they are property-based tests, not
fuzz targets.

## `coverage`

A coverage tool CI runs, reporting branches: gcovr with any report but the default text one (`--xml`, `--html`,
`--json`, `--sonarqube`, `--print-summary`, `--txt-metric branch`, also in `gcovr.cfg`), lcov or genhtml with
`branch_coverage=1` (also in `.lcovrc`), `gcov -b`, or `llvm-cov report`, `export` or `show -show-branches`. Path or
MC/DC coverage is a bonus: gcov `--conditions` or `--prime-paths`, lcov `--mcdc-coverage`, `llvm-cov show -show-mcdc`,
or the instrumentation `-fcondition-coverage`, `-fpath-coverage` or `-fcoverage-mcdc` on a command line, in an
environment variable, or in the CMake files a CI `cmake` configuration reads (matched in their text).

## `platform-matrix`

The toolchains are compilers. A CI job that names no compiler counts with its runner's default compiler (gcc on Linux,
AppleClang on macOS, MSVC on Windows), unless it only runs another ecosystem's tools.

## `ci-build-types`

Every OS/compiler combination builds Debug and Release, each with and without sanitizers.

## `compiler-warnings`

`-Wall -Wextra -Wpedantic -Wshadow -Wconversion`, plus `/W4` and `/permissive-` when MSVC is in CI.

## `warnings-as-errors`

`-Werror`, `/WX` or `COMPILE_WARNING_AS_ERROR` (Meson: `werror=true`) is enabled in at least one configuration.

## `cxx-extensions`

`CMAKE_CXX_EXTENSIONS` (or `CMAKE_C_EXTENSIONS` for C) is turned off, or with Meson `cpp_std` (`c_std`) names a
standard such as `c++20` rather than `gnu++20`, so `-std=c++NN` is used rather than `-std=gnu++NN`.

## `hardening`

`_FORTIFY_SOURCE`, `-fstack-protector-strong`, `-fcf-protection`, `-fstack-clash-protection` and
`_GLIBCXX_ASSERTIONS` or `_LIBCPP_HARDENING_MODE` (or GCC's `-fhardened`), plus `/sdl /guard:cf /DYNAMICBASE
/CETCOMPAT` when MSVC is in CI. Warns listing what is missing.

## `mutation-testing`

Mull (`mull-runner` or `mull-cxx`, settings in `mull.yml`; a build with its compiler plugin only embeds the mutants,
so it is not a run) or dextool (`dextool mutate`, settings in `.dextool_mutate.toml`). No changes-only mode is
recognised for either.

## `code-formatting`

The style is defined in a `.clang-format` (or `_clang-format`), at or above the code, and CI checks it:
`clang-format --dry-run -Werror` (or `-n --Werror`, also through `xargs`), `git clang-format --diff`, run-clang-format,
the `DoozyX/clang-format-lint-action` or `jidicula/clang-format-action` action, or the clang-format pre-commit hook
when CI runs pre-commit. `clang-format -i` enforces it only where the job then fails on a change
(`git diff --exit-code`) or commits it.

## `security-scanning`

No security lints of its own here: CodeQL, GitLab SAST or semgrep in CI.

## `function-limits`

lizard runs in CI with a length limit (`-L`, `--length`, `-T length=` or `-T nloc=`), or clang-tidy runs (directly,
or through `CMAKE_CXX_CLANG_TIDY`) with a `.clang-tidy` that enables `readability-function-size` with a positive
`LineThreshold` or `StatementThreshold`. A `.clang-tidy` that sets the limit while nothing runs clang-tidy warns; one
that cannot be read makes the answer unknown.

## `static-analysis`

Both clang-tidy and cppcheck: run directly (`clang-tidy`, `run-clang-tidy`, `cppcheck`), through the
`cpp-linter/cpp-linter-action`, `ZedThree/clang-tidy-review` or `deep5050/cppcheck-action` actions, or by a build CI
configures with `CMAKE_CXX_CLANG_TIDY` / `CMAKE_CXX_CPPCHECK` (on the `cmake` command line, or in the CMake files,
target properties or presets), or a custom target CI builds (`cmake --build build --target lint`) that runs either.
clang-tidy needs its checks chosen in a `.clang-tidy`.

## `dependency-management`

CPM, FetchContent, vcpkg (`vcpkg.json`), Conan (`conanfile.txt` / `conanfile.py`) or Meson wraps
(`subprojects/*.wrap`).

## `committed-artifacts`

Object files and libraries (`*.o`, `*.obj`, `*.a`, `*.lib`, `*.so`, `*.dylib`, `*.dll`), `*.exe`, `*.pdb`,
`CMakeCache.txt`, `CMakeFiles/`, `CMakeUserPresets.json`, and a top-level `build/`, `out/` or `builddir/`.

## `vcs-ignore`

`build/` or `out/`.
