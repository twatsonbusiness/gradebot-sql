"""Backward-compatible launcher. Prefer `gradebot` or `python -m gradebot`."""

from gradebot.cli import main

if __name__ == "__main__":
    main()
