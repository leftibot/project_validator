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

_Column = tuple[str, str]  # (unit, ecosystem)


def _escape(text: str) -> str:
    return text.replace("|", "\\|")


def _columns(rows: Sequence[Report]) -> list[_Column]:
    found = {(place.unit, place.ecosystem) for row in rows for place in row.result.places}
    return sorted(found, key=lambda column: (column[0] != ".", column[0], column[1]))


def _heading(column: _Column, single_unit: bool) -> str:
    unit, ecosystem = column
    if single_unit:
        return ecosystem
    return f"{ecosystem} in {'the root' if unit == '.' else unit}"


def _cell(row: Report, column: _Column) -> str:
    places = row.result.places
    if not places:
        return MARKS[row.result.status] if column[1] in applies_to(row.check) else "—"
    here = [place for place in places if (place.unit, place.ecosystem) == column]
    if not here:
        return "—"
    return _escape(f"{MARKS[here[0].result.status]} {', '.join(here[0].tools)}".rstrip())


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
        [f"`{r.check.name}`", _escape(f"{MARKS[r.result.status]} {r.result.message}")]
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
            lines.append(f"- {MARKS[result.status]} `{report.check.name}`: {result.message}")
            lines.extend(f"  - {detail}" for detail in result.details)
    return ["## Findings", "", *lines] if lines else []


def render_grid(reports: Sequence[Report]) -> str:
    """Render the reports as markdown sections of grid, whole-project table and findings."""
    sections = [
        section
        for section in (_grid_section(reports), _whole_project_section(reports), _findings_section(reports))
        if section
    ]
    return "\n".join("\n".join(lines) + "\n" for lines in sections)
