# GitHub Copilot & Claude Code Instructions

This repository contains the APIs to manage supported Remeha appliances.

## Git Commit Guidelines

- **Do NOT amend, squash, or rebase commits that have already been pushed to the PR branch after the PR is opened** - Reviewers need to follow the commit history, as well as see what changed since their last review

## Pull Requests

Only open a pull request after a code owner (`.github/CODEOWNERS`) has instructed you to do so in a related github issue. Otherwise, create a github issue first.

## Development Commands

- After finishing a code session, run `uv run --no-sync prek run --all-files` to check for linting and formatting issues.

## Python Syntax Notes

- aio-remeha-modbus supports Python 3.14 as its minimum version. Do not flag syntax or features that require Python 3.14 as issues, and do not suggest workarounds for older Python versions.
- Python 3.14 explicitly allows `except TypeA, TypeB:` without parentheses. Never flag this as an issue.
- Python 3.14 evaluates annotations lazily (PEP 649). Forward references in annotations do not need to be quoted — annotations can reference names defined later in the module without quoting them or using `from __future__ import annotations`. Do not flag unquoted forward references in annotations as issues.

## Testing

- Use `uv run --no-sync pytest` to run tests
- When writing or modifying tests, ensure all test function parameters have type annotations.
- Prefer concrete types (for example, `HomeAssistant`, `MockConfigEntry`, etc.) over `Any`.
- Prefer `@pytest.mark.usefixtures` over arguments, if the argument is not going to be used.
- Avoid using conditions/branching in tests. Instead, either split tests or adjust the test parametrization to cover all cases without branching.
- If multiple tests share most of their code, use `pytest.mark.parametrize` to merge them into a single parameterized test instead of duplicating the body. Use `pytest.param` with an `id` parameter to name the test cases clearly.

## Good practices

- When validation guarantees a dict key exists, prefer direct key access (`data["key"]`) instead of `.get("key")` so contract violations are surfaced instead of silently masked.
- Keep comments concise. Prefer one short line stating the non-obvious constraint, or no comment at all.
- Do not add comments that just restate the code on the following line(s) (e.g. `# Check if initialized` above `if self.initialized:`). Comments should only explain why (non-obvious constraints, surprising behavior, or workarounds), never what. Never add comments that justify a change by referencing what the code looked like before. Comments in tests that explain why a function call or assertion is made are ok.
- Do not add section or divider comments (e.g. `# --- XYZ Triggers ---`) inside or outside of functions, since those can easily become stale and be misleading.
- When catching exceptions, try-clauses should be as small as possible, i.e. avoid wrapping large blocks of code in a try-clause, and avoid catching exceptions from functions that are not expected to raise them.

## AI policy

Be sure to follow the [general contribution rules](CONTRIBUTING.md).
Submissions that do not follow these rules will be closed.
