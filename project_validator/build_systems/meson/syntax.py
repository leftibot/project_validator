"""The Meson build language (see https://mesonbuild.com/Syntax.html): statements (assignments, `if`, `foreach`,
expressions) over strings, numbers, booleans, arrays, dictionaries, function and method calls. Parsing evaluates
nothing."""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field


class MesonSyntaxError(ValueError):
    def __init__(self, line: int, problem: str) -> None:
        super().__init__(f"line {line}: {problem}")


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    text: str
    line: int


_TOKEN = re.compile(
    r"""
      (?P<space>[ \t\r]+|\\\n)
    | (?P<comment>\#[^\n]*)
    | (?P<newline>\n)
    | (?P<string>f?'''.*?'''|f?'(?:\\.|[^'\\\n])*')
    | (?P<number>0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+|\d+)
    | (?P<name>[A-Za-z_]\w*)
    | (?P<operator>==|!=|<=|>=|\+=|[-+*/%<>=?:,.()\[\]{}])
    """,
    re.VERBOSE | re.DOTALL,
)
KEYWORDS = frozenset(
    {"if", "elif", "else", "endif", "foreach", "endforeach", "and", "or", "not", "in", "true", "false", "break"}
    | {"continue"}
)
_OPENING, _CLOSING = "([{", ")]}"


def tokens(text: str) -> Iterator[Token]:
    """The tokens of `text`; a newline inside brackets is blank, as Meson reads it."""
    position, line, depth = 0, 1, 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None or match.lastgroup is None:
            raise MesonSyntaxError(line, f"unexpected {text[position]!r}")
        kind, found = match.lastgroup, match[0]
        depth += (found in _OPENING) - (found in _CLOSING) if kind == "operator" else 0
        if kind == "name" and found in KEYWORDS:
            kind = "keyword"
        if kind not in ("space", "comment") and not (kind == "newline" and depth > 0):
            yield Token(kind, found, line)
        line += found.count("\n")
        position = match.end()
    yield Token("newline", "\n", line)
    yield Token("end", "", line)


# --- the tree


@dataclass(frozen=True, slots=True)
class Literal:
    value: object  # str, int or bool
    formatted: bool = False  # an f-string, whose @name@ are replaced


@dataclass(frozen=True, slots=True)
class Name:
    name: str


@dataclass(frozen=True, slots=True)
class Array:
    items: tuple[Expression, ...]


@dataclass(frozen=True, slots=True)
class Dictionary:
    items: tuple[tuple[Expression, Expression], ...]


@dataclass(frozen=True, slots=True)
class Arguments:
    positional: tuple[Expression, ...] = ()
    keywords: tuple[tuple[str, Expression], ...] = ()

    def keyword(self, name: str) -> Expression | None:
        return next((value for key, value in self.keywords if key == name), None)


@dataclass(frozen=True, slots=True)
class Call:
    """A function call (`target` None) or a method call on `target`."""

    name: str
    arguments: Arguments
    target: Expression | None = None


@dataclass(frozen=True, slots=True)
class Index:
    target: Expression
    index: Expression


@dataclass(frozen=True, slots=True)
class Operation:
    """A unary (`right` None), binary or ternary (`otherwise`) operation."""

    operator: str
    left: Expression
    right: Expression | None = None
    otherwise: Expression | None = None


type Expression = Literal | Name | Array | Dictionary | Call | Index | Operation


@dataclass(frozen=True, slots=True)
class Assignment:
    name: str
    operator: str  # "=" or "+="
    value: Expression
    line: int


@dataclass(frozen=True, slots=True)
class Statement:
    expression: Expression
    line: int


