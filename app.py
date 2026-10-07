#!/usr/bin/env python3
"""Divoom Keeper Studio: the browser shell (same as shell_main.py). Use --demo for a device-free preview."""
import sys

from keeper import shell


def main(argv=None):
    return shell.run(shell.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
