"""PyYAML support; it is required, but imported here so a missing install is reported cleanly instead of crashing."""

import importlib
from dataclasses import dataclass
from functools import cache
from types import ModuleType
from typing import Any

MISSING_MESSAGE = "PyYAML >= 6.0 is required (python3 -m pip install PyYAML, or the distro's python3-yaml package)"
NESTED_MESSAGE = "nested too deeply to read"


class YamlError(Exception):
    def __init__(self, message: str, line: int | None = None, column: int | None = None) -> None:
        super().__init__(message)
        # 1-based, when the parser knows where the problem is.
        self.line = line
        self.column = column


def _import_yaml() -> ModuleType | None:
    try:
        return importlib.import_module("yaml")
    except ImportError:
        return None


_yaml = _import_yaml()


def available() -> bool:
    return _yaml is not None


@dataclass(frozen=True, slots=True)
class Tagged:
    """A value with a local tag a tool defines (GitLab's `!reference [.setup, script]`, CloudFormation's `!Ref`)."""

    tag: str
    value: object


@cache
def _loader() -> type:
    """A safe loader that keeps values with local tags as `Tagged` instead of rejecting them."""
    yaml: Any = _yaml

    class Loader(yaml.SafeLoader):  # type: ignore[misc]
        pass

    def tagged(loader: Any, suffix: str, node: Any) -> Tagged:
        if isinstance(node, yaml.SequenceNode):
            return Tagged(tag=f"!{suffix}", value=loader.construct_sequence(node))
        if isinstance(node, yaml.MappingNode):
            return Tagged(tag=f"!{suffix}", value=loader.construct_mapping(node))
        return Tagged(tag=f"!{suffix}", value=loader.construct_scalar(node))

    Loader.add_multi_constructor("!", tagged)
    return Loader


def load(text: str) -> object:
    """The YAML document of `text`; a value with a local tag is a `Tagged`."""
    if _yaml is None:
        raise YamlError(MISSING_MESSAGE)
    try:
        return _yaml.load(text, Loader=_loader())
    except _yaml.YAMLError as error:
        raise YamlError(str(error).replace("\n", " ")) from error
    except RecursionError as error:
        raise YamlError(NESTED_MESSAGE) from error


def check_documents(text: str) -> None:
    """Parse every document of `text` without constructing values, so any tag (`!reference`, `!Ref`) is accepted:
    only whether the text is well-formed YAML is judged."""
    if _yaml is None:
        raise YamlError(MISSING_MESSAGE)
    try:
        for _ in _yaml.compose_all(text, Loader=_yaml.SafeLoader):
            pass
    except _yaml.MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        problem = error.problem or error.context or "invalid YAML"
        raise YamlError(problem, mark.line + 1, mark.column + 1) if mark else YamlError(problem) from error
    except _yaml.YAMLError as error:
        raise YamlError(str(error).replace("\n", " ")) from error
    except RecursionError as error:
        raise YamlError(NESTED_MESSAGE) from error
