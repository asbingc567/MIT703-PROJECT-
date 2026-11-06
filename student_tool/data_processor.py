"""Validate, clean, merge, filter and aggregate student records."""

from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from typing import Any

from student_tool.models import InvalidRecord, Student

logger = logging.getLogger(__name__)

IDENTITY_FIELDS = ("student_id", "name", "course")
ATTENDANCE_FIELDS = ("student_id", "sessions_attended", "sessions_total")
STUDENT_ID_PATTERN = re.compile(r"^[A-Z0-9_-]{2,20}$")
ASSESSMENT_PATTERN = re.compile(r"^[a-z0-9_]{1,40}$")


class RecordError(ValueError):
    """Raised internally when a single record fails validation."""


def clean_text(value: Any) -> str:
    """Return ``value`` as text with extra whitespace collapsed."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def clean_student_id(value: Any) -> str:
    """Normalise and validate a student ID.

    IDs are upper-cased and stripped so that ``" s001"`` and ``"S001"``
    refer to the same student.

    Raises:
        RecordError: If the ID is empty or contains invalid characters.
    """
    student_id = clean_text(value).upper()
    if not student_id:
        raise RecordError("missing student_id")
    if not STUDENT_ID_PATTERN.match(student_id):
        raise RecordError(f"invalid student_id {student_id!r}")
    return student_id


def parse_mark(value: Any) -> float | None:
    """Convert a raw mark to a float between 0 and 100.

    Blank values are treated as "not yet submitted" and return ``None``
    rather than zero, so they do not drag the average down.

    Raises:
        RecordError: If the value is not a number or is out of range.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise RecordError(f"mark {value!r} is not a number")
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    try:
        mark = float(value)
    except (TypeError, ValueError) as exc:
        raise RecordError(f"mark {value!r} is not a number") from exc
    if math.isnan(mark) or math.isinf(mark):
        raise RecordError(f"mark {value!r} is not a finite number")
    if not 0 <= mark <= 100:
        raise RecordError(f"mark {mark:g} is outside 0-100")
    return round(mark, 2)


