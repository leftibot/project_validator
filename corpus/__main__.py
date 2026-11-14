"""`python -m corpus record DIR`: fetch every project of the corpus, validate it, and write what the validator says to
`DIR/<owner>--<repo>.json`; a crash, or an ecosystem a project stands for that is not detected, fails the run unless
the manifest names open issues against the project.
`python -m corpus diff BASE HEAD`: what changed between two recordings, per project and per check. `fetch` fills the
cache and stops."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

from corpus import MANIFEST, CorpusProject, by_name, cache_directory, fetch, observed, projects, shortfalls, unexplained


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m corpus", description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST, help="the projects to use (default: projects.toml)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (("record", "validate the projects and write the recording to DIR"), ("fetch", "fetch and stop")):
        command = commands.add_parser(name, help=text)
        if name == "record":
            command.add_argument("directory", type=Path, metavar="DIR")
        command.add_argument("names", nargs="*", help="only these projects (owner/repo); default: every project")
        command.add_argument("--cache", type=Path, default=cache_directory(), help="where the checkouts are kept")
        command.add_argument("--jobs", type=int, default=4, help="projects validated at once (default: 4)")
    diff = commands.add_parser("diff", help="what changed between two recordings")
    diff.add_argument("base", type=Path, metavar="BASE")
    diff.add_argument("head", type=Path, metavar="HEAD")
    diff.add_argument("--full", action="store_true", help="print each project's unified diff, not just the summary")
    return parser


def _record(selected: list[CorpusProject], cache: Path, jobs: int, directory: Path) -> int:
    """Validate `selected` (fetched first), write the recordings, and say what fell short; 1 when a shortfall has no
    open issue to account for it."""
    directory.mkdir(parents=True, exist_ok=True)
    known, fatal = 0, 0
    with ProcessPoolExecutor(max_workers=jobs) as validating:
        for project, seen in validating.map(observed, selected, [cache] * len(selected)):
            project.recording(directory).write_text(seen, encoding="utf-8")
            problems = shortfalls(project, json.loads(seen))
            unaccounted = unexplained(project, problems)
            for problem in problems:
                issues = (
                    "" if problem in unaccounted else " (known: " + ", ".join(f"#{n}" for n in project.issues) + ")"
                )
                print(f"{project.name}: {problem}{issues}", flush=True)
            fatal += len(unaccounted)
            known += len(problems) - len(unaccounted)
    print(f"{len(selected)} projects recorded in {directory}; {known} known shortfall(s), {fatal} unexplained")
    return 1 if fatal else 0


def _statuses(recording: dict[str, object]) -> dict[str, str]:
    results = recording.get("results")
    return {str(r["check"]): str(r["status"]) for r in results} if isinstance(results, list) else {}


def _changes(base: dict[str, object], head: dict[str, object]) -> list[str]:
    """The checks whose status changed, as `check: BEFORE → AFTER`; a crash appearing or going is a change too."""
    before, after = _statuses(base), _statuses(head)
    changed = [f"{check}: {before.get(check, '—')} → {after.get(check, '—')}" for check in sorted(before | after)]
    changed = [line for line in changed if not line.endswith(f"{line.split(': ')[1].split(' → ')[0]}")]
    if ("extraction_error" in base) != ("extraction_error" in head):
        changed.insert(0, "extraction: " + ("crashes now" if "extraction_error" in head else "no longer crashes"))
    return changed


def _diff(base: Path, head: Path, *, full: bool) -> int:
    """Print what changed between the recordings in `base` and `head`: a summary line per changed project with its
    status changes, a count of status changes per check, and with `full` each project's unified diff."""
    names = sorted({path.name for path in base.glob("*.json")} | {path.name for path in head.glob("*.json")})
    changed_projects, status_changes = 0, Counter[str]()
    for name in names:
        before = (base / name).read_text(encoding="utf-8") if (base / name).is_file() else ""
        after = (head / name).read_text(encoding="utf-8") if (head / name).is_file() else ""
        if before == after:
            continue
        changed_projects += 1
        changes = _changes(json.loads(before or "{}"), json.loads(after or "{}"))
        status_changes.update(change.split(":")[0] for change in changes)
        detail = "; ".join(changes) if changes else "details only (messages, map or unread reasons)"
        print(f"{name.removesuffix('.json').replace('--', '/')}: {detail}")
        if full:
            print("\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(), "base", "head", lineterm="")))
    print(
        f"{changed_projects} of {len(names)} projects differ"
        + (f"; status changes: {dict(status_changes)}" if status_changes else "")
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "diff":
        return _diff(arguments.base, arguments.head, full=arguments.full)
    listed = projects(arguments.manifest)
    selected = by_name(arguments.names, listed) if arguments.names else listed
    cache: Path = arguments.cache
    with ThreadPoolExecutor(max_workers=8) as fetching:
        list(fetching.map(lambda project: fetch(project, cache), selected))
    if arguments.command == "fetch":
        print(f"{len(selected)} projects in {cache}")
        return 0
    return _record(selected, cache, arguments.jobs, arguments.directory)


if __name__ == "__main__":
    sys.exit(main())
