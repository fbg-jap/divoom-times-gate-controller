#!/usr/bin/env python3
"""Entry point of the packaged browser shell (same as app.py). Never imports PySide6."""
import sys

from keeper import shell


def main(argv=None):
    shell.ensure_std_streams()
    return shell.run(shell.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
