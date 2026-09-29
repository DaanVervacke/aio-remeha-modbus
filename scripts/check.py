"""Local CI gate: run every check tool in order and exit with the first failure's code.

CI runs this script directly, so local and CI checks are identical (lint -> test -> coverage -> docs,
with the coverage floor from pyproject.toml's fail_under).
"""

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

PYTEST_COVERAGE_REPORT = Path("pytest-coverage.txt")

# (command, optional file to mirror the command's stdout into, whether re-running auto-fixes failures)
COMMANDS: tuple[tuple[tuple[str, ...], Path | None, bool], ...] = (
    (("uv", "run", "--no-sync", "prek", "run", "--all-files"), None, True),
    (
        (
            "uv",
            "run",
            "--no-sync",
            "pytest",
            "--cov-report=term-missing",
            "--junitxml=junit-coverage.xml",
            "--cov=aio_remeha_modbus",
        ),
        PYTEST_COVERAGE_REPORT,
        False,
    ),
    (
        (
            "uv",
            "run",
            "--group",
            "docs",
            "sphinx-build",
            "-W",
            "--keep-going",
            "-b",
            "html",
            "docs/source",
            "docs/_build/html",
        ),
        None,
        False,
    ),
)


def run_command(command: Sequence[str], tee_to: Path | None = None) -> int:
    """Run *command* and return its exit code without raising on failure."""
    print(f"\n$ {' '.join(command)}", flush=True)
    if tee_to is None:
        return subprocess.run(command, check=False).returncode

    with tee_to.open("w") as report:
        # Only stdout is mirrored: pytest-coverage.txt is parsed by the coverage workflow,
        # and stderr noise (warnings, tracebacks) would corrupt that report.
        process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
        if process.stdout is None:  # unreachable with stdout=PIPE, kept for narrowing
            return process.wait()
        for line in process.stdout:
            report.write(line)
            print(line, end="", flush=True)
        return process.wait()


def main() -> int:
    """Run all check commands in sequence: stop and propagate the exit code on first failure."""
    for command, tee_to, auto_fixable in COMMANDS:
        return_code = run_command(command, tee_to)
        if return_code != 0:
            if auto_fixable:
                print(
                    f"\nhint: re-running may auto-fix lint/format findings: $ {' '.join(command)}",
                    file=sys.stderr,
                )
            return return_code
    return 0


if __name__ == "__main__":
    sys.exit(main())
