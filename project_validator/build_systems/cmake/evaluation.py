"""Evaluating a CMake project as configuring it would, without running CMake.

Evaluation starts at each top-level CMakeLists.txt and follows `include()`, `add_subdirectory()` and the project's
own functions and macros, keeping variables in their scopes. A build file decides some things only per build (the
compiler, the platform, the configuration) or by what configuring is told (options, compiler checks); every branch is
followed, in the builds its condition names (see `project_validator.build_systems.cmake.conditions`), and variables
hold each value in the builds it is set in. Commands that are neither control flow nor variables are handed to an
`Observer` with their arguments' values.

What is not followed: loops run once per listed item (or once), a function or macro called again with the same
arguments (or after its first calls),
`return()` returns nowhere, and only the
`list()` and `string()` operations that add to a variable change it. A CMake file no top-level CMakeLists.txt
reaches is evaluated on its own, as if it were included; a function or macro nothing calls, as if it were called.
"""

import posixpath
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from functools import partial
from itertools import islice, product
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Protocol

from project_validator.build_systems.cmake.conditions import SYMBOLIC, Operand, Variables, condition
from project_validator.build_systems.cmake.syntax import (
    Argument,
    Block,
    CMakeSyntaxError,
    Invocation,
    Kind,
    Node,
    parse,
)
from project_validator.build_systems.cmake.values import (
    ESCAPED_SEMICOLON,
    MOST_VALUES,
    Item,
    Value,
    elements,
    expanded,
    reference,
)
from project_validator.facts import Origin
from project_validator.facts.conditions import ALWAYS, Condition, both, either, negated, requiring

# How deep calls and includes nest, how many items a loop runs for, and how many commands are evaluated in all.
MOST_NESTED = 24
MOST_ITERATIONS = 64
MOST_COMMANDS = 250_000
# A function or macro called again with the same arguments sets the same things again: it is not followed again. Nor is
# it after its first calls, which show what it sets (on which targets is not asked).
MOST_CALLS = 64
LISTS_FILE = "CMakeLists.txt"
NO_ARGUMENTS: Mapping[str, tuple[Item, ...]] = MappingProxyType({})


class Scope:
    """Variables: a directory's, a function's or a block's own, and those of the scope it is in."""

    __slots__ = ("parent", "variables")

    def __init__(self, parent: Scope | None = None) -> None:
        self.parent = parent
        self.variables: dict[str, tuple[Item, ...] | None] = {}

    def get(self, name: str) -> tuple[Item, ...] | None:
        scope: Scope | None = self
        while scope is not None:
            if name in scope.variables:
                return scope.variables[name]
            scope = scope.parent
        return None

    def assign(self, name: str, items: Iterable[Item], when: Condition, *, append: bool = False) -> None:
        """Set (or, with `append`, add to) a variable in the builds `when` names; other builds keep its value."""
        old = self.get(name) or ()
        kept = (
            old
            if append
            else tuple(Item(item.text, held, item.origin) for item in old if (held := both(item.when, negated(when))))
        )
        added = tuple(Item(item.text, held, item.origin) for item in items if (held := both(item.when, when)))
        self.variables[name] = kept + added

    def unset(self, name: str, when: Condition) -> None:
        if when == ALWAYS:
            self.variables[name] = None
        else:
            self.assign(name, (), when)


@dataclass(frozen=True, slots=True, kw_only=True)
class Frame:
    """Where evaluation is: the scope, the builds the commands run in, the current source directory (relative to the
    project, "." at its top), the file being evaluated, a macro's arguments, and the files and calls it is inside."""

    scope: Scope
    condition: Condition
    directory: str
    path: str
    arguments: Mapping[str, tuple[Item, ...]] = NO_ARGUMENTS
    stack: tuple[str, ...] = ()

    def origin(self, invocation: Invocation) -> Origin:
        return Origin(path=self.path, at=(invocation.name, invocation.line))


class Observer(Protocol):
    def invoked(self, frame: Frame, invocation: Invocation, words: list[Value]) -> None: ...

    def finished(self, frame: Frame) -> None:
        """The end of a directory's (or a lone file's) evaluation: its scope holds what it set last."""


@dataclass(slots=True)
class Definition:
    name: str
    parameters: tuple[str, ...]
    body: list[Node]
    macro: bool
    path: str
    # The builds it is defined in.
    when: Condition = ALWAYS
    calls: int = 0
    # The arguments of each call followed so far.
    seen: set[tuple[str, ...]] = field(default_factory=set)


