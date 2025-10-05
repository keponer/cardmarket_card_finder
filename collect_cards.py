"""CLI entrypoint for Card Market Finder.

This module delegates to the package CLI implemented in `cmf.cli`.
"""
import sys
from cmf.cli import run_cli


if __name__ == "__main__":
    sys.exit(run_cli())


