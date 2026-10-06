#!/usr/bin/env python3
"""Qt-free entry point: the browser shell (same as `app.py --ui web`). Never imports PySide6."""
import sys

from keeper import shell


def main(argv=None):
    return shell.run(shell.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
