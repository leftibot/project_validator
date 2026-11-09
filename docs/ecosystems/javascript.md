# JavaScript/TypeScript

Recognised by `.js`, `.ts` and related sources, `package.json` or `deno.json`. The package scripts CI runs
(`npm test`, `npm run lint`, Deno tasks) count as CI configuration.

## `tests-run`

`*.test.*`, `*.spec.*`, `*_test.*` or `__tests__/` files run by jest, vitest, mocha, ava, `node --test`,
`deno test`, `bun test`, playwright or `npm test`.

## `coverage`

c8, nyc, Jest (`--coverage`, or `collectCoverage: true` in the configuration it reads, or package.json's `jest`), Vitest
(`--coverage`, or coverage `enabled: true` in the configuration it reads), `deno test --coverage` or
`node --test --experimental-test-coverage`, run by CI directly, through `npx` and the other package runners, or
through the package scripts it runs. `bun test --coverage` counts lines only.

## `platform-matrix`

The toolchains are Node.js, Deno or Bun versions.

## `compiler-warnings`

A linter runs: eslint, `biome lint` / `biome ci`, or `deno lint`.

## `warnings-as-errors`

A lint warning fails CI: `eslint --max-warnings 0`, `biome ci` or `--error-on-warnings`, or `deno lint`.

## `type-checking`

`tsc` or `vue-tsc` (JavaScript with `checkJs`), or `deno check` / `deno test`, also through the package scripts
CI runs. Strict mode is a bonus: `"strict": true` or `@tsconfig/strictest` in a `tsconfig.json`, or Deno, strict by
default.

## `mutation-testing`

StrykerJS (`stryker run`, also as `npx stryker run` or a package script; settings in `stryker.config.json`,
`.js`, `.mjs` or `.cjs`, or `stryker.conf.json` or `.js`). `stryker run --incremental` counts as
running on the changes only.

## `code-formatting`

`prettier --check` (or `-l`; settings in a `.prettierrc*`, `prettier.config.*` or the `prettier` key of
package.json), `biome format`, `biome check` or `biome ci` (without `--write`), `deno fmt --check`, `dprint check` or
`oxfmt --check`, in CI or the package scripts and Deno tasks it runs. They have a default style, so CI enforcement
alone passes.

## `function-limits`

lizard runs in CI with a length limit, or eslint runs with `max-lines-per-function` on (not `"off"` or `0`) in its
configuration. The rule on while CI does not run eslint warns.

## `static-analysis`

eslint (or `next lint`), oxlint, `biome lint` / `check` / `ci` or `deno lint`, in CI, a pre-commit hook CI runs,
or the package scripts CI runs.

## `security-scanning`

eslint with `eslint-plugin-security` (or `@microsoft/eslint-plugin-sdl`) in its configuration. In CI, where the tool
runs (a setting alone, which nothing CI runs reads, does not count); CodeQL, GitLab SAST or semgrep count too.

## `dependency-management`

Dependencies declared in `package.json` (or `imports` in `deno.json`) are locked by a committed `package-lock.json`,
`npm-shrinkwrap.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lock`, `bun.lockb` or `deno.lock`, libraries included.

## `dependency-audit`

`npm audit` (not `npm audit signatures`), `pnpm audit`, `yarn npm audit` / `yarn audit` or `bun audit`.

## `license`

`license` in `package.json`.

## `committed-artifacts`

`node_modules/`, a top-level `coverage/` and `*.tsbuildinfo` (not `dist/`, which a JavaScript GitHub Action commits).

## `vcs-ignore`

`node_modules/`.
