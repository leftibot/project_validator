"""GitHub Actions: workflows are parsed, and each job's matrix is expanded the way GitHub expands it."""

import itertools
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace

from project_validator.ci import CiProvider, Load, strings
from project_validator.ci.github_expressions import Known, evaluate, rendered
from project_validator.facts import ActionStep, CiJob, Fact, Origin, Unknown
from project_validator.facts.expansion import script_facts
from project_validator.platforms import detect_operating_systems
from project_validator.text import pattern

type Combination = dict[str, object]

_MATRIX_EXPRESSION = re.compile(r"\$\{\{\s*matrix\.([\w.-]+)\s*\}\}")
_RESERVED_MATRIX_KEYS = frozenset({"include", "exclude"})


def _lookup(combination: Combination, dotted: str) -> object | None:
    value: object = combination
    for key in dotted.split("."):
        if not isinstance(value, Mapping) or key not in value:
            return None
        value = value[key]
    return value


def substitute_matrix(text: str, combination: Combination, missing: str | None = None) -> str:
    """`text` with `${{ matrix.<key> }}` replaced by the combination's values; a key the combination lacks is left as
    written, or replaced by `missing` (GitHub itself substitutes an empty string)."""

    def replacement(match: re.Match[str]) -> str:
        value = _lookup(combination, match[1])
        if value is None:
            return match[0] if missing is None else missing
        return value if isinstance(value, str) else json.dumps(value)

    return _MATRIX_EXPRESSION.sub(replacement, text)


# An expression GitHub evaluates before the shell runs the step.
EXPRESSION = re.compile(r"\$\{\{.*?\}\}")


def _is_subset(entry: Mapping[str, object], combination: Combination) -> bool:
    return all(combination.get(key) == value for key, value in entry.items())


def _can_extend(entry: Mapping[str, object], original: Combination) -> bool:
    return all(original[key] == value for key, value in entry.items() if key in original)


def expand_matrix(matrix: object) -> list[Combination] | None:
    """Every combination GitHub would run, or None when the matrix is computed by an expression."""
    if matrix is None:
        return [{}]
    if not isinstance(matrix, Mapping):
        return None
    base = {key: value for key, value in matrix.items() if key not in _RESERVED_MATRIX_KEYS}
    includes = matrix.get("include", [])
    excludes = matrix.get("exclude", [])
    vectors = (*base.values(), includes, excludes)
    if not all(isinstance(vector, list) for vector in vectors):
        return None

    originals = [dict(zip(base, values, strict=True)) for values in itertools.product(*base.values())] if base else []
    originals = [c for c in originals if not any(_is_subset(entry, c) for entry in excludes)]
    return _with_includes(originals, includes) if base or includes else [{}]


def _with_includes(originals: list[Combination], includes: list[Mapping[str, object]]) -> list[Combination]:
    """GitHub's include rules: extend every original combination an entry fits, else add the entry as its own."""
    expanded = [dict(original) for original in originals]
    additions: list[Combination] = []
    for entry in includes:
        targets = [result for original, result in zip(originals, expanded, strict=True) if _can_extend(entry, original)]
        for target in targets:
            target.update(entry)
        if not targets:
            additions.append(dict(entry))
    return expanded + additions


def _runner_os(job: Mapping[str, object], combination: Combination) -> str:
    if "container" in job:
        return "linux"
    runner = substitute_matrix(json.dumps(job.get("runs-on", "")), combination)
    found = detect_operating_systems(runner)
    return found[0] if found else "unknown"


def _combination_label(combination: Combination) -> str:
    return ", ".join(value if isinstance(value, str) else json.dumps(value) for value in combination.values())


def _job_label(name: str, combination: Combination) -> str:
    substituted = substitute_matrix(name, combination)
    if substituted != name or not combination:
        return substituted
    return f"{name} ({_combination_label(combination)})"


_EXPORT = re.compile(
    r"""^\s*(?:echo|printf)\s+(?:-\w+\s+)?["']?(?P<name>[A-Za-z_]\w*)=(?P<value>[^"'\n]*?)["']?"""
    r"""\s*>>\s*["']?\$\{?GITHUB_ENV\}?["']?\s*$""",
    re.MULTILINE,
)