class _TooMuch(Exception):
    pass


@dataclass(slots=True)
class Evaluation:
    """The evaluation of a project's CMake files (`read` returns a file's text), for an observer."""

    files: frozenset[str]
    read: Callable[[str], str]
    observer: Observer
    functions: dict[str, Definition] = field(default_factory=dict)
    # Variables configuring decides (options, cache variables), and how to describe compiler checks' results.
    configured: set[str] = field(default_factory=set)
    descriptions: dict[str, str] = field(default_factory=dict)
    reached: set[str] = field(default_factory=set)
    problems: dict[str, str] = field(default_factory=dict)
    _parsed: dict[str, list[Node] | None] = field(default_factory=dict)
    _commands: int = 0

    def parsed(self, path: str) -> list[Node] | None:
        if path not in self._parsed:
            try:
                self._parsed[path] = parse(self.read(path))
            except CMakeSyntaxError as error:
                self.problems[path] = str(error)
                self._parsed[path] = None
            except RecursionError:
                self.problems[path] = "nested too deeply to read"
                self._parsed[path] = None
        return self._parsed[path]

    def evaluate(self) -> None:
        """Every top-level CMakeLists.txt, then the files, functions and macros none of them reaches."""
        try:
            self._evaluate_all()
        except _TooMuch:
            self.problems["CMakeLists.txt"] = f"evaluation stopped after {MOST_COMMANDS} commands"
        except RecursionError:
            self.problems["CMakeLists.txt"] = "nested too deeply to read"

    def _evaluate_all(self) -> None:
        lists = sorted((path for path in self.files if PurePosixPath(path).name == LISTS_FILE), key=_depth)
        for path in lists:
            if path not in self.reached:
                self._directory(path, Scope(), ALWAYS, top=True)
        for path in sorted(self.files - self.reached):
            self._directory(path, Scope(), requiring(f"{path} is included"), top=True)
        while uncalled := [definition for definition in self.functions.values() if not definition.calls]:
            for definition in uncalled:
                self._uncalled(definition)

    def _uncalled(self, definition: Definition) -> None:
        definition.calls = 1
        directory = posixpath.dirname(definition.path) or "."
        frame = Frame(
            scope=_root_scope(directory, definition.path),
            condition=both(definition.when, requiring(f"{definition.name}() is called")),
            directory=directory,
            path=definition.path,
        )
        self.run(definition.body, frame)
        self.observer.finished(frame)

    def _directory(self, path: str, scope: Scope, when: Condition, *, top: bool = False) -> None:
        """Evaluate a CMakeLists.txt (or a lone CMake file) in `scope`, a new one for its directory."""
        directory = posixpath.dirname(path) or "."
        if top:
            scope = _root_scope(directory, path)
        _set_directory(scope, directory, path)
        frame = Frame(scope=scope, condition=when, directory=directory, path=path)
        self._file(path, frame)
        self.observer.finished(frame)

    def _file(self, path: str, frame: Frame) -> None:
        self.reached.add(path)
        nodes = self.parsed(path)
        if nodes is not None:
            self.run(nodes, replace(frame, path=path, stack=(*frame.stack, path)))

    def run(self, nodes: Iterable[Node], frame: Frame) -> None:
        for node in nodes:
            self._commands += 1
            if self._commands > MOST_COMMANDS:
                raise _TooMuch
            if isinstance(node, Block):
                self._block(node, frame)
            else:
                self._invoke(node, frame)

    # --- arguments

    def lookup(self, frame: Frame, name: str) -> tuple[Item, ...] | None:
        """A reference's value: a macro's argument, else the variable's."""
        return frame.arguments[name] if name in frame.arguments else frame.scope.get(name)

    def words(self, arguments: Iterable[Argument], frame: Frame) -> list[Value]:
        """The values of the arguments: unquoted ones split into their list elements."""
        found: list[Value] = []
        for index, argument in enumerate(arguments):
            if argument.kind is Kind.BRACKET:
                found.append(Value(argument.text))
                continue
            for choice, value in enumerate(self._possible(argument.text, frame)):
                if argument.kind is Kind.QUOTED:
                    text = value.text.replace(ESCAPED_SEMICOLON, ";")
                    found.append(Value(text, value.when, value.origin, choice, index))
                else:
                    found += (Value(element, value.when, value.origin, choice) for element in elements(value.text))
        return found

    def _possible(self, text: str, frame: Frame) -> list[Value]:
        """The values `text` takes in the builds the commands run in."""
        return [value for value in expanded(text, partial(self.lookup, frame)) if both(frame.condition, value.when)]

    def variables(self, frame: Frame) -> Variables:
        return Variables(
            value=frame.scope.get,
            describe=lambda name: self.descriptions.get(name, name),
            configured=self.configured.__contains__,
        )

    def condition(self, arguments: Iterable[Argument], frame: Frame) -> Condition:
        """The builds in which an `if()` with these arguments holds, for each value its references take."""
        choices = [
            [Value(argument.text)] if argument.kind is Kind.BRACKET else self._possible(argument.text, frame)
            for argument in arguments
        ]
        quoted = [argument.kind is not Kind.UNQUOTED for argument in arguments]
        found = []
        for values in islice(product(*choices), MOST_VALUES):
            operands = [Operand(value.text, kind) for value, kind in zip(values, quoted, strict=True)]
            found.append(both(*(value.when for value in values), condition(operands, self.variables(frame))))
        return either(*found)

    # --- blocks

    def _block(self, block: Block, frame: Frame) -> None:
        opening = block.opening
        if opening.name == "if":
            self._if(block, frame)
        elif opening.name in ("function", "macro"):
            self._define(block, frame)
        elif opening.name == "foreach":
            self._foreach(block, frame)
        elif opening.name == "while":
            holds = both(frame.condition, self.condition(opening.arguments, frame))
            self.run(block.branches[0][1], replace(frame, condition=holds))
        else:  # block()
            self.run(block.branches[0][1], replace(frame, scope=Scope(frame.scope)))

    def _if(self, block: Block, frame: Frame) -> None:
        remaining = frame.condition
        for opening, body in block.branches:
            holds = ALWAYS if opening.name == "else" else self.condition(opening.arguments, frame)
            if branch := both(remaining, holds):
                self.run(body, replace(frame, condition=branch))
            remaining = both(remaining, negated(holds))
            if not remaining:
                return

    def _define(self, block: Block, frame: Frame) -> None:
        opening, body = block.branches[0]
        names = [word.text for word in self.words(opening.arguments, frame)]
        if names:
            macro = opening.name == "macro"
            definition = Definition(names[0].lower(), tuple(names[1:]), body, macro, frame.path, frame.condition)
            self.functions[definition.name] = definition

    def _foreach(self, block: Block, frame: Frame) -> None:
        opening, body = block.branches[0]
        words = self.words(opening.arguments, frame)
        if not words:
            return
        variable, items = words[0].text, _loop_items(words[1:], frame.scope)
        if items is None:
            frame.scope.unset(variable, ALWAYS)
            self.run(body, frame)
            return
        for item in islice(items, MOST_ITERATIONS):
            if holds := both(frame.condition, item.when):
                frame.scope.assign(variable, (Item(item.text, ALWAYS, item.origin),), ALWAYS)
                self.run(body, replace(frame, condition=holds))

    # --- commands

    def _invoke(self, invocation: Invocation, frame: Frame) -> None:
        words = self.words(invocation.arguments, frame)
        if (definition := self.functions.get(invocation.name)) is not None:
            self._call(definition, words, frame)
            return
        if (handler := _HANDLERS.get(invocation.name)) is not None:
            handler(self, frame, words, invocation)
        self.observer.invoked(frame, invocation, words)

    def _call(self, definition: Definition, words: list[Value], frame: Frame) -> None:
        arguments = tuple(word.text for word in words)
        if arguments in definition.seen or definition.name in frame.stack or len(frame.stack) > MOST_NESTED:
            definition.calls = max(definition.calls, 1)
            return
        definition.seen.add(arguments)
        definition.calls += 1
        if definition.calls > MOST_CALLS:
            return
        bound = _bound(definition.parameters, words)
        stack = (*frame.stack, definition.name)
        if definition.macro:
            self.run(
                definition.body,
                replace(frame, arguments={**frame.arguments, **bound}, stack=stack, path=definition.path),
            )
            return
        scope = Scope(frame.scope)
        for name, items in bound.items():
            scope.variables[name] = items
        self.run(
            definition.body, replace(frame, scope=scope, arguments=NO_ARGUMENTS, stack=stack, path=definition.path)
        )

    def set_variable(self, frame: Frame, words: list[Value], invocation: Invocation) -> None:
        if not words or words[0].text.startswith("ENV{") or words[0].text in SYMBOLIC:
            return
        name = words[0].text
        appended = _appended(name, invocation.arguments[1:])
        values = self.words(appended, frame) if appended is not None else words[1:]
        texts = [value.text for value in values]
        if "CACHE" in texts:
            self.configured.add(name)
            return
        scope = frame.scope
        if texts[-1:] == ["PARENT_SCOPE"]:
            scope, values = frame.scope.parent or frame.scope, values[:-1]
        if not values and appended is None:
            scope.unset(name, frame.condition)
            return
        items = (Item(value.text, value.when, value.origin or frame.origin(invocation)) for value in values)
        grouped = (Item(";".join(item.text for item in group), when, origin) for when, origin, group in _grouped(items))
        scope.assign(name, grouped, frame.condition, append=appended is not None)

    def unset_variable(self, frame: Frame, words: list[Value], _: Invocation) -> None:
        if words:
            scope = frame.scope.parent or frame.scope if words[-1].text == "PARENT_SCOPE" else frame.scope
            scope.unset(words[0].text, frame.condition)

    def list_command(self, frame: Frame, words: list[Value], invocation: Invocation) -> None:
        if len(words) < 2:
            return
        operation, name = words[0].text, words[1].text
        origin = frame.origin(invocation)
        if operation in ("APPEND", "PREPEND", "INSERT"):
            added = words[2:] if operation != "INSERT" else words[3:]
            frame.scope.assign(
                name,
                (Item(word.text, word.when, word.origin or origin) for word in added),
                frame.condition,
                append=True,
            )
        elif operation == "REMOVE_ITEM":
            removed = {word.text for word in words[2:]}
            current = frame.scope.get(name) or ()
            frame.scope.assign(name, [item for item in current if item.text not in removed], frame.condition)

    def string_command(self, frame: Frame, words: list[Value], invocation: Invocation) -> None:
        if len(words) >= 2 and words[0].text in ("APPEND", "PREPEND"):
            text = "".join(word.text for word in words[2:])
            frame.scope.assign(
                words[1].text, (Item(text, ALWAYS, frame.origin(invocation)),), frame.condition, append=True
            )

    def separate_arguments(self, frame: Frame, words: list[Value], invocation: Invocation) -> None:
        """`separate_arguments(VARIABLE UNIX_COMMAND "a b")`: the words of a command line, as a list; the old
        form, `separate_arguments(VARIABLE)`, splits the variable's own value."""
        if not words:
            return
        name, texts = words[0].text, words[2:] if len(words) > 2 and words[1].text.endswith("_COMMAND") else words[1:]
        origin = frame.origin(invocation)
        found = texts or [Value(item.text, item.when, item.origin) for item in frame.scope.get(name) or ()]
        items = [Item(part, value.when, value.origin or origin) for value in found for part in value.text.split()]
        frame.scope.assign(name, items, frame.condition)

    def option(self, _frame: Frame, words: list[Value], _: Invocation) -> None:
        if words:
            self.configured.add(words[0].text)

    def find_program(self, frame: Frame, words: list[Value], invocation: Invocation) -> None:
        """The program found is taken to be the first name searched for."""
        names = [word.text for word in words[1:]]
        names = names[names.index("NAMES") + 1 :] if "NAMES" in names else names
        if words and names and frame.scope.get(words[0].text) is None:
            frame.scope.assign(words[0].text, (Item(names[0], ALWAYS, frame.origin(invocation)),), frame.condition)

    def check(self, _frame: Frame, words: list[Value], invocation: Invocation) -> None:
        """A compiler check's result is described by what it checks."""
        texts = [word.text for word in words]
        if invocation.name in ("check_compiler_flag", "check_linker_flag"):
            texts = texts[1:]
        if len(texts) >= 2:
            tool = "linker" if "linker" in invocation.name else "compiler"
            self.descriptions[texts[1]] = f"the {tool} accepts {texts[0]}"

    def parse_arguments(self, frame: Frame, words: list[Value], _: Invocation) -> None:
        texts = [word.text for word in words]
        if texts[:1] == ["PARSE_ARGV"] and len(texts) >= 6:
            arguments = [Value(item.text, item.when, item.origin) for item in frame.scope.get("ARGV") or ()]
            _parse_arguments(frame.scope, texts[2:6], arguments[_number(texts[1]) :])
        elif len(texts) >= 4:
            _parse_arguments(frame.scope, texts[:4], words[4:])

    def include(self, frame: Frame, words: list[Value], _: Invocation) -> None:
        if not words or (path := self._module(frame, words[0].text)) is None or path in frame.stack:
            return
        if len(frame.stack) > MOST_NESTED or (path in self.reached and self._guarded(path)):
            return
        directory = posixpath.dirname(path) or "."
        saved = {name: frame.scope.get(name) for name in ("CMAKE_CURRENT_LIST_DIR", "CMAKE_CURRENT_LIST_FILE")}
        _set_list_file(frame.scope, directory, path)
        self._file(path, replace(frame, condition=both(frame.condition, words[0].when)))
        frame.scope.variables.update(saved)

    def _guarded(self, path: str) -> bool:
        nodes = self.parsed(path) or []
        return any(isinstance(node, Invocation) and node.name == "include_guard" for node in nodes)

    def _module(self, frame: Frame, name: str) -> str | None:
        """The project's file `include(name)` evaluates: a path from the current source directory, or a module in
        `CMAKE_MODULE_PATH`; None for CMake's own modules and files outside the project."""
        if "/" in name or name.endswith(".cmake"):
            return _within(self.files, frame.directory, name)
        modules = frame.scope.get("CMAKE_MODULE_PATH") or ()
        directories = (directory for item in modules for directory in elements(item.text))
        found = (_within(self.files, directory, f"{name}.cmake") for directory in directories)
        return next((path for path in found if path is not None), None)

    def add_subdirectory(self, frame: Frame, words: list[Value], _: Invocation) -> None:
        if not words or len(frame.stack) > MOST_NESTED:
            return
        path = _within(self.files, frame.directory, f"{words[0].text}/{LISTS_FILE}")
        if path is not None and path not in frame.stack:
            self._directory(path, Scope(frame.scope), both(frame.condition, words[0].when))

    def project(self, frame: Frame, words: list[Value], invocation: Invocation) -> None:
        if not words:
            return
        name, origin = words[0].text, frame.origin(invocation)
        top = frame.scope.get("CMAKE_SOURCE_DIR") == (Item(frame.directory),)
        for variable, value in (
            ("PROJECT_NAME", name),
            ("PROJECT_SOURCE_DIR", frame.directory),
            (f"{name}_SOURCE_DIR", frame.directory),
            ("PROJECT_IS_TOP_LEVEL", "ON" if top else "OFF"),
            (f"{name}_IS_TOP_LEVEL", "ON" if top else "OFF"),
        ):
            frame.scope.assign(variable, (Item(value, ALWAYS, origin),), frame.condition)