def parse_count(value: Any, field_name: str) -> int:
    """Convert a raw attendance count to a non-negative whole number.

    Raises:
        RecordError: If the value is missing, fractional or negative.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise RecordError(f"missing {field_name}")
    if isinstance(value, bool):
        raise RecordError(f"{field_name} {value!r} is not a whole number")
    try:
        number = float(str(value).strip())
    except ValueError as exc:
        raise RecordError(
            f"{field_name} {value!r} is not a whole number"
        ) from exc
    if not number.is_integer() or number < 0:
        raise RecordError(
            f"{field_name} {value!r} must be a whole number >= 0"
        )
    return int(number)


class DataProcessor:
    """Collect records from many files and merge them into ``Student`` objects.

    Typical use::

        processor = DataProcessor()
        processor.add_marks_records(records, "term1.csv")
        processor.add_attendance_records(records, "attendance.json")
        students = processor.merge(join="left")

    Attributes:
        students: Student ID mapped to ``Student`` (O(1) lookup for merging).
        invalid_records: Every rejected row and why it was rejected.
        stats: Counts of rows read, accepted and rejected.
    """

    def __init__(self) -> None:
        """Create an empty processor."""
        self.students: dict[str, Student] = {}
        self.invalid_records: list[InvalidRecord] = []
        self.stats: Counter[str] = Counter()
        self._attendance: dict[str, tuple[int, int]] = {}

    def _reject(self, source: str, row: int, reason: str) -> None:
        """Record an invalid row and log it without personal details."""
        self.invalid_records.append(InvalidRecord(source, row, reason))
        self.stats["rows_rejected"] += 1
        logger.warning("Rejected %s row %d: %s", source, row, reason)

    def add_marks_records(
        self, records: list[tuple[int, Any]], source: str
    ) -> None:
        """Validate and add student marks records from one file.

        Each record must contain ``student_id``, ``name`` and ``course``.
        Every other field is treated as an assessment mark.
        """
        for row_number, record in records:
            self.stats["marks_rows_read"] += 1
            try:
                self._add_marks_record(record)
            except RecordError as exc:
                self._reject(source, row_number, str(exc))
            else:
                self.stats["marks_rows_accepted"] += 1

    def _add_marks_record(self, record: Any) -> None:
        """Validate one marks record and merge it into ``self.students``."""
        if not isinstance(record, dict):
            raise RecordError("record is not an object")
        if None in record:
            # csv.DictReader puts surplus values under the key None.
            raise RecordError("row has more values than header columns")

        student_id = clean_student_id(record.get("student_id"))
        name = clean_text(record.get("name"))
        course = clean_text(record.get("course")).upper()
        if not name:
            raise RecordError("missing name")
        if not course:
            raise RecordError("missing course")

        # Validate every mark before changing any state, so a bad row
        # is rejected as a whole rather than half-applied.
        marks: dict[str, float] = {}
        for key, raw_value in record.items():
            if key in IDENTITY_FIELDS:
                continue
            assessment = clean_text(key).lower().replace(" ", "_")
            if not ASSESSMENT_PATTERN.match(assessment):
                raise RecordError(f"invalid assessment name {key!r}")
            mark = parse_mark(raw_value)
            if mark is not None:
                marks[assessment] = mark

        existing = self.students.get(student_id)
        if existing is None:
            student = Student(student_id, name, course)
            self.students[student_id] = student
        else:
            if (existing.name, existing.course) != (name, course):
                raise RecordError(
                    f"{student_id} conflicts with an earlier record "
                    "(different name or course)"
                )
            student = existing

        duplicates = [a for a in marks if a in student.marks]
        if duplicates:
            raise RecordError(
                f"duplicate mark(s) for {student_id}: {', '.join(duplicates)}"
            )
        for assessment, mark in marks.items():
            student.add_mark(assessment, mark)

    def add_attendance_records(
        self, records: list[tuple[int, Any]], source: str
    ) -> None:
        """Validate and store attendance records from one file.

        Attendance is held separately until ``merge`` is called, so marks
        and attendance files can be supplied in any order.
        """
        for row_number, record in records:
            self.stats["attendance_rows_read"] += 1
            try:
                student_id, counts = self._parse_attendance(record)
            except RecordError as exc:
                self._reject(source, row_number, str(exc))
                continue
            if student_id in self._attendance:
                self._reject(
                    source, row_number,
                    f"duplicate attendance record for {student_id}",
                )
                continue
            self._attendance[student_id] = counts
            self.stats["attendance_rows_accepted"] += 1

    @staticmethod
    def _parse_attendance(record: Any) -> tuple[str, tuple[int, int]]:
        """Validate one attendance record.

        Returns:
            ``(student_id, (attended, total))``.
        """
        if not isinstance(record, dict):
            raise RecordError("record is not an object")
        student_id = clean_student_id(record.get("student_id"))
        attended = parse_count(
            record.get("sessions_attended"), "sessions_attended"
        )
        total = parse_count(record.get("sessions_total"), "sessions_total")
        if total == 0:
            raise RecordError("sessions_total must be greater than zero")
        if attended > total:
            raise RecordError(
                f"sessions_attended ({attended}) exceeds "
                f"sessions_total ({total})"
            )
        return student_id, (attended, total)

    def merge(self, join: str = "left") -> list[Student]:
        """Attach attendance to students and return them sorted by ID.

        Args:
            join: ``"left"`` keeps students with no attendance record;
                ``"inner"`` keeps only students present in both sources.

        Returns:
            A new list of ``Student`` objects sorted by ``student_id``.

        Raises:
            ValueError: If ``join`` is not ``"left"`` or ``"inner"``.
        """
        if join not in ("left", "inner"):
            raise ValueError(f"join must be 'left' or 'inner', got {join!r}")

        orphans = sorted(set(self._attendance) - set(self.students))
        for student_id in orphans:
            logger.warning(
                "Attendance for %s ignored: no matching marks record",
                student_id,
            )
        self.stats["attendance_orphans"] = len(orphans)

        merged: list[Student] = []
        for student_id in sorted(self.students):
            student = self.students[student_id]
            counts = self._attendance.get(student_id)
            if counts is not None:
                student.set_attendance(*counts)
            elif join == "inner":
                logger.info("Dropping %s: no attendance record", student_id)
                continue
            else:
                self.stats["students_without_attendance"] += 1
            merged.append(student)
        self.stats["students_merged"] = len(merged)
        return merged


def apply_filters(
    students: list[Student],
    filters: dict[str, Any],
    pass_mark: float = 50.0,
    min_attendance_pct: float = 80.0,
) -> list[Student]:
    """Return the students that match every filter.

    Supported filters: ``course`` (string or list), ``min_average``,
    ``max_average``, ``min_attendance`` and ``at_risk_only``. Students
    with no average or no attendance are excluded by the matching
    numeric filters, since they cannot be shown to meet them.
    """
    result = list(students)
    if "course" in filters:
        wanted = filters["course"]
        courses = {
            c.strip().upper()
            for c in (wanted if isinstance(wanted, list) else [wanted])
        }
        result = [s for s in result if s.course in courses]
    if "min_average" in filters:
        result = [
            s for s in result
            if s.average_mark() is not None
            and s.average_mark() >= filters["min_average"]
        ]
    if "max_average" in filters:
        result = [
            s for s in result
            if s.average_mark() is not None
            and s.average_mark() <= filters["max_average"]
        ]
    if "min_attendance" in filters:
        result = [
            s for s in result
            if s.attendance_percentage() is not None
            and s.attendance_percentage() >= filters["min_attendance"]
        ]
    if filters.get("at_risk_only"):
        result = [
            s for s in result if s.is_at_risk(pass_mark, min_attendance_pct)
        ]
    logger.info("%d of %d student(s) match the filters",
                len(result), len(students))
    return result


def _mean(values: list[float]) -> float | None:
    """Return the rounded mean of ``values``, or ``None`` if empty."""
    return round(sum(values) / len(values), 2) if values else None


def group_summary(
    students: list[Student],
    group_by: str = "course",
    pass_mark: float = 50.0,
    min_attendance_pct: float = 80.0,
) -> list[dict[str, Any]]:
    """Aggregate students into one summary row per group.

    Args:
        students: Students to summarise.
        group_by: ``"course"`` or ``"grade"``.

    Returns:
        A list of dictionaries sorted by group name, each with the
        student count, mean/highest/lowest average mark, mean attendance
        and number of at-risk students.

    Raises:
        ValueError: If ``group_by`` is not supported.
    """
    if group_by == "course":
        def key_of(student: Student) -> str:
            return student.course
    elif group_by == "grade":
        def key_of(student: Student) -> str:
            return student.grade()
    else:
        raise ValueError(f"Cannot group by {group_by!r}")

    groups: defaultdict[str, list[Student]] = defaultdict(list)
    for student in students:
        groups[key_of(student)].append(student)

    summary: list[dict[str, Any]] = []
    for group_name in sorted(groups):
        members = groups[group_name]
        averages = [
            s.average_mark() for s in members if s.average_mark() is not None
        ]
        attendance = [
            s.attendance_percentage() for s in members
            if s.attendance_percentage() is not None
        ]
        summary.append({
            group_by: group_name,
            "students": len(members),
            "mean_average_mark": _mean(averages),
            "highest_average": max(averages) if averages else None,
            "lowest_average": min(averages) if averages else None,
            "mean_attendance_pct": _mean(attendance),
            "at_risk": sum(
                s.is_at_risk(pass_mark, min_attendance_pct) for s in members
            ),
        })
    return summary
