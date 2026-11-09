"""Generator expressions (see cmake-generator-expressions(7)), which CMake evaluates per build: `$<$<CONFIG:Debug>:-O0>`
is `-O0` in Debug builds and nothing in the others. Each value an argument takes is found with the builds it is in."""

import re
from collections.abc import Callable, Iterator, Mapping

from project_validator.build_systems.cmake.conditions import COMPILER, CONFIGURATION, LANGUAGE, PLATFORM, constant
from project_validator.build_systems.cmake.values import MOST_VALUES, Value, referenced
from project_validator.facts.conditions import ALWAYS, NEVER, Condition, both, either, negated, requiring

_START = "$<"


def _split(text: str, separator: str) -> list[str]:
    """`text` split on `separator` outside nested generator expressions."""
    parts, depth, start = [], 0, 0
    for position, character in enumerate(text):
        if text.startswith(_START, position):
            depth += 1
        elif character == ">" and depth:
            depth -= 1
        elif character == separator and not depth:
            parts.append(text[start:position])
            start = position + 1
    return [*parts, text[start:]]


def _head(content: str) -> tuple[str, str, str]:
    """An expression's name (or condition) and arguments, split at the first colon outside nested expressions."""
    name, *rest = _split(content, ":")
    return name, ":" if rest else "", ":".join(rest)


def _end(text: str, start: int) -> int:
    """The position of the `>` closing the expression whose content starts at `start`; -1 when it is not closed."""
    depth = 1
    for position in range(start, len(text)):
        if text.startswith(_START, position):
            depth += 1
        elif text[position] == ">":
            depth -= 1
            if depth == 0:
                return position
    return -1


def _parts(text: str) -> Iterator[tuple[str, bool]]:
    """(text, whether it is an expression's content) for each part of `text`."""
    position = 0
    while (start := text.find(_START, position)) >= 0 and (end := _end(text, start + 2)) >= 0:
        yield text[position:start], False
        yield text[start + 2 : end], True
        position = end + 1
    yield text[position:], False


def _listed(evaluate: Callable[[list[str]], Condition]) -> Callable[[list[str]], Condition]:
    return lambda arguments: evaluate([name for argument in arguments for name in argument.split(",") if name])


def _lang_and_id(arguments: list[str]) -> Condition:
    language, *compilers = arguments
    return both(LANGUAGE.equal_to(language), COMPILER.listed(compilers))


def _bool(arguments: list[str]) -> Condition:
    text = ",".join(arguments)
    if (name := referenced(text)) is not None:
        return requiring(name)
    return NEVER if constant(text) is False else ALWAYS


def _streq(arguments: list[str]) -> Condition | None:
    if len(arguments) != 2 or any("${" in argument or _START in argument for argument in arguments):
        return None
    return ALWAYS if arguments[0] == arguments[1] else NEVER


_COMPILER_ID = re.compile(r"(?:C|CXX|CUDA|OBJC|OBJCXX|Fortran|HIP|ASM\w*)_COMPILER_ID")
_TESTS: Mapping[str, Callable[[list[str]], Condition | None]] = {
    "CONFIG": _listed(CONFIGURATION.listed),
    "PLATFORM_ID": _listed(PLATFORM.listed),
    "COMPILE_LANGUAGE": _listed(LANGUAGE.listed),
    "LINK_LANGUAGE": _listed(LANGUAGE.listed),
    "COMPILE_LANG_AND_ID": _lang_and_id,
    "LINK_LANG_AND_ID": _lang_and_id,
    "BOOL": _bool,
    "STREQUAL": _streq,
}


def test(text: str) -> Condition:
    """The builds in which `text`, a boolean expression or a constant, is 1."""
    if (known := constant(text)) is not None:
        return ALWAYS if known else NEVER
    contents = [content for content, expression in _parts(text) if expression]
    if len(contents) != 1 or not text.startswith(_START) or not text.endswith(">"):
        return requiring(text)
    name, _, rest = _head(contents[0])
    arguments = _split(rest, ",")
    found: Condition | None
    if name == "NOT":
        found = negated(test(rest))
    elif name in ("AND", "OR"):
        found = (both if name == "AND" else either)(*(test(argument) for argument in arguments))
    elif _COMPILER_ID.fullmatch(name):
        found = _listed(COMPILER.listed)(arguments)
    else:
        found = _TESTS[name](arguments) if name in _TESTS else None
    return requiring(text) if found is None else found


_PASSED = frozenset({"BUILD_INTERFACE", "BUILD_LOCAL_INTERFACE", "HOST_LINK", "DEVICE_LINK", "LINK_ONLY"})
_CHARACTERS = {"SEMICOLON": ";", "COMMA": ",", "ANGLE-R": ">", "INSTALL_INTERFACE": ""}


def _in(when: Condition, value: str) -> list[Value]:
    """The values `value` takes in the builds `when` names."""
    return [Value(part.text, held) for part in _generated(value) if (held := both(when, part.when))]


def _conditional(when: Condition, value: str) -> list[Value]:
    """`$<condition:value>`: the value where the condition holds, nothing elsewhere."""
    found = _in(when, value)
    return [*found, Value("", rest)] if (rest := negated(when)) else found


def _expression(content: str) -> list[Value]:
    """The values one expression (`content`, between `$<` and `>`) takes."""
    name, separator, rest = _head(content)
    if name in ("0", "1") or name.startswith(_START):
        return _conditional(test(name), rest)
    if name == "IF" and len(arguments := _split(rest, ",")) == 3:
        when = test(arguments[0])
        return [*_in(when, arguments[1]), *_in(negated(when), arguments[2])]
    if name in _PASSED:
        return _generated(rest)
    if name in _CHARACTERS:
        return [Value(_CHARACTERS[name])]
    if (separator and name in _TESTS) or name in ("NOT", "AND", "OR") or _COMPILER_ID.fullmatch(name):
        when = test(f"$<{content}>")
        return [Value("1", when), Value("0", negated(when))]
    return [Value(f"$<{content}>")]


def _generated(text: str) -> list[Value]:
    values = [Value("")]
    for part, expression in _parts(text):
        found = _expression(part) if expression else [Value(part)]
        values = [
            Value(value.text + more.text, when)
            for value in values
            for more in found
            if (when := both(value.when, more.when))
        ][:MOST_VALUES]
    return [value for value in values if value.when]


def generated(text: str) -> list[Value]:
    """The values `text` takes, with the builds it takes each in; expressions that are not understood (or are nested
    too deeply) are kept."""
    try:
        return _generated(text)
    except RecursionError:
        return [Value(text)]


__all__ = ["generated", "test"]
