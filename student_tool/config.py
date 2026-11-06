"""Configuration loading for the Student Performance Data Transformation Tool.

Settings come from three places, in increasing order of priority:

1. Built-in defaults (``DEFAULTS`` below).
2. Environment variables, optionally loaded from a local ``.env`` file.
3. An optional JSON configuration file passed on the command line.

Command-line options are applied on top of these in ``main.py``.
No credentials or secrets are stored in source code.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

VALID_GROUP_KEYS = ("course", "grade")
VALID_FORMATS = ("csv", "json", "text")
VALID_JOINS = ("left", "inner")
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
VALID_FILTER_KEYS = (
    "course",
    "min_average",
    "max_average",
    "min_attendance",
    "at_risk_only",
)


class ConfigError(Exception):
    """Raised when configuration values are missing, malformed or invalid."""


@dataclass
class Settings:
    """All runtime settings for one run of the tool.

    Attributes:
        output_dir: Folder where reports are written.
        log_level: Logging level name, e.g. ``"INFO"``.
        group_by: Field used to aggregate the summary report.
        output_formats: Which report formats to produce.
        join: ``"left"`` keeps students with no attendance record;
            ``"inner"`` drops them.
        include_names: Whether student names appear in output files.
        pass_mark: Average mark below which a student is at risk.
        min_attendance_pct: Attendance percentage below which a student
            is at risk.
        filters: Filters applied before reports are generated.
    """

    output_dir: Path = Path("output")
    log_level: str = "INFO"
    group_by: str = "course"
    output_formats: list[str] = field(
        default_factory=lambda: list(VALID_FORMATS)
    )
    join: str = "left"
    include_names: bool = True
    pass_mark: float = 50.0
    min_attendance_pct: float = 80.0
    filters: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        """Check that every setting has an allowed value.

        Raises:
            ConfigError: If any setting is invalid.
        """
        if self.group_by not in VALID_GROUP_KEYS:
            raise ConfigError(
                f"group_by must be one of {VALID_GROUP_KEYS}, "
                f"got {self.group_by!r}"
            )
        if self.join not in VALID_JOINS:
            raise ConfigError(
                f"join must be one of {VALID_JOINS}, got {self.join!r}"
            )
        bad_formats = set(self.output_formats) - set(VALID_FORMATS)
        if bad_formats or not self.output_formats:
            raise ConfigError(
                f"output_formats must be a non-empty subset of "
                f"{VALID_FORMATS}, got {self.output_formats!r}"
            )
        if self.log_level.upper() not in VALID_LOG_LEVELS:
            raise ConfigError(f"Unknown log level {self.log_level!r}")
        for name in ("pass_mark", "min_attendance_pct"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not 0 <= value <= 100:
                raise ConfigError(f"{name} must be a number from 0 to 100")
        _validate_filters(self.filters)


def _validate_filters(filters: dict[str, Any]) -> None:
    """Validate the ``filters`` section of the configuration.

    Raises:
        ConfigError: If an unknown key or an invalid value is present.
    """
    if not isinstance(filters, dict):
        raise ConfigError("filters must be a JSON object")
    unknown = set(filters) - set(VALID_FILTER_KEYS)
    if unknown:
        raise ConfigError(f"Unknown filter(s): {sorted(unknown)}")
    for key in ("min_average", "max_average", "min_attendance"):
        if key in filters:
            value = filters[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"Filter {key} must be a number")
            if not 0 <= value <= 100:
                raise ConfigError(f"Filter {key} must be between 0 and 100")
    if "course" in filters:
        course = filters["course"]
        courses = course if isinstance(course, list) else [course]
        if not courses or not all(
            isinstance(c, str) and c.strip() for c in courses
        ):
            raise ConfigError(
                "Filter course must be a string or list of strings"
            )
    if "at_risk_only" in filters and not isinstance(
        filters["at_risk_only"], bool
    ):
        raise ConfigError("Filter at_risk_only must be true or false")


def load_settings(config_path: Path | None = None) -> Settings:
    """Build a ``Settings`` object from defaults, environment and JSON file.

    Args:
        config_path: Optional path to a JSON configuration file.

    Returns:
        A validated ``Settings`` instance.

    Raises:
        ConfigError: If the config file cannot be read or is invalid.
    """
    # Values in a local .env file never override real environment variables.
    load_dotenv(override=False)
    settings = Settings()

    env_output = os.environ.get("STP_OUTPUT_DIR")
    if env_output:
        settings.output_dir = Path(env_output)
    env_level = os.environ.get("STP_LOG_LEVEL")
    if env_level:
        settings.log_level = env_level.upper()

    if config_path is not None:
        _apply_config_file(settings, config_path)

    settings.validate()
    return settings


def _apply_config_file(settings: Settings, config_path: Path) -> None:
    """Read a JSON configuration file and copy its values into settings.

    Raises:
        ConfigError: If the file is missing, unreadable or not valid JSON.
    """
    try:
        with config_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {config_path}") from exc
    except PermissionError as exc:
        raise ConfigError(f"Cannot read config file: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"Config file {config_path} is not valid JSON "
            f"(line {exc.lineno}, column {exc.colno})"
        ) from exc

    if not isinstance(data, dict):
        raise ConfigError("Config file must contain a JSON object")

    allowed = {
        "output_dir", "group_by", "output_formats", "join",
        "include_names", "pass_mark", "min_attendance_pct", "filters",
    }
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError(f"Unknown config key(s): {sorted(unknown)}")

    if "output_dir" in data:
        settings.output_dir = Path(str(data["output_dir"]))
    if "group_by" in data:
        settings.group_by = data["group_by"]
    if "output_formats" in data:
        if not isinstance(data["output_formats"], list):
            raise ConfigError("output_formats must be a list")
        settings.output_formats = data["output_formats"]
    if "join" in data:
        settings.join = data["join"]
    if "include_names" in data:
        if not isinstance(data["include_names"], bool):
            raise ConfigError("include_names must be true or false")
        settings.include_names = data["include_names"]
    for key in ("pass_mark", "min_attendance_pct"):
        if key in data:
            setattr(settings, key, data[key])
    if "filters" in data:
        settings.filters = data["filters"]
    logger.debug("Loaded configuration from %s", config_path)