def _exported(script: str) -> dict[str, str]:
    """The variables a step's script sets for the later steps: `echo "NAME=value" >> "$GITHUB_ENV"`."""
    return {match["name"]: match["value"] for match in _EXPORT.finditer(script)}


def _job_facts(
    path: str, job_id: str, job: Mapping[str, object], workflow_env: object, caller: str = "", load: Load | None = None
) -> Iterator[Fact]:
    """The facts of one job; `caller` names the job that calls the workflow, for a reusable workflow's jobs. `load`
    reads the local actions its steps use."""
    origin = Origin(path=path, at=("jobs", job_id))
    strategy = job.get("strategy")
    combinations = expand_matrix(strategy.get("matrix") if isinstance(strategy, Mapping) else None)
    if combinations is None:
        # Its steps still run, in combinations that are not known: their matrix values stay as written.
        yield Unknown(
            origin=origin,
            subject=f"the matrix of job {job_id}",
            reason="it is computed by an expression",
            hides="matrix",
        )
        unknown = _Combination(origin, f"{caller}{path}:{job_id}", {}, load=load, matrix_known=False)
        yield from unknown.facts(job, workflow_env)
        return
    for index, combination in enumerate(combinations):
        identity = f"{caller}{path}:{job_id}" + ("" if len(combinations) == 1 else f"[{index}]")
        yield from _Combination(origin, identity, combination, load=load).facts(job, workflow_env)