_CHECKS = ("check_c_compiler_flag", "check_cxx_compiler_flag", "check_compiler_flag", "check_linker_flag")
_HANDLERS: Mapping[str, Callable[[Evaluation, Frame, list[Value], Invocation], None]] = {
    "set": Evaluation.set_variable,
    "unset": Evaluation.unset_variable,
    "list": Evaluation.list_command,
    "string": Evaluation.string_command,
    "option": Evaluation.option,
    "cmake_dependent_option": Evaluation.option,
    "find_program": Evaluation.find_program,
    "cmake_parse_arguments": Evaluation.parse_arguments,
    "separate_arguments": Evaluation.separate_arguments,
    "include": Evaluation.include,
    "add_subdirectory": Evaluation.add_subdirectory,
    "project": Evaluation.project,
    **dict.fromkeys(_CHECKS, Evaluation.check),
}


def _appended(name: str, arguments: tuple[Argument, ...]) -> tuple[Argument, ...] | None:
    """What `set(NAME "${NAME} more")` (or `set(NAME ${NAME} more)`) adds to the variable's value; None for a `set()`
    that does not start from the variable's own value."""
    own = reference(name)
    if not arguments or arguments[0].kind is Kind.BRACKET or not arguments[0].text.startswith(own):
        return None
    rest = arguments[0].text[len(own) :]
    return (*([Argument(rest, arguments[0].kind)] if rest else []), *arguments[1:])


