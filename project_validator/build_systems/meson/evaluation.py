"""Evaluating a Meson project as configuring it would, without running Meson.

Evaluation starts at each top-level meson.build and follows `subdir()`, which shares the variables. Every branch of
an `if` is followed, in the builds its condition holds in (see `values`): the compiler (`cc.get_id()`,
`cc.get_argument_syntax()`), the host system (`host_machine.system()`) and the build type
(`get_option('buildtype')`) are understood, other options and compiler checks (`cc.has_argument()`) are
requirements, as written. A loop runs once per listed item; `break` and `continue` are not followed.
"""

import posixpath
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Protocol

from project_validator.build_systems.meson import syntax
from project_validator.build_systems.meson.operations import (
    BUILD_TYPE,
    added,
    binary,
    indexed,
    looped,
    method,
    pairs,
    text_of,
    within,
    written,
)
from project_validator.build_systems.meson.values import (
    FALSE,
    TRUE,
    Choices,
    Dictionary,
    Object,
    Symbol,
    Truth,
    Unknown,
    Value,
    array,
    assigned,
    combined,
    elements,
    holds,
    single,
    strings,
)
from project_validator.facts import Origin
from project_validator.facts.conditions import ALWAYS, Condition, Dimension, both, either, negated

BUILD_FILE = "meson.build"
MOST_ITERATIONS = 64
MOST_STATEMENTS = 250_000

