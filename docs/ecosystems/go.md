# Go

Recognised by `.go` sources and Go modules (`go.mod`).

## `tests-run`

`Test` functions in `*_test.go` files run by `go test`.

## `coverage`

Go's tools measure statements only, so Go needs statement coverage: `go test` (or `go build`) with `-cover`,
`-coverprofile`, `-covermode` or `-coverpkg`.

## `platform-matrix`

The toolchains are Go versions.

## `compiler-warnings`

`go vet` and staticcheck (golangci-lint runs both).

## `hardening`

Programs are built as position-independent executables (`-buildmode=pie`, not the default on Linux); a module with no
`package main` is skipped.

## `mutation-testing`

gremlins (`gremlins unleash`, also as `go run github.com/go-gremlins/gremlins/cmd/gremlins@v0.5.0 unleash`; settings in
`.gremlins.yaml`) or go-mutesting. `gremlins unleash --diff <branch>` counts as running on the changes only.

## `code-formatting`

gofmt, gofumpt or goimports listing what they would change (`-l` or `-d`, which CI fails on:
`test -z "$(gofmt -l .)"`), or `golangci-lint fmt --diff`. They have one style, so CI enforcement alone passes;
`gofmt -w` and `go fmt` only rewrite files.

## `function-limits`

lizard runs in CI with a length limit, or golangci-lint runs with `funlen` enabled in its configuration (in
`linters.enable`, or all linters, and not in `linters.disable`). `funlen` enabled while CI does not run golangci-lint
warns.

## `static-analysis`

golangci-lint (`golangci-lint run`, `go run …/golangci-lint@v… run`, or the `golangci/golangci-lint-action`
action) with linters enabled beyond its defaults (`linters.enable`, `enable-all` or `default: all` in a
`.golangci.yml`, `.toml` or `.json`).

## `security-scanning`

gosec, or golangci-lint with gosec enabled in its configuration. In CI, where the tool runs (a setting alone, which
nothing CI runs reads, does not count); CodeQL, GitLab SAST or semgrep count too.

## `dependency-management`

A module that requires others commits `go.sum`. `go mod vendor` output is not third-party code committed by hand.

## `dependency-audit`

govulncheck, run directly, as `go run golang.org/x/vuln/cmd/govulncheck@…`, or as `golang/govulncheck-action`.

## `committed-artifacts`

`*.test`, `*.out` and a top-level `bin/`.

## `vcs-ignore`

`*.test` or `*.out`.