@dataclass(slots=True)
class If:
    """`if` and each `elif` with its condition, then `else` (condition None), each with its statements."""

    branches: list[tuple[Expression | None, list[Node]]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Foreach:
    names: tuple[str, ...]
    items: Expression
    body: list[Node]


@dataclass(frozen=True, slots=True)
class Jump:
    keyword: str  # "break" or "continue"


type Node = Assignment | Statement | If | Foreach | Jump

_COMPARISONS = frozenset({"==", "!=", "<", ">", "<=", ">="})


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = list(tokens(text))
        self.position = 0

    @property
    def token(self) -> Token:
        return self.tokens[self.position]

    def _at(self, *texts: str) -> bool:
        return self.token.kind in ("operator", "keyword") and self.token.text in texts

    def _take(self, *texts: str) -> Token | None:
        if self._at(*texts):
            self.position += 1
            return self.tokens[self.position - 1]
        return None

    def _expect(self, text: str) -> Token:
        found = self._take(text)
        if found is None:
            raise MesonSyntaxError(self.token.line, f"expected {text!r}, found {self.token.text!r}")
        return found

    def _newlines(self) -> None:
        while self.token.kind == "newline":
            self.position += 1

    def block(self, *ends: str) -> list[Node]:
        """Statements until one of the keywords `ends` (or the end of the file, when there are none)."""
        nodes: list[Node] = []
        self._newlines()
        while not self._at(*ends) and self.token.kind != "end":
            nodes.append(self.statement())
            self._newlines()
        if ends and self.token.kind == "end":
            raise MesonSyntaxError(self.token.line, f"expected {' or '.join(ends)}")
        return nodes

    def statement(self) -> Node:
        line = self.token.line
        if self._take("if"):
            return self._if()
        if self._take("foreach"):
            return self._foreach()
        if jump := self._take("break", "continue"):
            return Jump(jump.text)
        expression = self.expression()
        if isinstance(expression, Name) and (operator := self._take("=", "+=")):
            return Assignment(expression.name, operator.text, self.expression(), line)
        if self.token.kind not in ("newline", "end"):
            raise MesonSyntaxError(line, f"unexpected {self.token.text!r}")
        return Statement(expression, line)

    def _if(self) -> If:
        found = If()
        condition: Expression | None = self.expression()
        while True:
            body = self.block("elif", "else", "endif")
            found.branches.append((condition, body))
            if self._take("endif"):
                return found
            condition = self.expression() if self._take("elif") else None
            if condition is None:
                self._expect("else")

    def _foreach(self) -> Foreach:
        names = [self._name()]
        while self._take(","):
            names.append(self._name())
        self._expect(":")
        items = self.expression()
        body = self.block("endforeach")
        self._expect("endforeach")
        return Foreach(tuple(names), items, body)

    def _name(self) -> str:
        token = self.token
        if token.kind != "name":
            raise MesonSyntaxError(token.line, f"expected a name, found {token.text!r}")
        self.position += 1
        return token.text

    # --- expressions, by precedence

    def expression(self) -> Expression:
        condition = self._or()
        if self._take("?"):
            chosen = self.expression()
            self._expect(":")
            return Operation("?", condition, chosen, self.expression())
        return condition

    def _or(self) -> Expression:
        found = self._and()
        while self._take("or"):
            found = Operation("or", found, self._and())
        return found

    def _and(self) -> Expression:
        found = self._not()
        while self._take("and"):
            found = Operation("and", found, self._not())
        return found

    def _not(self) -> Expression:
        return Operation("not", self._not()) if self._take("not") else self._comparison()

    def _comparison(self) -> Expression:
        found = self._sum()
        if self._at("not") and self.tokens[self.position + 1].text == "in":
            self.position += 2
            return Operation("not in", found, self._sum())
        if operator := self._take(*_COMPARISONS, "in"):
            return Operation(operator.text, found, self._sum())
        return found

    def _sum(self) -> Expression:
        found = self._product()
        while operator := self._take("+", "-"):
            found = Operation(operator.text, found, self._product())
        return found

    def _product(self) -> Expression:
        found = self._unary()
        while operator := self._take("*", "/", "%"):
            found = Operation(operator.text, found, self._unary())
        return found

    def _unary(self) -> Expression:
        return Operation("-", self._unary()) if self._take("-") else self._postfix()

    def _postfix(self) -> Expression:
        found = self._primary()
        while True:
            if self._take("."):
                name = self._name()
                self._expect("(")
                found = Call(name, self._arguments(), found)
            elif self._take("["):
                found = Index(found, self.expression())
                self._expect("]")
            else:
                return found

    def _primary(self) -> Expression:
        token = self.token
        self.position += 1
        if token.kind == "string":
            return _string(token.text)
        if token.kind == "number":
            return Literal(int(token.text, 0 if token.text[1:2].isalpha() else 10))
        if token.kind == "keyword" and token.text in ("true", "false"):
            return Literal(token.text == "true")
        if token.kind == "name":
            return Call(token.text, self._arguments()) if self._take("(") else Name(token.text)
        return self._bracketed(token)

    def _bracketed(self, token: Token) -> Expression:
        if token.text == "(":
            found = self.expression()
            self._expect(")")
            return found
        if token.text == "[":
            return Array(tuple(self._items("]", self.expression)))
        if token.text == "{":
            return Dictionary(tuple(self._items("}", self._pair)))
        raise MesonSyntaxError(token.line, f"unexpected {token.text!r}")

    def _pair(self) -> tuple[Expression, Expression]:
        key = self.expression()
        self._expect(":")
        return key, self.expression()

    def _items[T](self, closing: str, item: Callable[[], T]) -> Iterator[T]:
        while not self._take(closing):
            yield item()
            if not self._take(","):
                self._expect(closing)
                return

    def _arguments(self) -> Arguments:
        positional: list[Expression] = []
        keywords: list[tuple[str, Expression]] = []
        while not self._take(")"):
            value = self.expression()
            if isinstance(value, Name) and self._take(":"):
                keywords.append((value.name, self.expression()))
            else:
                positional.append(value)
            if not self._take(","):
                self._expect(")")
                break
        return Arguments(tuple(positional), tuple(keywords))


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", "0": "\0"}


def _string(text: str) -> Literal:
    formatted = text.startswith("f")
    body = text.removeprefix("f")
    if body.startswith("'''"):
        return Literal(body[3:-3], formatted)
    unescaped = re.sub(r"\\(.)", lambda match: _ESCAPES.get(match[1], match[0]), body[1:-1])
    return Literal(unescaped, formatted)


def parse(text: str) -> list[Node]:
    """The statements of a meson.build (or meson.options) file."""
    parser = _Parser(text.removeprefix("\ufeff"))
    try:
        return parser.block()
    except RecursionError as error:
        raise MesonSyntaxError(parser.token.line, "nested too deeply to read") from error


__all__ = [
    "Arguments",
    "Array",
    "Assignment",
    "Call",
    "Dictionary",
    "Expression",
    "Foreach",
    "If",
    "Index",
    "Jump",
    "Literal",
    "MesonSyntaxError",
    "Name",
    "Node",
    "Operation",
    "Statement",
    "parse",
]
