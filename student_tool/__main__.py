"""Allow the package to be run with ``python -m student_tool``."""

import sys

from student_tool.main import main

if __name__ == "__main__":
    sys.exit(main())
