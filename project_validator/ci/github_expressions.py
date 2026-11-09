"""Evaluating the GitHub Actions expressions of `if:` conditions, as far as a checkout shows their values.

`runner.os`, `matrix.*` and the workflow's and job's `env.*` are known; everything else (`github.*`, `secrets.*`,
`steps.*`, `needs.*`, unknown functions) is not, and makes the result unknown (None) unless the rest decides it:
`false && x` is false and `true || x` is true whatever `x` is. Comparisons ignore case, as GitHub's do. A step's
status functions are judged for a run in which every step succeeds.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

type Value = str | float | bool | None
_UNKNOWN = object()
type Maybe = Value | object  # a Value, or _UNKNOWN

_TOKEN = re.compile(
    r"\s*(?:(?P<string>'(?:[^']|'')*')|(?P<number>-?\d+(?:\.\d+)?)|(?P<operator>==|!=|<=|>=|&&|\|\||[!()<>,])"
    r"|(?P<name>[A-Za-z_][\w.*-]*))"
)
_RUNNER_OS = {"linux": "Linux", "windows": "Windows", "macos": "macOS"}
_STATUS = {"success": True, "always": True, "failure": False, "cancelled": False}


@dataclass(frozen=True, slots=True, kw_only=True)
class Known:
    """What a checkout shows about one job: its OS, its matrix combination and its environment."""

    os: str
    matrix: Mapping[str, object]
    env: Mapping[str, str]
    # Whether `matrix` is the combination's values; a matrix computed by an expression has values that are not seen.
    matrix_known: bool = True


def _tokens(text: str) -> list[str] | None:
    tokens, position = [], 0
    text = text.strip()
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None or match.end() == position:
            return None
        tokens.append(match[0].strip())
        position = match.end()
    return tokens


def _text(value: Maybe) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _truthy(value: Maybe) -> Maybe:
    if value is _UNKNOWN:
        return _UNKNOWN
    return value not in (None, False, 0.0, "")


class _Parser:
    def __init__(self, tokens: list[str], known: Known) -> None:
        self.tokens, self.position, self.known = tokens, 0, known

    def peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self) -> str:
        token = self.tokens[self.position]
        self.position += 1
        return token

    def expression(self) -> Maybe:
        return self.binary(("||",), self.conjunction, _either)

    def conjunction(self) -> Maybe:
        return self.binary(("&&",), self.comparison, _both)

    def comparison(self) -> Maybe:
        return self.binary(("==", "!="), self.unary, _compare)

    def binary(self, operators: tuple[str, ...], operand: Callable[[], Maybe], combine: _Combine) -> Maybe:
        left = operand()
        while self.peek() in operators:
            operator = self.take()
            left = combine(operator, left, operand())
        return left

    def unary(self) -> Maybe:
        if self.peek() == "!":
            self.take()
            value = _truthy(self.unary())
            return _UNKNOWN if value is _UNKNOWN else not value
        return self.primary()

    def primary(self) -> Maybe:
        word = self.take()
        if word == "(":
            value = self.expression()
            self.take()
            return value
        if word.startswith("'"):
            return word[1:-1].replace("''", "'")
        if re.fullmatch(r"-?\d+(?:\.\d+)?", word):
            return float(word)
        if self.peek() == "(":
            return self.call(word)
        return self.reference(word)

    def call(self, name: str) -> Maybe:
        self.take()
        arguments: list[Maybe] = []
        while self.peek() != ")":
            arguments.append(self.expression())
            if self.peek() == ",":
                self.take()
        self.take()
        return _function(name.lower(), arguments)

    def reference(self, name: str) -> Maybe:
        literals: dict[str, Value] = {"true": True, "false": False, "null": None}
        if name in literals:
            return literals[name]
        head, _, rest = name.partition(".")
        if name == "runner.os":
            return _RUNNER_OS.get(self.known.os, _UNKNOWN)
        if head == "matrix":
            return _lookup(self.known.matrix, rest) if self.known.matrix_known else _UNKNOWN
        if head == "env" and rest in self.known.env:
            return self.known.env[rest]
        return _UNKNOWN


type _Combine = Callable[[str, Maybe, Maybe], Maybe]


def _lookup(values: Mapping[str, object], dotted: str) -> Maybe:
    value: object = values
    for key in dotted.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value if isinstance(value, (str, float, bool)) or value is None else str(value)


def _either(_: str, left: Maybe, right: Maybe) -> Maybe:
    left, right = _truthy(left), _truthy(right)
    if True in (left, right):
        return True
    return _UNKNOWN if _UNKNOWN in (left, right) else False


def _both(_: str, left: Maybe, right: Maybe) -> Maybe:
    left, right = _truthy(left), _truthy(right)
    if False in (left, right):
        return False
    return _UNKNOWN if _UNKNOWN in (left, right) else True


def _compare(operator: str, left: Maybe, right: Maybe) -> Maybe:
    if _UNKNOWN in (left, right):
        return _UNKNOWN
    equal = _text(left).lower() == _text(right).lower()
    return equal if operator == "==" else not equal


def _function(name: str, arguments: list[Maybe]) -> Maybe:
    if name in _STATUS and not arguments:
        return _STATUS[name]
    tests: dict[str, Callable[[str, str], bool]] = {
        "contains": lambda text, part: part in text,
        "startswith": str.startswith,
        "endswith": str.endswith,
    }
    if name not in tests or len(arguments) != 2 or _UNKNOWN in arguments:
        return _UNKNOWN
    text, part = (_text(argument).lower() for argument in arguments)
    return tests[name](text, part)


def _parsed(expression: str, known: Known) -> Maybe:
    text = expression.strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2]
    tokens = _tokens(text)
    if not tokens:
        return _UNKNOWN
    parser = _Parser(tokens, known)
    try:
        value = parser.expression()
    except IndexError, RecursionError:
        return _UNKNOWN
    return _UNKNOWN if parser.peek() is not None else value


def evaluate(condition: str, known: Known) -> bool | None:
    """Whether a job or step with `condition` runs, or None when the checkout does not show it."""
    value = _truthy(_parsed(condition, known))
    return None if value is _UNKNOWN else bool(value)


def rendered(expression: str, known: Known) -> str | None:
    """The text GitHub puts in place of `${{ expression }}`, or None when the checkout does not show it."""
    value = _parsed(expression, known)
    return None if value is _UNKNOWN else _text(value)
