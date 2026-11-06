"""Shared pytest fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from student_tool.models import Student

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = PROJECT_ROOT / "sample_data"


@pytest.fixture
def sample_dir() -> Path:
    """Folder holding the synthetic sample input files."""
    return SAMPLE_DIR


@pytest.fixture
def write_file(tmp_path: Path):
    """Return a helper that writes text to a file in a temp folder."""
    def _write(name: str, content: str) -> Path:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path
    return _write


@pytest.fixture
def write_json(tmp_path: Path):
    """Return a helper that writes a Python object as a JSON file."""
    def _write(name: str, data: object) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path
    return _write


@pytest.fixture
def students() -> list[Student]:
    """A small, known set of students for filter and summary tests."""
    a = Student("S1", "Ann", "MIT703", {"a1": 90, "a2": 80})
    a.set_attendance(12, 12)
    b = Student("S2", "Ben", "MIT703", {"a1": 40, "a2": 50})
    b.set_attendance(9, 12)
    c = Student("S3", "Cat", "MIT702", {"a1": 70})
    c.set_attendance(6, 12)
    d = Student("S4", "Dan", "MIT702")
    return [a, b, c, d]
