# Student Performance Data Transformation Tool

MIT703 Programming with Python, Assessment 2 (Option C: CSV/JSON Data Transformation Tool)

A command-line tool for teachers, tutors and administrators. It loads student
marks and attendance from **multiple CSV and JSON files** and then:

- **validates and cleans** every record (IDs, names, course codes, marks 0–100, attendance counts)
- **merges** the records by student ID across files, for example Term 1 and Term 2 marks plus attendance
- **calculates** total marks, average mark, grade band, attendance % and an at-risk flag
- **filters** the results by course, average, attendance or at-risk status
- **aggregates** the results by course or grade
- writes **CSV, JSON and plain-text reports**, plus a list of every rejected row with its file name, row number and reason

It uses only the Python standard library at runtime, plus `python-dotenv` for optional local settings.

---

## Project structure

```
MIT703_Project_SE20262806/
├── student_tool/              # application package
│   ├── __init__.py            # package docstring and version
│   ├── __main__.py            # allows `python -m student_tool`
│   ├── main.py                # CLI argument parsing and workflow
│   ├── config.py              # settings from defaults, .env and JSON config
│   ├── data_loader.py         # reads CSV/JSON files; file-level errors
│   ├── models.py              # Student and InvalidRecord classes
│   ├── data_processor.py      # validate, clean, merge, filter, aggregate
│   └── report_generator.py    # CSV/JSON/text output, CSV-injection safe
├── tests/                     # pytest suite (63 tests)
├── sample_data/               # SYNTHETIC data only (includes bad rows on purpose)
├── config.example.json        # example configuration file
├── .env.example               # example environment settings
├── requirements.txt           # pinned dependencies
├── pytest.ini
└── .gitignore
```

## Requirements

- Python **3.10 or later**
- The packages in `requirements.txt`: `python-dotenv==1.0.1` and `pytest==8.3.3`

## Installation

```bash
git clone <your-repo-url>
cd MIT703_Project_SE20262806

python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

pip install -r requirements.txt

# Optional: local settings
cp .env.example .env          # Windows: copy .env.example .env
```

## Input formats

**Marks files** (CSV or JSON, one or more). Each file needs `student_id`, `name` and `course`.
**Every other column is treated as an assessment mark** (0–100). A blank mark means "not submitted" and is left out of the average rather than counted as zero.

```csv
student_id,name,course,assignment1,assignment2
S001,Alex Chen,MIT703,78,85
```

**Attendance files** (JSON or CSV, optional):

```json
[{"student_id": "S001", "sessions_attended": 11, "sessions_total": 12}]
```

A JSON file can be a plain list of records or an object of the form `{"records": [...]}`.

### Validation and cleaning rules

| Rule | Behaviour |
|---|---|
| Student ID | trimmed and upper-cased (` s003 ` → `S003`); must match `A–Z 0–9 _ -`, 2–20 characters |
| Name / course | extra whitespace collapsed; course upper-cased; must not be empty |
| Marks | numeric and within 0–100; blank values are treated as missing |
| Attendance | whole numbers; `sessions_total > 0`; `attended ≤ total` |
| Too many values in a CSV row | row rejected |
| Same student in another file | marks merged; rejected if the name or course conflicts |
| Same assessment twice for a student | duplicate rejected and the first value kept |
| Attendance with no matching student | ignored and logged |

Rejected rows never stop the run. They are written to `invalid_records.csv`.
File-level problems (missing file, invalid JSON, missing columns, non-UTF-8 text) stop the run with a clear message and exit code 1.

## Usage

```bash
python -m student_tool --marks FILE [FILE ...] [--attendance FILE [FILE ...]] [options]
```

| Option | Meaning |
|---|---|
| `--config FILE` | JSON config file (see `config.example.json`) |
| `--output-dir DIR` | where reports go (default `output/`) |
| `--group-by {course,grade}` | summary grouping |
| `--format {csv,json,text} ...` | which reports to write |
| `--join {left,inner}` | `left` keeps students with no attendance; `inner` drops them |
| `--course CODE` | only include one course |
| `--min-average N` | only include students with an average of at least N |
| `--at-risk-only` | only include at-risk students |
| `--exclude-names` | leave names out of every output (privacy) |
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | logging detail |

Settings are applied in this order of priority: **command line > config file > environment / `.env` > defaults**.

### Examples