def _depth(path: str) -> tuple[int, str]:
    return path.count("/"), path


def _within(files: frozenset[str], directory: str, path: str) -> str | None:
    """`path` from `directory`, when it is one of the project's `files`."""
    found = posixpath.normpath(posixpath.join(directory, path))
    return found if found in files else None


def _set_list_file(scope: Scope, directory: str, path: str) -> None:
    scope.variables["CMAKE_CURRENT_LIST_DIR"] = (Item(directory),)
    scope.variables["CMAKE_CURRENT_LIST_FILE"] = (Item(path),)


def _set_directory(scope: Scope, directory: str, path: str) -> None:
    scope.variables["CMAKE_CURRENT_SOURCE_DIR"] = (Item(directory),)
    _set_list_file(scope, directory, path)


def _root_scope(directory: str, path: str) -> Scope:
    """A top-level directory's scope, with the variables CMake sets before evaluating its CMakeLists.txt."""
    scope = Scope()
    for name, value in (
        ("CMAKE_COMMAND", "cmake"),
        ("CMAKE_CTEST_COMMAND", "ctest"),
        ("CMAKE_CPACK_COMMAND", "cpack"),
        ("CMAKE_SOURCE_DIR", directory),
    ):
        scope.variables[name] = (Item(value),)
    _set_directory(scope, directory, path)
    return scope


