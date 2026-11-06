"""Write CSV, JSON and plain-text reports."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from student_tool.models import InvalidRecord, Student

logger = logging.getLogger(__name__)

# Spreadsheet apps run cells beginning with these characters as formulas.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class ReportError(Exception):
    """Raised when a report cannot be written."""


def sanitise_cell(value: Any) -> Any:
    """Neutralise text that a spreadsheet would treat as a formula.

    This protects against CSV (formula) injection: a name such as
    ``=HYPERLINK(...)`` is written as ``'=HYPERLINK(...)`` so Excel shows
    it as text. Numbers are returned unchanged, so negative numbers are
    not affected.
    """
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


class ReportGenerator:
    """Write report files into one output folder.

    Attributes:
        output_dir: Folder that all reports are written to.
        include_names: Whether student names are included in reports.
        pass_mark: At-risk threshold for average mark.
        min_attendance_pct: At-risk threshold for attendance.
        written: Paths of the files written so far.
    """

    def __init__(
        self,
        output_dir: Path,
        include_names: bool = True,
        pass_mark: float = 50.0,
        min_attendance_pct: float = 80.0,
    ) -> None:
        """Create the generator and make sure the output folder exists.

        Raises:
            ReportError: If the folder cannot be created.
        """
        self.output_dir = output_dir
        self.include_names = include_names
        self.pass_mark = pass_mark
        self.min_attendance_pct = min_attendance_pct
        self.written: list[Path] = []
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ReportError(
                f"Cannot create output folder {output_dir}: {exc}"
            ) from exc

    def _student_rows(self, students: list[Student]) -> list[dict[str, Any]]:
        """Turn students into dictionaries using the configured settings."""
        return [
            s.to_dict(self.include_names, self.pass_mark,
                      self.min_attendance_pct)
            for s in students
        ]

    def _open(self, filename: str):
        """Open a report file for writing, converting errors to ReportError."""
        path = self.output_dir / filename
        try:
            handle = path.open("w", newline="", encoding="utf-8")
        except OSError as exc:
            raise ReportError(f"Cannot write {path}: {exc}") from exc
        self.written.append(path)
        logger.info("Writing %s", path)
        return handle

    def write_students_csv(
        self, students: list[Student], filename: str = "students_clean.csv"
    ) -> Path:
        """Write one row per student with marks expanded into columns."""
        assessments = sorted({a for s in students for a in s.marks})
        rows = self._student_rows(students)
        base = [k for k in (rows[0] if rows else {}) if k != "marks"]
        if not rows:
            base = ["student_id"] + (["name"] if self.include_names else [])
        # Put assessment columns straight after the identity columns.
        split = base.index("course") + 1 if "course" in base else len(base)
        columns = base[:split] + assessments + base[split:]

        with self._open(filename) as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                marks = row.pop("marks")
                for assessment in assessments:
                    row[assessment] = marks.get(assessment, "")
                writer.writerow({
                    k: sanitise_cell("" if v is None else v)
                    for k, v in row.items()
                })
        return self.written[-1]

    def write_students_json(
        self,
        students: list[Student],
        filename: str = "students_merged.json",
    ) -> Path:
        """Write all merged students, with calculated fields, as JSON."""
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "student_count": len(students),
            "students": self._student_rows(students),
        }
        with self._open(filename) as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        return self.written[-1]

    def write_summary_csv(
        self, summary: list[dict[str, Any]], group_by: str
    ) -> Path:
        """Write the grouped summary table as CSV."""
        filename = f"summary_by_{group_by}.csv"
        columns = list(summary[0]) if summary else [group_by, "students"]
        with self._open(filename) as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in summary:
                writer.writerow({
                    k: sanitise_cell("" if v is None else v)
                    for k, v in row.items()
                })
        return self.written[-1]

    def write_invalid_records(
        self,
        invalid: list[InvalidRecord],
        filename: str = "invalid_records.csv",
    ) -> Path:
        """Write every rejected row with its file, row number and reason."""
        with self._open(filename) as handle:
            writer = csv.writer(handle)
            writer.writerow(["source", "row", "reason"])
            for record in invalid:
                writer.writerow([
                    sanitise_cell(record.source),
                    record.row,
                    sanitise_cell(record.reason),
                ])
        return self.written[-1]

    def write_text_summary(
        self,
        students: list[Student],
        summary: list[dict[str, Any]],
        group_by: str,
        stats: dict[str, int],
        filters: dict[str, Any],
        filename: str = "summary.txt",
    ) -> Path:
        """Write a short human-readable report."""
        text = build_text_summary(
            students, summary, group_by, stats, filters,
            self.pass_mark, self.min_attendance_pct,
        )
        with self._open(filename) as handle:
            handle.write(text)
        return self.written[-1]


def _fmt(value: Any) -> str:
    """Format a number for the text report, showing ``-`` for missing."""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def build_text_summary(
    students: list[Student],
    summary: list[dict[str, Any]],
    group_by: str,
    stats: dict[str, int],
    filters: dict[str, Any],
    pass_mark: float = 50.0,
    min_attendance_pct: float = 80.0,
) -> str:
    """Build the plain-text report as a string (also used for the console).

    Only student IDs, not names, are listed, to limit personal data.
    """
    lines = [
        "STUDENT PERFORMANCE SUMMARY",
        "=" * 60,
        f"Generated: {datetime.now():%Y-%m-%d %H:%M}",
        "",
        "Input",
        f"  Marks rows read / accepted:      "
        f"{stats.get('marks_rows_read', 0)} / "
        f"{stats.get('marks_rows_accepted', 0)}",
        f"  Attendance rows read / accepted: "
        f"{stats.get('attendance_rows_read', 0)} / "
        f"{stats.get('attendance_rows_accepted', 0)}",
        f"  Rows rejected (see invalid_records.csv): "
        f"{stats.get('rows_rejected', 0)}",
        f"  Students merged: {stats.get('students_merged', 0)}",
        "  Filters: "
        + (json.dumps(filters, sort_keys=True) if filters else "none"),
        f"  Students in report: {len(students)}",
        "",
        f"Summary by {group_by}",
    ]
    header = (
        f"  {group_by.upper():<10}{'N':>5}{'MEAN':>9}{'HIGH':>9}"
        f"{'LOW':>9}{'ATT%':>9}{'RISK':>6}"
    )
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for row in summary:
        lines.append(
            f"  {str(row[group_by]):<10}{row['students']:>5}"
            f"{_fmt(row['mean_average_mark']):>9}"
            f"{_fmt(row['highest_average']):>9}"
            f"{_fmt(row['lowest_average']):>9}"
            f"{_fmt(row['mean_attendance_pct']):>9}"
            f"{row['at_risk']:>6}"
        )
    if not summary:
        lines.append("  (no students matched)")

    at_risk = [
        s.student_id for s in students
        if s.is_at_risk(pass_mark, min_attendance_pct)
    ]
    lines += [
        "",
        f"At-risk students (average < {pass_mark:g} or attendance "
        f"< {min_attendance_pct:g}%): {len(at_risk)}",
        "  " + (", ".join(at_risk) if at_risk else "none"),
        "",
    ]
    return "\n".join(lines)