@dataclass(frozen=True, slots=True)
class _Combination:
    """One matrix combination of a job, whose values are substituted into everything the job runs."""

    origin: Origin
    identity: str
    combination: Combination
    # What the job's conditions and expressions can be evaluated with, once its environment is known.
    known: Known | None = None
    load: Load | None = None
    # Whether the combination's values are known; when not, matrix expressions stay as written.
    matrix_known: bool = True
    # The shell the job's steps run in unless a step names its own (`defaults: run: shell:`).
    shell: str | None = None

    def substitute(self, text: str) -> str:
        """`text` as GitHub runs it: matrix values in place, and every expression whose value is known evaluated."""
        text = substitute_matrix(text, self.combination, missing="" if self.matrix_known else None)
        if (known := self.known) is None:
            return text
        return EXPRESSION.sub(
            lambda match: value if (value := rendered(match[0], known)) is not None else match[0], text
        )

    def substituted(self, value: object) -> dict[str, str]:
        return {key: self.substitute(text) for key, text in strings(value).items()}

    def optional(self, value: object) -> str | None:
        return self.substitute(value) if isinstance(value, str) else None

    def runs(self, condition: object, known: Known) -> bool | None:
        """Whether a job or step with `condition` runs in this combination; None when the checkout does not show it.

        A condition that is not a string (`if: true`) is YAML's own value."""
        if condition is None:
            return True
        return evaluate(condition, known) if isinstance(condition, str) else bool(condition)

    def facts(self, job: Mapping[str, object], workflow_env: object) -> Iterator[Fact]:
        env = {**self.substituted(workflow_env), **self.substituted(job.get("env"))}
        os = _runner_os(job, self.combination)
        known = Known(os=os, matrix=self.combination, env=env)
        if self.runs(job.get("if"), known) is False:
            return
        defaults = job.get("defaults")
        run = defaults.get("run") if isinstance(defaults, Mapping) else None
        shell = run.get("shell") if isinstance(run, Mapping) else None
        yield from replace(self, known=known, shell=str(shell) if shell else None).job_facts(job, known)

    def job_facts(self, job: Mapping[str, object], known: Known) -> Iterator[Fact]:
        container = job.get("container")
        yield CiJob(
            origin=self.origin,
            id=self.identity,
            provider=GITHUB_ACTIONS.name,
            name=_job_label(str(job.get("name", self.origin.at[-1])), self.combination)
            + ("" if self.matrix_known else " (matrix computed by an expression)"),
            os=known.os,
            matrix={
                key: value if isinstance(value, str) else json.dumps(value) for key, value in self.combination.items()
            },
            image=self.optional(container.get("image") if isinstance(container, Mapping) else container),
            env=self.substituted(known.env),
        )
        steps = job.get("steps")
        for number, step in enumerate(steps if isinstance(steps, list) else []):
            if isinstance(step, Mapping):
                yield from self.step_facts(
                    Origin(path=self.origin.path, at=(*self.origin.at, "steps", number)), step, known
                )
                # What a step writes to $GITHUB_ENV is in the environment of the job's later steps.
                if isinstance(run := step.get("run"), str) and (exported := _exported(self.substitute(run))):
                    known = replace(known, env={**known.env, **exported})

    def step_facts(
        self, origin: Origin, step: Mapping[str, object], known: Known, via: tuple[Origin, ...] = ()
    ) -> Iterator[Fact]:
        """The facts of a step that runs, or may run, in this combination; its condition is kept while unknown. A local
        composite action's steps run in the job too, with `via` naming the steps that use it."""
        runs = self.runs(step.get("if"), known)
        if runs is False:
            return
        condition = None if runs else self.optional(step.get("if"))
        if "uses" in step:
            inputs = self.substituted(step.get("with"))
            uses = str(step["uses"])
            yield ActionStep(origin=origin, job=self.identity, uses=uses, inputs=inputs, condition=condition)
            if (local := _local_action(uses)) is not None:
                yield from self.composite_facts(origin, local, inputs, known, (*via, origin))
        if isinstance(run := step.get("run"), str):
            yield from script_facts(
                self.substitute(run),
                job=self.identity,
                origin=Origin(path=origin.path, at=(*origin.at, "run")),
                env={**known.env, **self.substituted(step.get("env"))},
                directory=self.optional(step.get("working-directory")),
                condition=condition,
                opaque=EXPRESSION,
                via=via,
                powershell=self.powershell(step, known),
            )

    def powershell(self, step: Mapping[str, object], known: Known) -> bool:
        """Whether a step's script is PowerShell: its `shell`, the job's default, or the runner's (pwsh on Windows)."""
        shell = step.get("shell") or self.shell
        if shell is None:
            return known.os == "windows"
        return str(shell).split()[0] in ("pwsh", "powershell")

    def composite_facts(
        self, origin: Origin, directory: str, inputs: Mapping[str, str], known: Known, via: tuple[Origin, ...]
    ) -> Iterator[Fact]:
        """The steps of the local action in `directory`, when it is a composite action, with its inputs in place."""
        found = self._action(directory)
        if found is None:
            yield Unknown(
                origin=origin,
                subject=f"the action ./{directory}",
                reason="its action.yml is not read",
                hides="commands",
            )
            return
        path, action = found
        runs = action.get("runs")
        steps = runs.get("steps") if isinstance(runs, Mapping) and runs.get("using") == "composite" else None
        if not isinstance(steps, list) or len(via) > _CALL_DEPTH:
            return  # a JavaScript or Docker action, whose commands are its own code
        values = {**_input_defaults(action.get("inputs")), **inputs}
        for number, step in enumerate(steps):
            if isinstance(step, Mapping):
                at = Origin(path=path, at=("runs", "steps", number))
                yield from self.step_facts(at, _with_inputs(step, values), known, via)

    def _action(self, directory: str) -> tuple[str, Mapping[str, object]] | None:
        for name in ("action.yml", "action.yaml"):
            path = f"{directory}/{name}"
            if self.load is not None and isinstance(document := self.load(path), Mapping):
                return path, document
        return None


_INPUT = re.compile(r"\$\{\{\s*inputs\.([\w-]+)\s*\}\}")


def _local_action(uses: str) -> str | None:
    """The directory of an action in the same repository (`./.github/actions/build`), else None."""
    path = _local(uses)
    return None if path is None else path.rstrip("/")


def _input_defaults(inputs: object) -> dict[str, str]:
    if not isinstance(inputs, Mapping):
        return {}
    found = ((name, spec.get("default")) for name, spec in inputs.items() if isinstance(spec, Mapping))
    return {
        str(name): str(default).lower() if isinstance(default, bool) else str(default)
        for name, default in found
        if default is not None
    }


