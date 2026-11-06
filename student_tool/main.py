"""Command-line entry point: parse arguments and run the workflow.

Data flow::

    input CSV/JSON files -> load -> validate & clean -> merge by student ID
    -> filter -> group & calculate -> CSV / JSON / text reports
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from student_tool import __version__
from student_tool.config import (
    VALID_FORMATS,
    VALID_GROUP_KEYS,
    VALID_JOINS,
    ConfigError,
    Settings,
    load_settings,
)
from student_tool.data_loader import DataLoadError, load_records
from student_tool.data_processor import (
    IDENTITY_FIELDS,
    DataProcessor,
    apply_filters,
    group_summary,
)
from student_tool.report_generator import (
    ReportError,
    ReportGenerator,
    build_text_summary,
)

logger = logging.getLogger("student_tool")

EXIT_OK = 0
EXIT_ERROR = 1


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="student_tool",
        description=(
            "Merge student marks and attendance from CSV/JSON files and "
            "produce cleaned data and summary reports."
        ),
    )
    parser.add_argument(
        "--marks", nargs="+", type=Path, required=True, metavar="FILE",
        help="one or more CSV/JSON files with student_id, name, course "
             "and one column per assessment",
    )
    parser.add_argument(
        "--attendance", nargs="+", type=Path, default=[], metavar="FILE",
        help="zero or more CSV/JSON files with student_id, "
             "sessions_attended and sessions_total",
    )
    parser.add_argument("--config", type=Path, help="JSON configuration file")
    parser.add_argument("--output-dir", type=Path,
                        help="folder for reports (default: output)")
    parser.add_argument("--group-by", choices=VALID_GROUP_KEYS)
    parser.add_argument("--format", nargs="+", choices=VALID_FORMATS,
                        dest="formats", help="report formats to write")
    parser.add_argument("--join", choices=VALID_JOINS,
                        help="left keeps students without attendance; "
                             "inner drops them")
    parser.add_argument("--course", help="only include this course code")
    parser.add_argument("--min-average", type=float,
                        help="only include students with at least "
                             "this average")
    parser.add_argument("--at-risk-only", action="store_true",
                        help="only include at-risk students")
    parser.add_argument("--exclude-names", action="store_true",
                        help="leave student names out of all outputs")
    parser.add_argument("--log-level",
                        choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    return parser


def apply_cli_overrides(settings: Settings, args: argparse.Namespace) -> None:
    """Copy any command-line options onto settings (CLI has top priority).

    Raises:
        ConfigError: If the combined settings are invalid.
    """
    if args.output_dir:
        settings.output_dir = args.output_dir
    if args.group_by:
        settings.group_by = args.group_by
    if args.formats:
        settings.output_formats = list(dict.fromkeys(args.formats))
    if args.join:
        settings.join = args.join
    if args.log_level:
        settings.log_level = args.log_level
    if args.exclude_names:
        settings.include_names = False
    filters = dict(settings.filters)
    if args.course:
        filters["course"] = args.course
    if args.min_average is not None:
        filters["min_average"] = args.min_average
    if args.at_risk_only:
        filters["at_risk_only"] = True
    settings.filters = filters
    settings.validate()


def setup_logging(level: str, log_file: Path | None = None) -> None:
    """Send log messages to the console and, optionally, a log file.

    Only the ``student_tool`` logger is configured, so running the tool
    repeatedly (e.g. in tests) never duplicates or leaks handlers.
    """
    package_logger = logging.getLogger("student_tool")
    for handler in list(package_logger.handlers):
        package_logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    )
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
        except OSError as exc:
            print(f"Warning: cannot write log file {log_file}: {exc}",
                  file=sys.stderr)
    for handler in handlers:
        handler.setFormatter(formatter)
        package_logger.addHandler(handler)
    package_logger.setLevel(getattr(logging, level.upper()))


def run(args: argparse.Namespace) -> int:
    """Run the full workflow and return a process exit code."""
    try:
        settings = load_settings(args.config)
        apply_cli_overrides(settings, args)
    except ConfigError as exc:
        setup_logging("INFO")
        logger.error("Configuration error: %s", exc)
        return EXIT_ERROR

    setup_logging(settings.log_level, settings.output_dir / "logs" / "run.log")
    logger.info("Student tool %s starting", __version__)

    processor = DataProcessor()
    try:
        for path in args.marks:
            records = load_records(path, required_fields=IDENTITY_FIELDS)
            processor.add_marks_records(records, path.name)
        for path in args.attendance:
            records = load_records(
                path,
                required_fields=("student_id", "sessions_attended",
                                 "sessions_total"),
            )
            processor.add_attendance_records(records, path.name)
    except DataLoadError as exc:
        logger.error("Could not load input: %s", exc)
        return EXIT_ERROR

    students = processor.merge(join=settings.join)
    if not students:
        logger.error("No valid student records were found; nothing to report")
        return EXIT_ERROR

    selected = apply_filters(
        students, settings.filters,
        settings.pass_mark, settings.min_attendance_pct,
    )
    summary = group_summary(
        selected, settings.group_by,
        settings.pass_mark, settings.min_attendance_pct,
    )

    try:
        reports = ReportGenerator(
            settings.output_dir, settings.include_names,
            settings.pass_mark, settings.min_attendance_pct,
        )
        if "csv" in settings.output_formats:
            reports.write_students_csv(selected)
            reports.write_summary_csv(summary, settings.group_by)
        if "json" in settings.output_formats:
            reports.write_students_json(selected)
        if "text" in settings.output_formats:
            reports.write_text_summary(
                selected, summary, settings.group_by,
                dict(processor.stats), settings.filters,
            )
        reports.write_invalid_records(processor.invalid_records)
    except ReportError as exc:
        logger.error("Could not write reports: %s", exc)
        return EXIT_ERROR

    print(build_text_summary(
        selected, summary, settings.group_by, dict(processor.stats),
        settings.filters, settings.pass_mark, settings.min_attendance_pct,
    ))
    print("Files written:")
    for path in reports.written:
        print(f"  {path}")
    logger.info("Finished: %d report file(s) written", len(reports.written))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the tool. Returns the exit code."""
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