LANGUAGES = {"c": "C", "cpp": "C++", "cuda": "CUDA", "objc": "Objective-C", "objcpp": "Objective-C++"}
LANGUAGES |= {"fortran": "Fortran", "nasm": "Assembly", "masm": "Assembly"}
LANGUAGE = Dimension("languages", LANGUAGES)
# A target's arguments for one language: `cpp_args`.
TARGET_ARGUMENTS = {f"{name}_args": name for name in LANGUAGES}
TARGETS = frozenset(
    {"executable", "library", "static_library", "shared_library", "both_libraries", "shared_module", "build_target"}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Frame:
    """Where evaluation is: the builds the statements run in, the directory and file, and the statement's line."""

    condition: Condition
    directory: str
    path: str
    line: int = 0

    def origin(self, name: str) -> Origin:
        return Origin(path=self.path, at=(name, self.line))

    def within(self, when: Condition) -> Frame:
        return replace(self, condition=both(self.condition, when))


type Found = Iterator[tuple[str, Condition]]


class Observer(Protocol):
    """What evaluation hands on: the options, settings, tests and run targets it finds."""

    def options(self, frame: Frame, name: str, found: Found, target: str | None, *, linking: bool) -> None: ...

    def setting(self, frame: Frame, name: str, key: str, value: str, target: str | None, *, default: bool) -> None: ...

    def test(self, frame: Frame) -> None: ...

    def run_target(self, frame: Frame, name: str, command: tuple[str, ...]) -> None: ...


class _TooMuch(Exception):
    pass


_BUILT_IN: Mapping[str, Value] = {
    "meson": Object("meson"),
    "host_machine": Object("machine", "host"),
    "build_machine": Object("machine", "build"),
    "target_machine": Object("machine", "target"),
}


def _depth(path: str) -> tuple[int, str]:
    return path.count("/"), path


@dataclass(slots=True)
class Evaluation:
    """The evaluation of a project's Meson files (path -> text), for an observer."""

    files: Mapping[str, str]
    observer: Observer
    variables: dict[str, Choices] = field(default_factory=dict)
    reached: set[str] = field(default_factory=set)
    problems: dict[str, str] = field(default_factory=dict)
    _statements: int = 0

    def evaluate(self) -> None:
        """Every top-level meson.build: those no `subdir()` reaches."""
        builds = sorted((path for path in self.files if PurePosixPath(path).name == BUILD_FILE), key=_depth)
        path = ""
        try:
            for path in builds:
                if path not in self.reached:
                    self.evaluate_alone(path)
        except _TooMuch:
            self.problems[builds[0]] = f"evaluation stopped after {MOST_STATEMENTS} statements"
        except RecursionError:
            self.problems[path] = "nested too deeply to read"

    def evaluate_alone(self, path: str) -> None:
        """A file evaluated on its own (a top-level meson.build, or meson.options), with no variables."""
        self.variables = {}
        self._file(path, Frame(condition=ALWAYS, directory=posixpath.dirname(path) or ".", path=path))

    def _file(self, path: str, frame: Frame) -> None:
        self.reached.add(path)
        try:
            nodes = syntax.parse(self.files[path])
        except syntax.MesonSyntaxError as error:
            self.problems[path] = str(error)
            return
        self.run(nodes, replace(frame, path=path, directory=posixpath.dirname(path) or "."))

    def run(self, nodes: list[syntax.Node], frame: Frame) -> None:
        for node in nodes:
            self._statements += 1
            if self._statements > MOST_STATEMENTS:
                raise _TooMuch
            if isinstance(node, syntax.Assignment):
                self._assign(node, replace(frame, line=node.line))
            elif isinstance(node, syntax.Statement):
                self.value(node.expression, replace(frame, line=node.line))
            elif isinstance(node, syntax.If):
                self._if(node, frame)
            elif isinstance(node, syntax.Foreach):
                self._foreach(node, frame)

    def _assign(self, node: syntax.Assignment, frame: Frame) -> None:
        new = self.value(node.value, frame)
        old = self.variables.get(node.name)
        if node.operator == "+=" and old is not None and new:
            self.variables[node.name] = [(added(value, new[0][0], frame.condition), when) for value, when in old]
        else:
            self.variables[node.name] = assigned(old, new, frame.condition)

    def _if(self, node: syntax.If, frame: Frame) -> None:
        remaining = frame.condition
        for condition, body in node.branches:
            held = ALWAYS if condition is None else holds(self.value(condition, frame))
            if branch := both(remaining, held):
                self.run(body, replace(frame, condition=branch))
            remaining = both(remaining, negated(held))
            if not remaining:
                return

    def _foreach(self, node: syntax.Foreach, frame: Frame) -> None:
        items = [item for value, when in self.value(node.items, frame) for item in looped(value, when)]
        for values, when in items[:MOST_ITERATIONS]:
            if held := both(frame.condition, when):
                for name, value in zip(node.names, values, strict=False):
                    self.variables[name] = single(value)
                self.run(node.body, replace(frame, condition=held))

    # --- expressions

    def value(self, expression: syntax.Expression, frame: Frame) -> Choices:
        """The values an expression takes, each in its builds."""
        match expression:
            case syntax.Literal(value=bool() as flag):
                return single(TRUE if flag else FALSE)
            case syntax.Literal(value=str() as text, formatted=True):
                return single(self._formatted(text))
            case syntax.Literal(value=str() | int() as value):
                return single(value)
            case syntax.Name(name=name):
                return self.variables.get(name) or single(_BUILT_IN.get(name, Unknown(name)))
            case syntax.Array(items=items):
                return single(array((value, when) for item in items for value, when in self.value(item, frame)))
            case syntax.Dictionary(items=items):
                return single(self._dictionary(items, frame))
            case syntax.Call():
                return self._call(expression, frame)
            case syntax.Index(target=target, index=index):
                pairs_of = combined(self.value(target, frame), self.value(index, frame))
                return [(indexed(container, key, written(target)), when) for (container, key), when in pairs_of]
            case syntax.Operation():
                return self._operation(expression, frame)
        return single(Unknown(written(expression)))  # pragma: no cover - every expression is matched above

    def _formatted(self, text: str) -> Value:
        """An f-string, its `@name@` replaced where the variable holds one string or number."""
        for name, choices in self.variables.items():
            if f"@{name}@" in text and len(choices) == 1 and isinstance(choices[0][0], (str, int)):
                text = text.replace(f"@{name}@", str(choices[0][0]))
        return text

    def _dictionary(self, items: tuple[tuple[syntax.Expression, syntax.Expression], ...], frame: Frame) -> Dictionary:
        found = []
        for key, value in items:
            name = self.value(key, frame)[0][0]
            if isinstance(name, str):
                found.append((name, self.value(value, frame)[0][0]))
        return Dictionary(tuple(found))

    def _operation(self, operation: syntax.Operation, frame: Frame) -> Choices:
        left = self.value(operation.left, frame)
        if operation.operator == "not":
            return single(Truth(negated(holds(left))))
        if operation.right is None:  # unary minus
            return [(-value if isinstance(value, int) else Unknown(written(operation)), when) for value, when in left]
        right = self.value(operation.right, frame)
        if operation.otherwise is not None:
            chosen = holds(left)
            return [*within(right, chosen), *within(self.value(operation.otherwise, frame), negated(chosen))]
        if operation.operator in ("and", "or"):
            return single(Truth((both if operation.operator == "and" else either)(holds(left), holds(right))))
        text = written(operation)
        return [(binary(operation.operator, one, other, text), when) for (one, other), when in combined(left, right)]

    # --- calls

    def _call(self, call: syntax.Call, frame: Frame) -> Choices:
        if call.target is None:
            handler = _FUNCTIONS.get(call.name)
            return handler(self, call, frame) if handler is not None else single(Object(call.name))
        values = self.positional(call, frame)
        found: Choices = []
        for target, when in self.value(call.target, frame):
            found += within(method(target, call, values), when)
        return found

    def positional(self, call: syntax.Call, frame: Frame) -> Choices:
        return [choice for argument in call.arguments.positional for choice in self.value(argument, frame)]

    def names(self, call: syntax.Call, frame: Frame) -> list[str]:
        """The strings among a call's positional arguments."""
        return [text for text, _ in strings(self.positional(call, frame))]

    def keyword(self, call: syntax.Call, name: str, frame: Frame) -> Choices:
        found = call.arguments.keyword(name)
        return [] if found is None else self.value(found, frame)

    # --- the functions that set something

    def project(self, call: syntax.Call, frame: Frame) -> Choices:
        """The project's default options; Meson's own default `warning_level` is 1."""
        options = self.keyword(call, "default_options", frame)
        if not any(key == "warning_level" for value, _ in elements(options) for key, _ in pairs(value)):
            self.observer.setting(frame, "project", "warning_level", "1", None, default=True)
        self._options(options, frame, "project", None, default=True)
        return single(Object("project"))

    def _options(self, choices: Choices, frame: Frame, name: str, target: str | None, *, default: bool) -> None:
        """The options `default_options` (or `override_options`) sets."""
        for value, when in elements(choices):
            for key, setting in pairs(value):
                self.observer.setting(frame.within(when), name, key, text_of(setting), target, default=default)

    def arguments(self, call: syntax.Call, frame: Frame) -> Choices:
        """`add_project_arguments(args..., language: 'cpp')` and the global and link variants."""
        languages = [text for text, _ in strings(self.keyword(call, "language", frame))]
        builds = frame.within(LANGUAGE.listed(languages)) if languages else frame
        found = strings(self.positional(call, frame))
        self.observer.options(builds, call.name, found, None, linking="link" in call.name)
        return single(Object(call.name))

    def target(self, call: syntax.Call, frame: Frame) -> Choices:
        """A build target: its own arguments per language, link arguments, and options."""
        names = self.names(call, frame)
        name = names[0] if names else None
        for keyword, value in call.arguments.keywords:
            if keyword in TARGET_ARGUMENTS or keyword == "link_args":
                language = TARGET_ARGUMENTS.get(keyword)
                builds = frame.within(LANGUAGE.equal_to(language)) if language else frame
                found = strings(self.value(value, frame))
                self.observer.options(builds, call.name, found, name, linking=keyword == "link_args")
            elif keyword == "override_options":
                self._options(self.value(value, frame), frame, call.name, name, default=False)
        return single(Object("target", name or ""))

    def test(self, _call: syntax.Call, frame: Frame) -> Choices:
        self.observer.test(frame)
        return single(Object("test"))

    def subdir(self, call: syntax.Call, frame: Frame) -> Choices:
        for directory, when in strings(self.positional(call, frame)):
            path = posixpath.normpath(posixpath.join(frame.directory, directory, BUILD_FILE))
            if path in self.files and path not in self.reached and (held := both(frame.condition, when)):
                self._file(path, replace(frame, condition=held))
        return single(Object("subdir"))

    def get_option(self, call: syntax.Call, frame: Frame) -> Choices:
        if self.names(call, frame) == ["buildtype"]:
            return single(Symbol(BUILD_TYPE, "get_option('buildtype')"))
        return single(Unknown(written(call)))

    def option(self, call: syntax.Call, frame: Frame) -> Choices:
        """An option of meson.options, and its default."""
        names = self.names(call, frame)
        for value, when in self.keyword(call, "value", frame) if names else ():
            self.observer.setting(frame.within(when), "option", names[0], text_of(value), None, default=True)
        return single(Object("option"))

    def run_target(self, call: syntax.Call, frame: Frame) -> Choices:
        names = self.names(call, frame)
        command = tuple(text_of(value) for value, _ in elements(self.keyword(call, "command", frame)))
        if names and command:
            self.observer.run_target(frame, names[0], command)
        return single(Object("run_target", names[0] if names else ""))

    def find_program(self, call: syntax.Call, frame: Frame) -> Choices:
        names = self.names(call, frame)
        return single(Object("program", names[0] if names else ""))

    def is_variable(self, call: syntax.Call, frame: Frame) -> Choices:
        names = self.names(call, frame)
        return single(TRUE if names and names[0] in self.variables else FALSE)


_ARGUMENTS = (
    "add_project_arguments",
    "add_global_arguments",
    "add_project_link_arguments",
    "add_global_link_arguments",
)
_FUNCTIONS: Mapping[str, Callable[[Evaluation, syntax.Call, Frame], Choices]] = {
    "project": Evaluation.project,
    **dict.fromkeys(_ARGUMENTS, Evaluation.arguments),
    **dict.fromkeys(TARGETS, Evaluation.target),
    "test": Evaluation.test,
    "subdir": Evaluation.subdir,
    "get_option": Evaluation.get_option,
    "option": Evaluation.option,
    "run_target": Evaluation.run_target,
    "find_program": Evaluation.find_program,
    "is_variable": Evaluation.is_variable,
}

__all__ = ["BUILD_FILE", "LANGUAGE", "Evaluation", "Frame", "Observer"]