def _with_inputs[T](value: T, inputs: Mapping[str, str]) -> T:
    """`value` (a step, or part of one) with each `${{ inputs.<name> }}` replaced by the input's value ("" when it has
    none)."""
    if isinstance(value, str):
        return _INPUT.sub(lambda match: inputs.get(match[1], ""), value)  # type: ignore[return-value]
    if isinstance(value, Mapping):
        return {key: _with_inputs(item, inputs) for key, item in value.items()}  # type: ignore[return-value]
    if isinstance(value, list):
        return [_with_inputs(item, inputs) for item in value]  # type: ignore[return-value]
    return value


# GitHub runs at most this many levels of reusable workflows.
_CALL_DEPTH = 4


def _only_called(document: Mapping[object, object]) -> bool:
    """Whether a workflow runs only when another calls it (`on: workflow_call`)."""
    triggers = document.get("on", document.get(True))  # YAML 1.1 reads a bare `on` as true
    names = [triggers] if isinstance(triggers, str) else list(triggers) if isinstance(triggers, (list, Mapping)) else []
    return names == ["workflow_call"]


def _local(uses: object) -> str | None:
    """The path of a reusable workflow or action in the same repository (`./.github/workflows/build.yml`,
    `$/.github/actions/build`), else None."""
    text = str(uses)
    for prefix in ("./", "$/"):
        if text.startswith(prefix) and "@" not in text:
            return text.removeprefix(prefix)
    return None


def workflow_facts(path: str, document: object, load: Load | None = None, caller: str = "") -> Iterator[Fact]:
    """The jobs of a workflow, one per matrix combination, with the commands and actions each one runs. A job that
    calls a reusable workflow of the same repository runs that workflow's jobs (read with `load`); one in another
    repository is unknown."""
    if not isinstance(document, Mapping) or not isinstance(jobs := document.get("jobs"), Mapping):
        return
    if not caller and _only_called(document):
        return  # its jobs run where another workflow calls it
    for job_id, job in jobs.items():
        if not isinstance(job, Mapping):
            continue
        if "uses" not in job:
            yield from _job_facts(path, str(job_id), job, document.get("env"), caller, load)
            continue
        called = _local(job["uses"])
        within_depth = caller.count(" → ") < _CALL_DEPTH
        if called is not None and load is not None and within_depth and (target := load(called)) is not None:
            yield from workflow_facts(called, target, load, f"{caller}{path}:{job_id} → ")
            continue
        yield Unknown(
            origin=Origin(path=path, at=("jobs", str(job_id))),
            subject=f"job {job_id}",
            reason=f"it calls the reusable workflow {job['uses']}, which is not read",
            hides="jobs",
        )


def _uses(entries: object) -> list[str]:
    if not isinstance(entries, list):
        return []
    return [str(entry["uses"]) for entry in entries if isinstance(entry, Mapping) and "uses" in entry]


def action_references(document: object) -> list[str]:
    """Every reusable workflow (`jobs.<id>.uses`) and action (`jobs.<id>.steps[*].uses`) a workflow uses."""
    if not isinstance(document, Mapping) or not isinstance(jobs := document.get("jobs"), Mapping):
        return []
    found = [job for job in jobs.values() if isinstance(job, Mapping)]
    return [*_uses(found), *(reference for job in found for reference in _uses(job.get("steps")))]


GITHUB_ACTIONS = CiProvider(
    name="GitHub Actions",
    directories=(".github/workflows",),
    # zizmor also finds security problems in workflows: template injection, credentials persisted by checkout, ...
    linters=(pattern("actionlint", r"\bactionlint\b"), pattern("zizmor", r"\bzizmor\b")),
    lint_hint="GitHub Actions: run actionlint (rhysd/actionlint) or zizmor (zizmorcore/zizmor-action) in CI",
    badges=(
        pattern(
            "GitHub Actions",
            r"/actions/workflows/[^/\s]+/badge\.svg|/workflows/[^/\s]+/badge\.svg|img\.shields\.io/github/actions/workflow/status/",
        ),
    ),
    step_references=action_references,
    facts=workflow_facts,
)
