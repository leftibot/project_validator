"""Text-search helpers used by the checks and by heuristic CI parsing."""

import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Pattern:
    name: str
    regex: re.Pattern[str]


def pattern(name: str, regex: str) -> Pattern:
    return Pattern(name, re.compile(regex, re.IGNORECASE))


def matching_names(texts: Iterable[str], patterns: Iterable[Pattern]) -> list[str]:
    """Names of the patterns found in any text, in pattern order and without duplicates."""
    texts = tuple(texts)
    found = (p.name for p in patterns if any(p.regex.search(text) for text in texts))
    return list(dict.fromkeys(found))


# A string, a comment, or a comma that only whitespace separates from the closing bracket.
_JSONC_TOKENS = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|,(?=\s*[}\]])', re.DOTALL)


def _blank_unless_string(match: re.Match[str]) -> str:
    token = match[0]
    return token if token.startswith('"') else re.sub(r"[^\n]", " ", token)


def strip_json_comments(text: str) -> str:
    """JSON with comments and trailing commas as plain JSON; comments become blanks, so positions are kept."""
    return _JSONC_TOKENS.sub(_blank_unless_string, _JSONC_TOKENS.sub(_blank_unless_string, text))


class JsonSyntaxError(ValueError):
    """JSON that is not one value, and where (line and column, from 1) the token that breaks it starts."""

    def __init__(self, message: str, line: int, column: int) -> None:
        super().__init__(message)
        self.line, self.column = line, column


_JSON_TOKEN = re.compile(
    r"""[ \t\n\r]*(?:(?P<open>[\[{])|(?P<close>[\]}])|(?P<colon>:)|(?P<comma>,)"""
    r"""|(?P<value>"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"|true|false|null"""
    r"""|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?))"""
)


# An open container and what may come next in it: "value", "key", "colon", "comma or close" (or "value or close" and
# "key or close" right after it opens).
type _Stack = list[list[str]]


def _value(stack: _Stack, match: re.Match[str]) -> bool:
    """A value or an opening bracket: where a value (or, as a key, a string) may come."""
    expecting = (stack[-1][1] if stack else "value").removesuffix(" or close")
    if expecting not in ("value", "key") or (expecting == "key" and not str(match["value"] or "").startswith('"')):
        return False
    if stack:
        stack[-1][1] = "colon" if expecting == "key" else "comma or close"
    if match["open"]:
        stack.append([match["open"], "key or close" if match["open"] == "{" else "value or close"])
    return True


def _close(stack: _Stack, match: re.Match[str]) -> bool:
    if not stack or stack[-1][1] == "value" or stack[-1][1] in ("key", "colon"):
        return False
    return stack.pop()[0] == {"]": "[", "}": "{"}[match["close"]]


def _colon(stack: _Stack, _match: re.Match[str]) -> bool:
    if not stack or stack[-1][1] != "colon":
        return False
    stack[-1][1] = "value"
    return True


def _comma(stack: _Stack, _match: re.Match[str]) -> bool:
    if not stack or stack[-1][1] != "comma or close":
        return False
    stack[-1][1] = "key" if stack[-1][0] == "{" else "value"
    return True


_READ = {"open": _value, "value": _value, "close": _close, "colon": _colon, "comma": _comma}


def check_json(text: str) -> None:
    """Whether `text` is one JSON value, read without recursion (so nested deeper than Python's parser recurses, as
    a JSON parser's test data is): each container on a stack, with what may come next in it. `JsonSyntaxError` where
    the token that breaks it starts."""
    stack: _Stack = []
    position, done = 0, False
    while not done and (match := _JSON_TOKEN.match(text, position)) is not None:
        kind = match.lastgroup or ""
        position = match.start(kind)
        if not _READ[kind](stack, match):
            break
        position, done = match.end(), not stack and kind != "colon" and kind != "comma"
    if not done or text[position:].strip(" \t\n\r"):
        line = text.count("\n", 0, position) + 1
        raise JsonSyntaxError("malformed JSON", line, position - text.rfind("\n", 0, position))
