"""The project corpus: real repositories, each pinned to a commit, validated as they are. The unit tests' fixtures are
small and written to be judged; the corpus is the other half of the regression suite, the projects as their authors
wrote them, one or more for every ecosystem profile. Nothing is recorded in the repository: `python -m corpus record`
writes what the validator says about each project to a directory, and `python -m corpus diff` compares two such
recordings, so CI runs the base branch and the pull request over the same checkouts and shows what changed, which
also runs every parser over real inputs each time.

`projects.toml` names each project (its GitHub `owner/repo`), the commit it is pinned to, the ecosystems it stands for
(a recording must detect each; `record` fails otherwise, unless the entry names open issues that account for it), and
the open issues about what the validator gets wrong on it. A recording holds, per project, the project map, the
results judged with `--allow-unknown` (without the per-place copies, a monorepo has hundreds), and what strict judging
adds: each check's status and the distinct reasons something could not be read. A checkout is fetched shallowly, once,
into the cache (`$PROJECT_VALIDATOR_CORPUS`, else `~/.cache/project_validator/corpus`).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from project_validator.cli import report_dicts
from project_validator.core import Context, Options, Project
from project_validator.plugins import discover
from project_validator.runner import Report, run_checks

ROOT = Path(__file__).parent
MANIFEST = ROOT / "projects.toml"
CACHE_VARIABLE = "PROJECT_VALIDATOR_CORPUS"
DEFAULT_CACHE = Path.home() / ".cache" / "project_validator" / "corpus"


@dataclass(frozen=True, slots=True)
class CorpusProject:
    """A repository of the corpus: `name` is its GitHub `owner/repo`, `commit` the full SHA it is pinned to,
    `ecosystems` the profiles it stands for (labels, as the support matrix names them), `issues` the upstream issues
    about what the validator gets wrong on it."""

    name: str
    commit: str
    ecosystems: tuple[str, ...]
    notes: str = ""
    issues: tuple[int, ...] = ()

    @property
    def url(self) -> str:
        return f"https://github.com/{self.name}.git"

    @property
    def slug(self) -> str:
        return self.name.replace("/", "--")

    def checkout(self, cache: Path) -> Path:
        return cache / self.slug

    def recording(self, directory: Path) -> Path:
        return directory / f"{self.slug}.json"


def projects(manifest: Path = MANIFEST) -> list[CorpusProject]:
    """The corpus, as `projects.toml` lists it."""
    with manifest.open("rb") as handle:
        listed = tomllib.load(handle)
    return [
        CorpusProject(
            name=entry["name"],
            commit=entry["commit"],
            ecosystems=tuple(entry["ecosystems"]),
            notes=entry.get("notes", ""),
            issues=tuple(entry.get("issues", ())),
        )
        for entry in listed["project"]
    ]


def by_name(names: Iterable[str], listed: Iterable[CorpusProject]) -> list[CorpusProject]:
    """The listed projects `names` select (by `owner/repo`); every name must be listed."""
    wanted = set(names)
    selected = [project for project in listed if project.name in wanted]
    missing = wanted - {project.name for project in selected}
    if missing:
        raise KeyError(f"not in the corpus: {', '.join(sorted(missing))}")
    return selected


def cache_directory() -> Path:
    return Path(os.environ.get(CACHE_VARIABLE) or DEFAULT_CACHE)


def _git(directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is needed to fetch the corpus")
    return subprocess.run(  # noqa: S603 - argv list, no shell
        [git, "-C", str(directory), *arguments], capture_output=True, text=True, check=False
    )


def _head(directory: Path) -> str | None:
    if not (directory / ".git").is_dir():
        return None
    head = _git(directory, "rev-parse", "HEAD")
    return head.stdout.strip() if head.returncode == 0 else None


def fetch(project: CorpusProject, cache: Path) -> Path:
    """The project's checkout at its commit, fetched shallowly (the one commit, no history) when the cache does not
    hold it yet. A git checkout, not an archive: an archive leaves out what `.gitattributes` export-ignores, often the
    CI configuration itself."""
    directory = project.checkout(cache)
    if _head(directory) == project.commit:
        return directory
    directory.mkdir(parents=True, exist_ok=True)
    if not (directory / ".git").is_dir():
        _git(directory, "init", "--quiet")
        _git(directory, "remote", "add", "origin", project.url)
    for step in (
        ("fetch", "--quiet", "--depth", "1", "origin", project.commit),
        ("-c", "advice.detachedHead=false", "checkout", "--quiet", "--force", project.commit),
    ):
        done = _git(directory, *step)
        if done.returncode != 0:
            raise RuntimeError(f"{project.name}: git {step[0]} failed: {done.stderr.strip()}")
    return directory


NOT_READ = re.compile(r"\bnot read: (.*)")


def _judgements(reports: list[Report]) -> list[dict[str, object]]:
    """The results as `--format json` prints them, without the per-place copies (a monorepo has hundreds)."""
    return [{key: value for key, value in result.items() if key != "places"} for result in report_dicts(reports)]


def _strictly(reports: list[Report]) -> dict[str, object]:
    """What strict judging adds: each check's status, and the distinct reasons something could not be read (the
    unread constructs: a parser that learns one removes its reason here)."""
    reasons = {
        found.group(1) for report in reports for detail in report.result.details if (found := NOT_READ.search(detail))
    }
    return {
        "statuses": {report.check.name: str(report.result.status) for report in reports},
        "not_read": sorted(reasons),
    }


def observe(project: CorpusProject, directory: Path) -> dict[str, object]:
    """What the validator says about the checkout: the project map, the results judged with `--allow-unknown` (the
    judgements, without per-place copies), and what strict judging adds (the facts are extracted once; only the
    judging differs). An extraction failure is recorded, not raised: a crash on a real project is a regression to see
    in the diff."""
    plugins = discover()
    context = Context(Project(directory.resolve()), plugins.providers, Options())
    strict = run_checks(plugins.checks, context)
    context.options = Options(allow_unknown=True)
    judged = run_checks(plugins.checks, context)
    observation: dict[str, object] = {
        "commit": project.commit,
        "results": _judgements(judged),
        "strict": _strictly(strict),
    }
    failure = context.extraction_error
    if failure is None:
        observation["map"] = context.structure.as_dict()
    else:
        observation["extraction_error"] = f"{failure}: {failure.error!r}"
    return observation


def render(observation: dict[str, object]) -> str:
    return json.dumps(observation, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def observed(project: CorpusProject, cache: Path) -> tuple[CorpusProject, str]:
    """The project and its rendered observation, fetched first; a module-level function, so a process pool can run
    it."""
    directory = fetch(project, cache)
    rendered = render(observe(project, directory))
    # A crash's message names the file by its absolute path; a recording must not depend on where the cache is.
    for absolute in {str(directory), str(directory.resolve())}:
        rendered = rendered.replace(absolute, "<checkout>")
    return project, rendered


def shortfalls(project: CorpusProject, observation: dict[str, object]) -> list[str]:
    """What a recording of `project` shows that the manifest does not promise: a crash, or an ecosystem the project
    stands for that was not detected in it."""
    if "extraction_error" in observation:
        return [f"the extraction failed: {observation['extraction_error']}"]
    structure = observation.get("map")
    detected = set(structure["ecosystems"]) if isinstance(structure, dict) else set()
    return [f"{label} is not detected" for label in project.ecosystems if label not in detected]


def unexplained(project: CorpusProject, problems: list[str]) -> list[str]:
    """The shortfalls nothing accounts for: a project whose manifest entry names open issues is known to be judged
    wrongly (a crash, a profile that does not recognise it yet), so its shortfalls are reported, not fatal."""
    return [] if project.issues else problems
