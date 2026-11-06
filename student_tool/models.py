"""Data model classes for the Student Performance Data Transformation Tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Grade boundaries as (minimum average, grade), checked from highest down.
GRADE_BANDS: tuple[tuple[float, str], ...] = (
    (80.0, "HD"),
    (70.0, "DI"),
    (60.0, "CR"),
    (50.0, "PA"),
    (0.0, "NN"),
)


@dataclass
class Student:
    """One student's merged marks and attendance.

    Attributes:
        student_id: Normalised, unique student identifier (e.g. ``"S001"``).
        name: Student's display name.
        course: Normalised course code (e.g. ``"MIT703"``).
        marks: Assessment name mapped to a mark from 0 to 100.
        sessions_attended: Number of classes attended, if known.
        sessions_total: Number of classes held, if known.
    """

    student_id: str
    name: str
    course: str
    marks: dict[str, float] = field(default_factory=dict)
    sessions_attended: int | None = None
    sessions_total: int | None = None

    def add_mark(self, assessment: str, mark: float) -> bool:
        """Record a mark for an assessment.

        Args:
            assessment: Assessment name, e.g. ``"exam"``.
            mark: Mark between 0 and 100.

        Returns:
            ``True`` if the mark was added, or ``False`` if this student
            already has a mark for that assessment (the first is kept).
        """
        if assessment in self.marks:
            return False
        self.marks[assessment] = mark
        return True

    def set_attendance(self, attended: int, total: int) -> None:
        """Store attendance figures for the student.

        Raises:
            ValueError: If the figures are negative, total is zero, or
                attended exceeds total.
        """
        if total <= 0:
            raise ValueError("sessions_total must be greater than zero")
        if not 0 <= attended <= total:
            raise ValueError(
                "sessions_attended must be between 0 and sessions_total"
            )
        self.sessions_attended = attended
        self.sessions_total = total

    def total_marks(self) -> float:
        """Return the sum of all recorded marks (0 if there are none)."""
        return round(sum(self.marks.values()), 2)

    def average_mark(self) -> float | None:
        """Return the mean mark, or ``None`` if no marks are recorded."""
        if not self.marks:
            return None
        return round(sum(self.marks.values()) / len(self.marks), 2)

    def attendance_percentage(self) -> float | None:
        """Return attendance as a percentage, or ``None`` if unknown."""
        if self.sessions_total is None or self.sessions_attended is None:
            return None
        return round(self.sessions_attended / self.sessions_total * 100, 2)

    def grade(self) -> str:
        """Return the grade band for the average mark, or ``"N/A"``."""
        average = self.average_mark()
        if average is None:
            return "N/A"
        for minimum, grade in GRADE_BANDS:
            if average >= minimum:
                return grade
        return "NN"

    def is_at_risk(
        self, pass_mark: float = 50.0, min_attendance_pct: float = 80.0
    ) -> bool:
        """Return ``True`` if the student is failing or attending too little.

        A student with no marks is treated as at risk, because there is
        no evidence they are passing. Unknown attendance alone does not
        make a student at risk.
        """
        average = self.average_mark()
        if average is None or average < pass_mark:
            return True
        attendance = self.attendance_percentage()
        return attendance is not None and attendance < min_attendance_pct

    def to_dict(
        self,
        include_name: bool = True,
        pass_mark: float = 50.0,
        min_attendance_pct: float = 80.0,
    ) -> dict[str, Any]:
        """Return a flat dictionary of raw and calculated fields for output.

        Args:
            include_name: Set to ``False`` to leave the name out (privacy).
            pass_mark: Threshold passed to ``is_at_risk``.
            min_attendance_pct: Threshold passed to ``is_at_risk``.
        """
        record: dict[str, Any] = {"student_id": self.student_id}
        if include_name:
            record["name"] = self.name
        record["course"] = self.course
        record["marks"] = dict(sorted(self.marks.items()))
        record["total_marks"] = self.total_marks()
        record["average_mark"] = self.average_mark()
        record["grade"] = self.grade()
        record["sessions_attended"] = self.sessions_attended
        record["sessions_total"] = self.sessions_total
        record["attendance_pct"] = self.attendance_percentage()
        record["at_risk"] = self.is_at_risk(pass_mark, min_attendance_pct)
        return record


@dataclass(frozen=True)
class InvalidRecord:
    """A row that was rejected, with enough detail to find and fix it.

    Attributes:
        source: File name the row came from.
        row: Row number in the file (CSV header is row 1; JSON items
            are numbered from 1).
        reason: Human-readable explanation of why the row was rejected.
    """

    source: str
    row: int
    reason: str
