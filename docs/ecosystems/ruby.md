# Ruby

Recognised by `.rb` sources and Bundler (`Gemfile`). The Rakefile counts as CI configuration when CI runs rake.

## `tests-run`

`spec/**/*_spec.rb` or `test/**/*_test.rb` files run by rspec, `rake test` / `spec` or `rails test`, or by the
Rakefile's test tasks when CI runs rake.

## `coverage`

SimpleCov with `enable_coverage :branch` (in `.simplecov` or a test helper), when CI runs the tests (`rspec`, `rake`,
`rails test`, also through `bundle exec`).

## `platform-matrix`

The toolchains are Ruby versions and implementations.

## `compiler-warnings`

Ruby's warnings are on while testing (`ruby -w`, `RUBYOPT=-w`, `$VERBOSE = true`, RSpec's `--warnings` /
`config.warnings`, or a test task's `warning = true`) and RuboCop or Standard runs.

## `type-checking`

Sorbet (`srb tc`) or Steep (`steep check`). Strict mode is a bonus: Sorbet's `# typed: strict` sigils, or
`D::Ruby.strict` in a Steepfile.

## `mutation-testing`

mutant (`mutant run`, also as `bundle exec mutant run`; settings in `.mutant.yml`, `mutant.yml` or
`config/mutant.yml`). `mutant run --since <revision>` counts as running on the changes only.

## `code-formatting`

RuboCop (without `-a` or `-A`), Standard (without `--fix`) or `stree check`, run directly, through
`bundle exec`, or as the Rake task a Rakefile defines (`RuboCop::RakeTask`, `standard/rake`) when CI runs it or the
default task that depends on it. They have a default style, so CI enforcement alone passes.

## `function-limits`

lizard runs in CI with a length limit, or RuboCop runs with `Metrics/MethodLength` on (it is on by default;
`Enabled: false` on the cop or on the `Metrics` department turns it off). Standard turns the Metrics cops off.

## `static-analysis`

RuboCop or Standard (without autocorrecting, run directly or as the Rake task a Rakefile defines), or Reek.

## `security-scanning`

brakeman, or RuboCop linting, whose Security cops are on by default. In CI, where the tool runs (a setting alone, which
nothing CI runs reads, does not count); CodeQL, GitLab SAST or semgrep count too.

## `dependency-management`

Gems in the `Gemfile` (or a gemspec's dependencies) are locked by a committed `Gemfile.lock`, unless the project is a
gem (has a gemspec).

## `dependency-audit`

bundler-audit.

## `license`

The gemspec's `license` or `licenses`.

## `committed-artifacts`

`.bundle/`, `*.gem`, and a top-level `coverage/` or `pkg/`. A committed `vendor/bundle/` is reported by
`dependency-management`.

## `vcs-ignore`

`.bundle/` or `vendor/bundle/`.
