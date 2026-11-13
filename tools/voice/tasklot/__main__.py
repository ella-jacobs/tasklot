"""Entry point for `python3 -m tasklot` (run from tools/voice). See cli.py."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
