"""Command line interface: `python3 -m project_validator [options] [path]`."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from project_validator import pretty, yaml_support
from project_validator.core import DEFAULT_MAX_FILE_SIZE, Check, Context, Options, Project
from project_validator.ecosystems import applies_to
from project_validator.grid import render_grid
from project_validator.plugins import PluginError, discover
from project_validator.questions.answers import answers
from project_validator.runner import Report, SelectionError, run_checks, select, succeeded
from project_validator.support_matrix import as_dict, render, support_matrix

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2


def _names(values: list[str]) -> list[str]:
    return [name.strip() for value in values for name in value.split(",") if name.strip()]


def _relative_directory(value: str) -> PurePosixPath:
    return PurePosixPath(Path(value).as_posix())


def _mebibytes(value: str) -> int:
    """A positive size in MiB, as bytes."""
    try:
        size = float(value)
    except ValueError:
        size = 0
    if not size > 0:
        raise argparse.ArgumentTypeError(f"expected a positive number of MiB, got {value!r}")
    return int(size * 1024 * 1024)


# What --map, --facts and --answers print.
_DUMPS = {
    "map": "the detected project structure",
    "facts": "the facts found about the project",
    "answers": "the answers to every question about the project",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="project_validator", description="Validate a project's build, CI and tooling against best practices."
    )
    parser.add_argument("path", nargs="?", default=".", type=Path, help="project to validate (default: .)")
    _add_listing_options(parser)
    parser.add_argument("--only", action="append", default=[], metavar="CHECKS", help="run only these checks")
    parser.add_argument("--skip", action="append", default=[], metavar="CHECKS", help="do not run these checks")
    _add_output_options(parser)
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        type=_relative_directory,
        metavar="DIR",
        help="leave DIR, relative to the project, out of the validation (e.g. test fixtures)",
    )
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    parser.add_argument(
        "--plugin-dir", action="append", default=[], type=Path, metavar="DIR", help="load extra plugins from DIR/*.py"
    )
    _add_check_options(parser)
    return parser


def _add_listing_options(parser: argparse.ArgumentParser) -> None:
    """The options that print information about the validator or the project and exit."""
    parser.add_argument(
        "--support-matrix",
        action="store_true",
        help="print what each check recognises for each ecosystem (markdown; as JSON with --format json) and exit",
    )
    parser.add_argument("--list", action="store_true", help="list the checks (as JSON: with what each applies to)")
    for name, what in _DUMPS.items():
        parser.add_argument(f"--{name}", action="store_true", help=f"print {what} as JSON and exit")


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    """The options that choose how the results are printed."""
    parser.add_argument(
        "--format",
        choices=("text", "json", "markdown"),
        default="text",
        help="output format (markdown: a grid of checks by ecosystem, for a job summary)",
    )
    parser.add_argument(
        "--color", choices=("auto", "always", "never"), default="auto", help="color the text output (needs rich)"
    )


def _add_check_options(parser: argparse.ArgumentParser) -> None:
    """The options that change what some checks do (see `Options`)."""
    parser.add_argument("--build", action="store_true", help="configure and build the project to list its tests")
    parser.add_argument("--cmake", default="cmake", help="cmake executable used by --build")
    parser.add_argument("--ctest", default="ctest", help="ctest executable used by --build")
    parser.add_argument(
        "--max-file-size",
        type=_mebibytes,
        default=DEFAULT_MAX_FILE_SIZE,
        metavar="MIB",
        help="committed files larger than this belong in Git LFS or DVC (default: 5)",
    )
    parser.add_argument(
        "--allow-official-tags", action="store_true", help="let actions from actions/ and github/ be pinned to tags"
    )
    parser.add_argument(
        "--allow-unknown",
        action="store_true",
        help="judge by what could be read when an answer depends on configuration that could not be (else an error)",
    )


def _options(arguments: argparse.Namespace) -> Options:
    return Options(
        build=arguments.build,
        cmake=arguments.cmake,
        ctest=arguments.ctest,
        max_file_size=arguments.max_file_size,
        allow_official_tags=arguments.allow_official_tags,
        allow_unknown=arguments.allow_unknown,
    )


def _format_text(reports: list[Report]) -> str:
    lines: list[str] = []
    for report in reports:
        lines.append(f"[{report.result.status}] {report.check.name}: {report.result.message}")
        lines.extend(f"    {detail}" for detail in report.result.details)
    return "\n".join(lines)


def _format_json(reports: list[Report]) -> str:
    return json.dumps(
        [
            {
                "check": report.check.name,
                "status": str(report.result.status),
                "message": report.result.message,
                "details": list(report.result.details),
            }
            for report in reports
        ],
        indent=2,
    )


def _use_color(choice: str) -> bool:
    if choice == "auto":
        return sys.stdout.isatty() and "NO_COLOR" not in os.environ
    return choice == "always"


def _print_text(reports: list[Report], color: bool) -> None:
    if color and pretty.available():
        pretty.print_reports(reports, sys.stdout)
        return
    if color:
        print("note: install rich for colored output", file=sys.stderr)
    print(_format_text(reports))


def _format_list(checks: Sequence[Check]) -> str:
    width = max((len(c.name) for c in checks), default=0)
    return "\n".join(f"{c.name:<{width}}  {c.description}" for c in checks)


def check_list(checks: Sequence[Check]) -> list[dict[str, object]]:
    """Each check and the ecosystems it judges; an empty `applies_to` means every project."""
    return [{"check": c.name, "description": c.description, "applies_to": list(applies_to(c))} for c in checks]


def _print_listing(checks: Sequence[Check], arguments: argparse.Namespace) -> None:
    """What --list or --support-matrix prints."""
    as_json = arguments.format == "json"
    if arguments.list:
        print(json.dumps(check_list(checks), indent=2) if as_json else _format_list(checks))
        return
    matrix = support_matrix(checks)
    print(json.dumps(as_dict(matrix), indent=2) if as_json else render(matrix), end="\n" if as_json else "")


def _usage_error(parser: argparse.ArgumentParser, message: str) -> int:
    print(f"{parser.prog}: error: {message}", file=sys.stderr)
    return EXIT_USAGE


def _print_reports(reports: list[Report], arguments: argparse.Namespace) -> None:
    if arguments.format == "json":
        print(_format_json(reports))
    elif arguments.format == "markdown":
        print(render_grid(reports), end="")
    else:
        _print_text(reports, _use_color(arguments.color))


def _dump(context: Context, arguments: argparse.Namespace) -> object:
    """What --facts, --answers or --map prints."""
    if arguments.facts:
        return context.facts.as_dicts()
    if arguments.answers:
        return answers(context)
    return context.structure.as_dict()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        plugins = discover(arguments.plugin_dir)
        selected = select(plugins.checks, _names(arguments.only), _names(arguments.skip))
    except (PluginError, SelectionError) as error:
        parser.print_usage(sys.stderr)
        return _usage_error(parser, str(error))

    if arguments.list or arguments.support_matrix:
        _print_listing(plugins.checks, arguments)
        return EXIT_SUCCESS
    if not yaml_support.available():
        return _usage_error(parser, yaml_support.MISSING_MESSAGE)
    if not arguments.path.is_dir():
        return _usage_error(parser, f"{arguments.path} is not a directory")

    project = Project(arguments.path.resolve(), frozenset(arguments.exclude))
    context = Context(project, plugins.providers, _options(arguments))
    if arguments.facts or arguments.map or arguments.answers:
        print(json.dumps(_dump(context, arguments), indent=2))
        return EXIT_SUCCESS
    reports = run_checks(selected, context)
    _print_reports(reports, arguments)
    return EXIT_SUCCESS if succeeded(reports, strict=arguments.strict) else EXIT_FAILURE
