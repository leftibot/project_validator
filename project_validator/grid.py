"""The results of one project as a grid of checks against the ecosystems in each of its units (`--format markdown`)."""

from collections.abc import Mapping, Sequence

from project_validator.core import Status
from project_validator.ecosystems import applies_to
from project_validator.runner import Report

MARKS: Mapping[Status, str] = {
    Status.PASS: "✅",
    Status.WARN: "⚠️",
    Status.FAIL: "❌",
    Status.ERROR: "❗",
    Status.SKIP: "⏭️",
}

_Column = tuple[str, str]  # (unit, ecosystem); a unit of "" is the whole project
_HEAD = (
    "# project_validator results",
    "",
    "✅ pass · ⚠️ warn · ❌ fail · ❗ error · ⏭️ skip · — does not apply",
)


def _md(text: str) -> str:
    """The text with every character markdown would read as markup escaped."""
    return "".join(f"\\{char}" if char in "\\`*_[]<>|~" else char for char in text)


def _columns(rows: Sequence[Report]) -> list[_Column]:
    places = [place for row in rows for place in row.result.places]
    units = {(place.unit, place.ecosystem) for place in places if place.unit}
    whole = {("", place.ecosystem) for place in places} - {("", ecosystem) for _, ecosystem in units}
    return sorted(units | whole, key=lambda column: (column[0] not in ("", "."), column[0], column[1]))


def _heading(column: _Column, single_unit: bool) -> str:
    unit, ecosystem = column
    if single_unit or not unit:
        return _md(ecosystem)
    return _md(f"{ecosystem} in {'the root' if unit == '.' else unit}")


def _cell(row: Report, column: _Column) -> str:
    places = row.result.places
    if not places:
        return MARKS[row.result.status] if column[1] in applies_to(row.check) else "—"
    ecosystem = column[1]
    by_place = {(place.unit, place.ecosystem): place for place in reversed(places)}
    found = by_place.get(column) or by_place.get(("", ecosystem))
    if found is None:
        return "—"
    return f"{MARKS[found.result.status]} {', '.join(_md(tool) for tool in found.tools)}".rstrip()


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = [f"| {' | '.join(headers)} |", "|" + "---|" * len(headers)]
    return lines + [f"| {' | '.join(cells)} |" for cells in rows]


def _grid_section(reports: Sequence[Report]) -> list[str]:
    rows = [report for report in reports if report.check.languages]
    columns = _columns(rows)
    if not columns:
        return []
    single_unit = len({unit for unit, _ in columns}) == 1
    headers = ["Check", *(_heading(column, single_unit) for column in columns)]
    body = [[f"`{row.check.name}`", *(_cell(row, column) for column in columns)] for row in rows]
    return ["## Results by ecosystem", "", *_table(headers, body)]


def _whole_project_section(reports: Sequence[Report]) -> list[str]:
    rows = [
        [f"`{r.check.name}`", f"{MARKS[r.result.status]} {_md(r.result.message)}"]
        for r in reports
        if not r.check.languages
    ]
    if not rows:
        return []
    return ["## Whole project", "", *_table(["Check", "Result"], rows)]


def _findings_section(reports: Sequence[Report]) -> list[str]:
    lines: list[str] = []
    for report in reports:
        result = report.result
        if result.status in (Status.WARN, Status.FAIL, Status.ERROR):
            lines.append(f"- {MARKS[result.status]} `{report.check.name}`: {_md(result.message)}")
            lines.extend(f"  - {_md(detail)}" for detail in result.details)
    return ["## Findings", "", *lines] if lines else []


def render_grid(reports: Sequence[Report]) -> str:
    """Render the reports as markdown sections of grid, whole-project table and findings."""
    sections = [
        section
        for section in (_grid_section(reports), _whole_project_section(reports), _findings_section(reports))
        if section
    ]
    if not sections:
        return ""
    return "\n".join(["\n".join(_HEAD) + "\n", *("\n".join(lines) + "\n" for lines in sections)])