def _grouped(items: Iterable[Item]) -> list[tuple[Condition, Origin | None, list[Item]]]:
    """Items set together in the same builds, which a list joins: one element per value."""
    groups: list[tuple[Condition, Origin | None, list[Item]]] = []
    for item in items:
        if groups and groups[-1][0] == item.when:
            groups[-1][2].append(item)
        else:
            groups.append((item.when, item.origin, [item]))
    return groups


def _loop_items(words: list[Value], scope: Scope) -> list[Item] | None:
    """The items `foreach()` runs for; None for a range, whose numbers are not followed."""
    texts = [word.text for word in words]
    if texts[:1] == ["RANGE"] or texts[:2] == ["IN", "ZIP_LISTS"]:
        return None
    if texts[:1] != ["IN"]:
        return [Item(word.text, word.when, word.origin) for word in words]
    found, mode = [], ""
    for word in words[1:]:
        if word.text in ("LISTS", "ITEMS"):
            mode = word.text
        elif mode == "ITEMS":
            found.append(Item(word.text, word.when, word.origin))
        else:
            found += (
                Item(element, item.when, item.origin)
                for item in scope.get(word.text) or ()
                for element in elements(item.text)
            )
    return found


def _arguments(words: list[Value]) -> list[tuple[Item, ...]]:
    """A call's arguments: each word one, but the values a quoted argument takes in different builds one together."""
    found: list[tuple[Item, ...]] = []
    for index, word in enumerate(words):
        item = Item(word.text, word.when, word.origin)
        if word.argument >= 0 and index and words[index - 1].argument == word.argument:
            found[-1] = (*found[-1], item)
        else:
            found.append((item,))
    return found