```bash
# Everything, using the sample data
python -m student_tool \
  --marks sample_data/term1_marks.csv sample_data/term2_marks.csv \
  --attendance sample_data/attendance.json

# MIT703 students at risk, JSON only, with names removed
python -m student_tool --marks sample_data/term1_marks.csv sample_data/term2_marks.csv \
  --attendance sample_data/attendance.json \
  --course MIT703 --at-risk-only --format json --exclude-names

# Group by grade band using a config file
python -m student_tool --marks sample_data/*.csv --config config.example.json --group-by grade
```

### Configuration file

```json
{
  "output_dir": "output",
  "group_by": "course",
  "output_formats": ["csv", "json", "text"],
  "join": "left",
  "include_names": true,
  "pass_mark": 50,
  "min_attendance_pct": 80,
  "filters": {"course": ["MIT703"], "min_average": 50, "min_attendance": 75, "at_risk_only": false}
}
```

Unknown keys and invalid values are rejected with a clear error message.

## Sample output

Console output (also written to `output/summary.txt`) from the first example above:

```
STUDENT PERFORMANCE SUMMARY
============================================================
Generated: 2026-11-07 01:13

Input
  Marks rows read / accepted:      17 / 12
  Attendance rows read / accepted: 10 / 7
  Rows rejected (see invalid_records.csv): 8
  Students merged: 7
  Filters: none
  Students in report: 7

Summary by course
  COURSE        N     MEAN     HIGH      LOW     ATT%  RISK
  ---------------------------------------------------------
  MIT702        3    57.39    70.67    43.50    86.11     1
  MIT703        4    76.67    91.67    45.67    83.33     1

At-risk students (average < 50 or attendance < 80%): 2
  S003, S005
```

`output/invalid_records.csv`:

```
source,row,reason
term1_marks.csv,7,mark 105 is outside 0-100
term1_marks.csv,8,missing name
term1_marks.csv,9,mark 'abc' is not a number
term1_marks.csv,10,row has more values than header columns
term1_marks.csv,11,"duplicate mark(s) for S002: assignment1, assignment2"
attendance.json,7,sessions_attended (14) exceeds sessions_total (12)
attendance.json,9,duplicate attendance record for S001
attendance.json,10,record is not an object
```

`output/students_clean.csv` (first rows):

```
student_id,name,course,assignment1,assignment2,exam,total_marks,average_mark,grade,sessions_attended,sessions_total,attendance_pct,at_risk
S001,Alex Chen,MIT703,78.0,85.0,81.0,244.0,81.33,HD,11,12,91.67,False
S005,Noah Williams,MIT702,38.0,,49.0,87.0,43.5,NN,9,12,75.0,True
S010,"'=HYPERLINK(""http://example.com"")",MIT702,,,58.0,58.0,58.0,PA,12,12,100.0,False
```

Note that S010's name has been prefixed with `'`, so Excel shows it as text instead of running it as a formula.

Other files written: `students_merged.json`, `summary_by_course.csv` and `logs/run.log`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | configuration error, unreadable input, no valid records, or reports could not be written |
| 2 | invalid command-line arguments |

## Running the tests

```bash
pytest            # 63 tests
pytest -v         # list every test
```

The tests cover normal cases, edge cases (grade boundaries, blank marks, Excel BOM, empty files, inner and left joins) and error conditions (missing files, invalid JSON, out-of-range values, bad config, CSV injection).

## Privacy and security

- `sample_data/` is **entirely synthetic**. Never commit real student data. A `data/` folder for real files is git-ignored.
- `.env`, `output/` and `*.log` are git-ignored. The tool needs **no credentials**.
- Logs and the text summary identify students **by ID only**, never by name.
- `--exclude-names` removes names from every output file.
- CSV cells starting with `= + - @` are neutralised to prevent formula injection.
- Input files over 50 MB are refused, and every record is validated before use.

## Third-party libraries

| Library | Version | Licence | Use |
|---|---|---|---|
| python-dotenv | 1.0.1 | BSD-3-Clause | loads optional local `.env` settings |
| pytest | 8.3.3 | MIT | test framework |

Everything else (`csv`, `json`, `argparse`, `logging`, `pathlib`, `dataclasses`, `collections`, `re`) is from the Python standard library.

## Author

Asbin GC (SE20262806), MIT703 Programming with Python
