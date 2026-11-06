"""Tests for reading CSV and JSON input files."""

import pytest

from student_tool.data_loader import DataLoadError, load_records


def test_csv_rows_are_numbered_from_line_two(write_file):
    path = write_file("m.csv", "student_id,name,course,a1\nS1,Ann,MIT703,70\n"
                               "S2,Ben,MIT703,80\n")
    records = load_records(path, ("student_id", "name", "course"))
    assert [row for row, _ in records] == [2, 3]
    assert records[0][1]["a1"] == "70"


def test_csv_with_excel_bom_and_spaced_header_is_read(write_file):
    path = write_file("m.csv", "﻿student_id , name,course\nS1,Ann,X\n")
    records = load_records(path, ("student_id", "name", "course"))
    assert records[0][1]["student_id"] == "S1"


def test_json_list_and_records_wrapper_are_accepted(write_json):
    plain = write_json("a.json", [{"student_id": "S1"}])
    wrapped = write_json("b.json", {"records": [{"student_id": "S1"}]})
    assert load_records(plain) == load_records(wrapped) == [
        (1, {"student_id": "S1"})
    ]


def test_missing_file_raises_data_load_error(tmp_path):
    with pytest.raises(DataLoadError, match="File not found"):
        load_records(tmp_path / "nope.csv")


def test_missing_required_column_raises(write_file):
    path = write_file("m.csv", "student_id,course\nS1,MIT703\n")
    with pytest.raises(DataLoadError, match="missing required column"):
        load_records(path, ("student_id", "name", "course"))


def test_invalid_json_reports_line_number(write_file):
    path = write_file("a.json", '[\n {"student_id": "S1",}\n]')
    with pytest.raises(DataLoadError, match="line 2"):
        load_records(path)


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("data.txt", "hello", "unsupported file type"),
        ("empty.csv", "", "empty"),
        ("obj.json", '{"student_id": "S1"}', "expected a JSON list"),
        ("dup.csv", "student_id,name,name\nS1,A,B\n", "duplicate column"),
    ],
)
def test_bad_files_raise_clear_errors(write_file, name, content, message):
    path = write_file(name, content)
    with pytest.raises(DataLoadError, match=message):
        load_records(path)


def test_non_utf8_file_raises(tmp_path):
    path = tmp_path / "latin1.csv"
    path.write_bytes("student_id,name\nS1,Jos\xe9\n".encode("latin-1"))
    with pytest.raises(DataLoadError, match="not UTF-8"):
        load_records(path)
