"""Splitting the shell scripts CI runs into commands, the way a POSIX shell splits simple commands.

Only what the validator needs is understood: line continuations, comments, quoting (a quoted string may span
lines), the operators that separate commands (`;`, `&&`, `||`, `|`, `&`), and command substitution (`$(…)` and
backquotes), whose commands run before the command they are part of. PowerShell scripts (`powershell=True`) are split
the same way, with PowerShell's escape character, the backquote, in place of the backslash (which is text there).
Leading `NAME=value` assignments are the command's environment. Compound commands (`if`, `for`, `case`) and
here-documents are not interpreted; their lines are split like any other.
"""

import re
import shlex
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

_CONTINUATION = re.compile(r"\\\r?\n")
_POWERSHELL_CONTINUATION = re.compile(r"`\r?\n")
_SEPARATORS = frozenset({";", "&&", "||", "|", "&", ";;", "|&"})
_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
# Words that only introduce or wrap the command that follows.
_KEYWORDS = frozenset({"then", "do", "else", "elif", "if", "while", "until", "!", "{", "}"})
_CLOSING = frozenset({"fi", "done", "esac"})
# A redirection operator (`>`, `2>&1`'s `>&`, `<<`); it and its target are not arguments.
_REDIRECTION = re.compile(r"^[<>&|]*[<>][<>&|]*$")


@dataclass(frozen=True, slots=True, kw_only=True)
class ShellCommand:
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...]
    line: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Unsplittable:
    """A line the shell rules above cannot split, such as one with an unbalanced quote."""

    line: str
    reason: str


_OPERATOR_CHARACTERS = ";&|()<>"
# Operator characters that are quoted or escaped are text: they stand in for them while the line is split.
_STAND_INS = {character: chr(0xE000 + index) for index, character in enumerate(_OPERATOR_CHARACTERS)}
_RESTORED = str.maketrans({stand_in: character for character, stand_in in _STAND_INS.items()})


def _protected(line: str, escape: str = "\\") -> str:
    """`line` with the operator characters that are quoted (`awk -F '|'`) or escaped (`\\;`) replaced by stand-ins."""
    out: list[str] = []
    quote: str | None = None
    escaped = False
    for character in line:
        if escaped or (quote is not None and character != quote):
            out.append(_STAND_INS.get(character, character))
            escaped = character == escape and quote == '"' and not escaped
            continue
        escaped = character == escape and quote is None
        if character in "'\"":
            quote = None if quote == character else character
        out.append(character)
    return "".join(out)


def _words(line: str, escape: str = "\\") -> list[str]:
    lexer = shlex.shlex(_protected(line, escape), posix=True, punctuation_chars=_OPERATOR_CHARACTERS)
    lexer.escape = escape
    lexer.whitespace_split = True
    lexer.commenters = "#"
    return list(lexer)  # quoted operator characters stay stand-ins until the commands are split (see `_command`)


def _without_redirections(words: list[str]) -> list[str]:
    kept: list[str] = []
    skip = False
    for word in words:
        if skip:
            skip = False
        elif _REDIRECTION.match(word):
            if kept and kept[-1].isdigit():
                kept.pop()  # the descriptor of `2>`
            skip = True
        else:
            kept.append(word)
    return kept


def _command(words: list[str], line: str) -> ShellCommand | None:
    words = _without_redirections(words)
    while words and words[0] in _KEYWORDS:
        words = words[1:]
    if words and words[0] in _CLOSING:
        return None
    env = []
    while words and _ASSIGNMENT.match(words[0]):
        name, value = words[0].split("=", 1)
        env.append((name, value.translate(_RESTORED)))
        words = words[1:]
    argv = tuple(word.translate(_RESTORED) for word in words if word not in {"(", ")"})
    return ShellCommand(argv=argv, env=tuple(env), line=line) if argv else None


def _commands_of(words: list[str], line: str) -> Iterator[ShellCommand]:
    current: list[str] = []
    for word in [*words, ";"]:
        if word in _SEPARATORS:
            if (command := _command(current, line)) is not None:
                yield command
            current = []
        else:
            current.append(word)


_PLACEHOLDER = re.compile(r"__opaque_(\d+)__")


