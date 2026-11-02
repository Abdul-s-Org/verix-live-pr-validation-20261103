"""Command-line entry point for Verix."""

import argparse
from importlib.metadata import PackageNotFoundError, version


def main() -> None:
    parser = argparse.ArgumentParser(prog="verix", description="Detect stale coding-agent assumptions.")
    try:
        installed_version = version("verix")
    except PackageNotFoundError:
        installed_version = "0.1.0"
    parser.add_argument("--version", action="version", version=f"%(prog)s {installed_version}")
    parser.parse_args()
    parser.print_help()
