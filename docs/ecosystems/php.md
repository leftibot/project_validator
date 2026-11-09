# PHP

Recognised by `.php` sources and Composer (`composer.json`). The Composer scripts CI runs (`composer test`) count as
CI configuration.

## `tests-run`

`*Test.php` files with PHPUnit test cases or Pest tests, run by phpunit, pest, paratest or `composer test`, in CI or
the Composer scripts it runs.

## `coverage`

PHPUnit (or Pest, or ParaTest) reporting coverage with `--path-coverage` (or `pathCoverage="true"` in the
configuration it reads, with a report), which reports branch and path coverage together, so it also earns the path
bonus. Line coverage alone counts no branches.

## `platform-matrix`

The toolchains are PHP versions.

## `compiler-warnings`

Every error is reported while testing: `error_reporting` `-1` or `E_ALL` in `phpunit.xml`, `php.ini` or CI.

## `warnings-as-errors`

PHPUnit's `failOnWarning`, `failOnNotice` and `failOnDeprecation` (or `failOnAllIssues`).

## `type-checking`

PHPStan or Psalm, also through the Composer scripts CI runs. Strict mode is a bonus: PHPStan `level` 8 or higher
(in its configuration or `--level`), or Psalm `errorLevel` 1 or 2.

## `mutation-testing`

Infection (`infection` or `vendor/bin/infection`, also through a Composer script; settings in `infection.json5`,
`infection.json`, or either with a `.dist` suffix). `--git-diff-filter` or `--git-diff-lines` counts as running on the
changes only.

## `code-formatting`

`php-cs-fixer check` (or `fix --dry-run`), phpcs or `pint --test`, in CI or the Composer scripts it runs; phpcbf
and `php-cs-fixer fix` only rewrite files. They have a default style, so CI enforcement alone passes.

## `function-limits`

lizard runs in CI with a length limit, or PHPMD runs with its `codesize` rules (`ExcessiveMethodLength`), named on
the command line or used by its rule set (`phpmd.xml`, or the rule set the command names) without excluding the rule.

## `static-analysis`

PHPStan, Psalm, PHPMD or Phan.

## `security-scanning`

Psalm's taint analysis (`--taint-analysis`, or `runTaintAnalysis` in `psalm.xml`), or phpcs with phpcs-security-audit.
CodeQL does not analyse PHP. In CI, where the tool runs (a setting alone, which nothing CI runs reads, does not count);
CodeQL, GitLab SAST or semgrep count too.

## `dependency-management`

Dependencies required in `composer.json` (besides `php` and extensions) are locked by a committed `composer.lock`,
unless the package is a `"type": "library"`.

## `dependency-audit`

`composer audit`, or `roave/security-advisories` required where CI installs the packages (`composer install` or
`update`), since it stops Composer installing a vulnerable version.

## `license`

`license` in `composer.json`.

## `committed-artifacts`

A top-level `vendor/`, `.phpunit.cache/` and `.phpunit.result.cache`.

## `vcs-ignore`

`vendor/`.