def _bound(parameters: tuple[str, ...], words: list[Value]) -> dict[str, tuple[Item, ...]]:
    """A call's arguments, by the names a function or macro gives them, and as ARGV, ARGN, ARGC and ARGV<n>."""
    arguments = _arguments(words)
    bound = {name: arguments[index] if index < len(arguments) else () for index, name in enumerate(parameters)}
    bound |= {f"ARGV{index}": items for index, items in enumerate(arguments)}
    every = tuple(item for items in arguments for item in items)
    rest = tuple(item for items in arguments[len(parameters) :] for item in items)
    return bound | {"ARGV": every, "ARGN": rest, "ARGC": (Item(str(len(arguments))),)}


def _number(text: str) -> int:
    return int(text) if text.isdigit() else 0


def _parse_arguments(scope: Scope, keywords: list[str], words: list[Value]) -> None:
    """`cmake_parse_arguments(PREFIX options one_value multi_value args...)`: each keyword's value, as a variable."""
    prefix, *kinds = keywords
    options, single, multiple = (set(elements(kind)) for kind in kinds)
    values: dict[str, list[Item]] = {name: [] for name in single | multiple}
    unparsed: list[Item] = []
    current: str | None = None
    for word in words:
        if word.text in options:
            values[word.text], current = [Item("TRUE")], None
        elif word.text in values:
            current = word.text
        elif current is not None:
            values[current].append(Item(word.text, word.when, word.origin))
            current = current if current in multiple else None
        else:
            unparsed.append(Item(word.text, word.when, word.origin))
    for name in options:
        scope.variables[f"{prefix}_{name}"] = tuple(values.get(name) or [Item("FALSE")])
    for name in single | multiple:
        scope.variables[f"{prefix}_{name}"] = tuple(values[name]) or None
    scope.variables[f"{prefix}_UNPARSED_ARGUMENTS"] = tuple(unparsed) or None


__all__ = ["Definition", "Evaluation", "Frame", "Observer", "Scope"]
