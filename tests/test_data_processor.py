"""Tests for validation, cleaning, merging, filtering and aggregation."""

import pytest

from student_tool.data_processor import (
    DataProcessor,
    RecordError,
    apply_filters,
    clean_student_id,
    group_summary,
    parse_mark,
)


def marks_row(student_id="S1", name="Ann", course="MIT703", **marks):
    """Build a marks record the way csv.DictReader would."""
    return {"student_id": student_id, "name": name, "course": course, **marks}


# --- field parsing -------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [("75", 75.0), (" 0 ", 0.0), ("100", 100.0), (88.456, 88.46),
     ("", None), (None, None)],
)
def test_parse_mark_valid_values(raw, expected):
    assert parse_mark(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "-1", "100.5", "nan", True])
def test_parse_mark_rejects_invalid_values(raw):
    with pytest.raises(RecordError):
        parse_mark(raw)


def test_clean_student_id_normalises_case_and_spaces():
    assert clean_student_id("  s001 ") == "S001"
    with pytest.raises(RecordError):
        clean_student_id("S 001; DROP")
    with pytest.raises(RecordError, match="missing"):
        clean_student_id("   ")


# --- marks records -------------------------------------------------------

def test_invalid_rows_are_rejected_with_file_and_row_number():
    processor = DataProcessor()
    processor.add_marks_records(
        [
            (2, marks_row("S1", a1="70")),
            (3, marks_row("S2", a1="150")),        # out of range
            (4, marks_row("S3", name="", a1="60")),  # missing name
            (5, {**marks_row("S4", a1="50"), None: ["extra"]}),  # extra col
        ],
        "term1.csv",
    )
    assert list(processor.students) == ["S1"]
    rejected = [(r.source, r.row) for r in processor.invalid_records]
    assert rejected == [("term1.csv", 3), ("term1.csv", 4), ("term1.csv", 5)]
    assert processor.stats["rows_rejected"] == 3


def test_marks_from_several_files_are_merged_by_student_id():
    processor = DataProcessor()
    processor.add_marks_records([(2, marks_row(a1="70"))], "term1.csv")
    processor.add_marks_records([(2, marks_row(" s1", exam="90"))],
                                "term2.csv")
    student = processor.students["S1"]
    assert student.marks == {"a1": 70.0, "exam": 90.0}
    assert student.average_mark() == 80.0


def test_duplicate_mark_and_conflicting_identity_are_rejected():
    processor = DataProcessor()
    processor.add_marks_records(
        [
            (2, marks_row(a1="70")),
            (3, marks_row(a1="99")),               # same assessment again
            (4, marks_row(name="Other", a2="50")),  # same ID, other name
        ],
        "m.csv",
    )
    assert processor.students["S1"].marks == {"a1": 70.0}
    reasons = [r.reason for r in processor.invalid_records]
    assert "duplicate mark" in reasons[0]
    assert "conflicts" in reasons[1]


def test_rejected_row_does_not_partially_update_student():
    processor = DataProcessor()
    processor.add_marks_records([(2, marks_row(a1="70"))], "m.csv")
    processor.add_marks_records([(2, marks_row(a2="80", a3="bad"))], "n.csv")
    assert processor.students["S1"].marks == {"a1": 70.0}


# --- attendance and merge -----------------------------------------------

def test_attendance_validation_and_left_join():
    processor = DataProcessor()
    processor.add_marks_records(
        [(2, marks_row("S1", a1="70")), (3, marks_row("S2", a1="60"))],
        "m.csv",
    )
    processor.add_attendance_records(
        [
            (1, {"student_id": "S1", "sessions_attended": 9,
                 "sessions_total": 12}),
            (2, {"student_id": "S1", "sessions_attended": 1,
                 "sessions_total": 12}),                       # duplicate
            (3, {"student_id": "S2", "sessions_attended": 13,
                 "sessions_total": 12}),                       # impossible
            (4, {"student_id": "S9", "sessions_attended": 5,
                 "sessions_total": 12}),                       # orphan
            (5, "not a record"),
        ],
        "att.json",
    )
    students = processor.merge("left")
    assert [s.student_id for s in students] == ["S1", "S2"]
    assert students[0].attendance_percentage() == 75.0
    assert students[1].attendance_percentage() is None
    assert [r.row for r in processor.invalid_records] == [2, 3, 5]
    assert processor.stats["attendance_orphans"] == 1


def test_inner_join_drops_students_without_attendance():
    processor = DataProcessor()
    processor.add_marks_records(
        [(2, marks_row("S1", a1="70")), (3, marks_row("S2", a1="60"))],
        "m.csv",
    )
    processor.add_attendance_records(
        [(1, {"student_id": "S2", "sessions_attended": "10",
              "sessions_total": "12"})],
        "att.csv",
    )
    assert [s.student_id for s in processor.merge("inner")] == ["S2"]


def test_merge_rejects_unknown_join_type():
    with pytest.raises(ValueError):
        DataProcessor().merge("outer")


# --- filtering and aggregation ------------------------------------------

def test_filters_combine_and_are_case_insensitive(students):
    ids = [s.student_id for s in apply_filters(students, {"course": "mit703"})]
    assert ids == ["S1", "S2"]
    ids = [s.student_id for s in apply_filters(students, {"min_average": 60})]
    assert ids == ["S1", "S3"]  # S4 has no marks so cannot meet the filter
    ids = [s.student_id
           for s in apply_filters(students, {"at_risk_only": True})]
    assert ids == ["S2", "S3", "S4"]
    assert apply_filters(students, {"course": ["MIT702"],
                                    "min_attendance": 60}) == []


def test_group_summary_by_course(students):
    summary = group_summary(students, "course")
    assert [row["course"] for row in summary] == ["MIT702", "MIT703"]
    mit703 = summary[1]
    assert mit703["students"] == 2
    assert mit703["mean_average_mark"] == 65.0   # (85 + 45) / 2
    assert mit703["highest_average"] == 85.0
    assert mit703["mean_attendance_pct"] == 87.5
    assert mit703["at_risk"] == 1


def test_group_summary_by_grade_and_empty_input(students):
    grades = {row["grade"]: row["students"]
              for row in group_summary(students, "grade")}
    assert grades == {"DI": 1, "HD": 1, "NN": 1, "N/A": 1}
    assert group_summary([], "course") == []
    with pytest.raises(ValueError):
        group_summary(students, "name")
