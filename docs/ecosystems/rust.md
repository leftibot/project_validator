# Rust

Recognised by `.rs` sources and Cargo (`Cargo.toml`).

## `tests-run`

`#[test]` functions run by `cargo test`, nextest, llvm-cov or tarpaulin.

## `fuzz-testing`

cargo-fuzz and AFL.rs targets (files that call `fuzz_target!` or `afl::fuzz!`), run by a CI step `cargo fuzz run
<target>` (with or without a `+toolchain`) or `cargo afl fuzz`. proptest and quickcheck tests alone warn: they are
property-based tests, not fuzz targets.

## `coverage`

cargo-llvm-cov, cargo-tarpaulin or grcov with `--branch`. MC/DC coverage (`cargo llvm-cov --mcdc`, or
`-Zcoverage-options=mcdc` in RUSTFLAGS) is a bonus.

## `platform-matrix`

The toolchains are Rust toolchains.

## `ci-build-types`

Every OS/toolchain combination builds the debug and release profiles, each with and without sanitizers.

## `compiler-warnings`

`cargo clippy`, `-D warnings` and `clippy::pedantic`.

## `hardening`

`overflow-checks` in release builds.

## `mutation-testing`

cargo-mutants (`cargo mutants`; settings in `.cargo/mutants.toml`). `cargo mutants --in-diff changes.diff` counts as
running on the changes only.

## `code-formatting`

rustfmt: `cargo fmt --check` (with any toolchain, `cargo +nightly fmt -- --check`), `rustfmt --check`, or the
`actions-rust-lang/rustfmt` action. It has a default style, so CI enforcement alone passes; its style can be set in
`rustfmt.toml` or `.rustfmt.toml`, which applies to the crates at and below it.

## `function-limits`

lizard runs in CI with a length limit.

## `static-analysis`

`cargo clippy` (with any toolchain), or a clippy action; its lints configured in `clippy.toml` or the
`[lints.clippy]` table of Cargo.toml.

## `security-scanning`

`unsafe_code` forbidden crate-wide (in `[lints.rust]`, a crate attribute, Cargo's `rustflags` or the command line) where
cargo builds. In CI, where the tool runs (a setting alone, which nothing CI runs reads, does not count); CodeQL, GitLab
SAST or semgrep count too.

## `dependency-management`

A binary crate (`src/main.rs`, `src/bin/`, or a `[[bin]]` target) commits `Cargo.lock`; a library need not. Each crate
declares its own dependencies (`[workspace.dependencies]` only sets the versions members use), and a workspace's
`Cargo.lock` locks every member.

## `dependency-audit`

cargo audit (or `rustsec/audit-check`, `actions-rust-lang/audit`), or `cargo deny check` with its advisories check
(or `EmbarkStudios/cargo-deny-action`).

## `license`

`[package] license` in `Cargo.toml`.

## `committed-artifacts`

A top-level `target/`.

## `vcs-ignore`

`/target`.
