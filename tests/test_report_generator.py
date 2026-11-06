"""Tests for report writing."""

import csv
import json

import pytest

from student_tool.models import InvalidRecord, Student
from student_tool.report_generator import ReportGenerator, sanitise_cell


@pytest.mark.parametrize(
    ("value", "expected"),
    [("=1+1", "'=1+1"), ("@SUM(A1)", "'@SUM(A1)"), ("+61", "'+61"),
     ("Ann", "Ann"), (-5, -5), (None, None)],
)
def test_sanitise_cell_blocks_formula_injection(value, expected):
    assert sanitise_cell(value) == expected


def test_students_csv_has_mark_columns_and_safe_cells(tmp_path):
    student = Student("S1", '=HYPERLINK("x")', "MIT703", {"exam": 70.0})
    other = Student("S2", "Ben", "MIT703", {"a1": 50})
    path = ReportGenerator(tmp_path).write_students_csv([student, other])
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["name"].startswith("'=")
    assert rows[0]["exam"] == "70.0" and rows[0]["a1"] == ""
    assert rows[1]["average_mark"] == "50.0"


def test_exclude_names_removes_names_from_every_output(tmp_path):
    student = Student("S1", "Ann Secret", "MIT703", {"a1": 70})
    reports = ReportGenerator(tmp_path, include_names=False)
    reports.write_students_csv([student])
    reports.write_students_json([student])
    for path in reports.written:
        assert "Ann Secret" not in path.read_text(encoding="utf-8")


def test_json_and_invalid_reports_are_well_formed(tmp_path):
    reports = ReportGenerator(tmp_path / "new" / "folder")
    json_path = reports.write_students_json(
        [Student("S1", "Ann", "MIT703", {"a1": 70})]
    )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["student_count"] == 1
    assert data["students"][0]["grade"] == "DI"

    invalid_path = reports.write_invalid_records(
        [InvalidRecord("m.csv", 3, "mark 150 is outside 0-100")]
    )
    lines = invalid_path.read_text(encoding="utf-8").splitlines()
    assert lines == ["source,row,reason", "m.csv,3,mark 150 is outside 0-100"]
