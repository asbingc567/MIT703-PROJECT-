"""Tests for the Student class."""

import pytest

from student_tool.models import Student


def test_total_and_average_are_calculated():
    student = Student("S1", "Ann", "MIT703", {"a1": 70, "a2": 85.5})
    assert student.total_marks() == 155.5
    assert student.average_mark() == 77.75


def test_student_with_no_marks_has_no_average_and_is_at_risk():
    student = Student("S1", "Ann", "MIT703")
    assert student.total_marks() == 0
    assert student.average_mark() is None
    assert student.grade() == "N/A"
    assert student.is_at_risk() is True


@pytest.mark.parametrize(
    ("average", "expected"),
    [(80, "HD"), (79.99, "DI"), (70, "DI"), (60, "CR"),
     (50, "PA"), (49.99, "NN"), (0, "NN")],
)
def test_grade_boundaries(average, expected):
    student = Student("S1", "Ann", "MIT703", {"a1": average})
    assert student.grade() == expected


def test_attendance_percentage_and_unknown_attendance():
    student = Student("S1", "Ann", "MIT703", {"a1": 90})
    assert student.attendance_percentage() is None
    assert student.is_at_risk() is False  # unknown attendance alone is fine
    student.set_attendance(9, 12)
    assert student.attendance_percentage() == 75.0
    assert student.is_at_risk() is True  # 75% < 80%


@pytest.mark.parametrize(("attended", "total"), [(13, 12), (-1, 12), (0, 0)])
def test_set_attendance_rejects_impossible_values(attended, total):
    student = Student("S1", "Ann", "MIT703")
    with pytest.raises(ValueError):
        student.set_attendance(attended, total)


def test_add_mark_keeps_first_value_on_duplicate():
    student = Student("S1", "Ann", "MIT703")
    assert student.add_mark("exam", 60) is True
    assert student.add_mark("exam", 95) is False
    assert student.marks == {"exam": 60}


def test_to_dict_can_exclude_name():
    student = Student("S1", "Ann", "MIT703", {"a1": 60})
    assert "name" in student.to_dict()
    record = student.to_dict(include_name=False)
    assert "name" not in record
    assert record["average_mark"] == 60
    assert record["grade"] == "CR"