@dataclass(slots=True)
class _Hidden:
    """The text hidden from the splitter while a script is split, by placeholder: opaque text, and command
    substitutions with the commands they run."""

    texts: list[str] = field(default_factory=list)
    substitutions: dict[int, str] = field(default_factory=dict)

    def shown(self, text: str) -> str:
        return _PLACEHOLDER.sub(lambda match: self.texts[int(match[1])], text)

    def hide(self, text: str, commands: str | None = None) -> str:
        self.texts.append(self.shown(text))
        if commands is not None:
            self.substitutions[len(self.texts) - 1] = self.shown(commands)
        return f"__opaque_{len(self.texts) - 1}__"

    def substituted(self, line: str) -> list[str]:
        """The commands of the command substitutions in `line`."""
        return [
            self.substitutions[index] for index in map(int, _PLACEHOLDER.findall(line)) if index in self.substitutions
        ]

    def restored(self, command: ShellCommand) -> ShellCommand:
        return ShellCommand(
            argv=tuple(map(self.shown, command.argv)),
            env=tuple((name, self.shown(value)) for name, value in command.env),
            line=self.shown(command.line),
        )


def split_script(
    script: str, opaque: re.Pattern[str] | None = None, *, powershell: bool = False
) -> Iterator[ShellCommand | Unsplittable]:
    """The simple commands of `script`, in order, each with the line it was written on; the commands of a command
    substitution come before the command it is part of.

    Text matching `opaque` (such as a CI expression the CI service evaluates before the shell runs) is kept as
    written, quotes and all, inside the word it is part of.
    """
    try:
        found = list(_split_script(script, opaque, powershell=powershell))
    except RecursionError:
        # Line by line, so only the lines nested too deeply are lost.
        found = []
        for line in script.splitlines():
            try:
                found.extend(_split_script(line, opaque, powershell=powershell))
            except RecursionError:
                found.append(Unsplittable(line=line, reason="nested too deeply to split"))
    yield from found


def _split_script(
    script: str, opaque: re.Pattern[str] | None, *, powershell: bool
) -> Iterator[ShellCommand | Unsplittable]:
    hidden = _Hidden()
    # Opaque text first: a Make variable `$(CC)` is not a command substitution.
    if opaque is not None:
        script = opaque.sub(lambda match: hidden.hide(match[0]), script)
    escape = "`" if powershell else "\\"
    script = _substitutions(script, hidden.hide, escape)
    continuation = _POWERSHELL_CONTINUATION if powershell else _CONTINUATION
    for line, words in _lines(continuation.sub(" ", script).splitlines(), escape):
        for commands in hidden.substituted(line):
            yield from _split_script(commands, opaque, powershell=powershell)
        if isinstance(words, ValueError):
            yield Unsplittable(line=hidden.shown(line), reason=str(words))
            continue
        yield from map(hidden.restored, _commands_of(words, line))


def _substitutions(script: str, hide: Callable[[str, str], str], escape: str = "\\") -> str:
    """`script` with each command substitution outside single quotes (`$(…)`, and `` `…` `` where the backquote is no
    escape; not arithmetic `$((…))`) replaced by what `hide` returns for its text and its commands."""
    out: list[str] = []
    index, quote = 0, ""
    while index < len(script):
        character = script[index]
        end = None if quote == "'" else _substitution_end(script, index, backquotes=escape != "`")
        if end is not None:
            text = script[index:end]
            out.append(hide(text, text[2:-1] if text.startswith("$(") else text[1:-1]))
            index = end
            continue
        if character == escape and quote != "'":
            out.append(script[index : index + 2])
            index += 2
            continue
        if character in "'\"" and quote in ("", character):
            quote = "" if quote else character
        out.append(character)
        index += 1
    return "".join(out)


def _substitution_end(script: str, start: int, *, backquotes: bool = True) -> int | None:
    """Where the command substitution starting at `start` ends (just after it), or None if none starts there."""
    if backquotes and script.startswith("`", start):
        end = script.find("`", start + 1)
        return None if end < 0 else end + 1
    if not script.startswith("$(", start) or script.startswith("$((", start):
        return None
    depth = 0
    for index in range(start + 1, len(script)):
        depth += {"(": 1, ")": -1}.get(script[index], 0)
        if depth == 0:
            return index + 1
    return None


def _lines(raw: list[str], escape: str = "\\") -> Iterator[tuple[str, list[str] | ValueError]]:
    """Each line with its words; a quoted string that is still open at the end of a line goes on to the next."""
    lines = iter(raw)
    for first in lines:
        line = first.strip()
        if not line or line.startswith("#"):
            continue
        while True:
            try:
                yield line, _words(line, escape)
                break
            except ValueError as error:
                following = next(lines, None)
                if following is None or "quotation" not in str(error):
                    yield line, error
                    break
                line = f"{line}\n{following}"
