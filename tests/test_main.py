"""End-to-end tests of the command-line workflow."""

import json

import pytest

from student_tool.main import main


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Stop a developer's local .env or shell settings affecting tests."""
    monkeypatch.delenv("STP_OUTPUT_DIR", raising=False)
    monkeypatch.delenv("STP_LOG_LEVEL", raising=False)
    monkeypatch.setattr("student_tool.config.load_dotenv",
                        lambda **kwargs: False)


def test_full_run_on_sample_data(sample_dir, tmp_path, capsys):
    out = tmp_path / "out"
    code = main([
        "--marks", str(sample_dir / "term1_marks.csv"),
        str(sample_dir / "term2_marks.csv"),
        "--attendance", str(sample_dir / "attendance.json"),
        "--output-dir", str(out),
    ])
    assert code == 0
    for name in ("students_clean.csv", "students_merged.json",
                 "summary_by_course.csv", "summary.txt",
                 "invalid_records.csv", "logs/run.log"):
        assert (out / name).exists(), name

    data = json.loads((out / "students_merged.json").read_text("utf-8"))
    by_id = {s["student_id"]: s for s in data["students"]}
    assert sorted(by_id) == ["S001", "S002", "S003", "S004", "S005",
                             "S010", "S011"]
    assert by_id["S003"]["name"] == "Liam O'Brien"   # cleaned spacing/case
    assert by_id["S001"]["average_mark"] == 81.33     # (78 + 85 + 81) / 3
    assert by_id["S005"]["marks"] == {"assignment1": 38.0, "exam": 49.0}
    assert by_id["S011"]["attendance_pct"] is None    # its row was invalid
    assert "STUDENT PERFORMANCE SUMMARY" in capsys.readouterr().out


def test_filters_and_formats_from_command_line(sample_dir, tmp_path):
    out = tmp_path / "out"
    code = main([
        "--marks", str(sample_dir / "term1_marks.csv"),
        "--course", "mit702", "--format", "json",
        "--exclude-names", "--output-dir", str(out),
    ])
    assert code == 0
    assert not (out / "students_clean.csv").exists()
    data = json.loads((out / "students_merged.json").read_text("utf-8"))
    assert {s["course"] for s in data["students"]} == {"MIT702"}
    assert all("name" not in s for s in data["students"])


def test_missing_input_file_returns_error_code(tmp_path, caplog):
    code = main(["--marks", str(tmp_path / "missing.csv"),
                 "--output-dir", str(tmp_path / "out")])
    assert code == 1
    assert "File not found" in caplog.text


def test_invalid_config_returns_error_code(sample_dir, tmp_path, caplog):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"filters": {"min_average": "high"}}))
    code = main(["--marks", str(sample_dir / "term1_marks.csv"),
                 "--config", str(config)])
    assert code == 1
    assert "must be a number" in caplog.text


def test_file_with_no_valid_rows_returns_error_code(tmp_path, caplog):
    bad = tmp_path / "bad.csv"
    bad.write_text("student_id,name,course,a1\n,Ann,MIT703,70\n")
    code = main(["--marks", str(bad), "--output-dir", str(tmp_path / "o")])
    assert code == 1
    assert "No valid student records" in caplog.text


def test_missing_required_argument_exits_with_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
