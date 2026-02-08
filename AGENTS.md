# AGENTS

## Purpose

- Provide clear, repo-specific instructions for autonomous agents working in this repository.

## General Guidelines

- Follow Home Assistant developer docs: https://developers.home-assistant.io/docs/.
- Be concise and explain coding steps briefly when making code changes; include code snippets and tests where relevant.
- For non-trivial edits, provide a short plan. For small, low-risk edits, implement and include a one-line summary.
- Focus on a single conceptual change at a time when public APIs or multiple modules are affected.
- Maintain project style and Python 3.13+ compatibility. Target latest Home Assistant core.
- If deviating from these guidelines, explicitly state which guideline is deviated from and why.

## Agent permissions and venv policy

- Agents may create and use a repository-local venv at `./.venv` and should reference `./.venv/bin/python` when running commands.
- Installing packages from repo manifests (prefer `pyproject.toml`) into `./.venv` is allowed for running tests or local tooling; avoid unrelated network operations without explicit consent.

## Home Assistant integration hygiene

- When changing config/options text or UI-visible strings:
  - Update `translations/*.json` as needed.
- When changing install/config steps:
  - Update `README.md` and `hacs.json` as needed.

## Folder structure (repo-specific)

- `custom_components/places`: integration code.
- `tests`: pytest test suite and fixtures.
- `README.md`: primary documentation.

## Project structure expectations

- Keep code modular: separate files for entity types, services, and utilities.
- Store constants in `const.py` and use a `config_flow.py` for configuration flows.

## Coding standards

- Add typing annotations to all functions and classes (including return types).
- Add or update docstrings for all files, classes and methods, including private methods. Method docstrings must be in NumPy format.
- Preserve existing comments and keep imports at the top of files.
- When editing code, prefer fixing root causes over surface patches.
- Keep changes minimal and consistent with the codebase style.
- Add tests for any changed behavior and update documentation if needed.

## Error handling & logging

- Use Home Assistant's logging framework.
- Catch specific exceptions (do not catch Exception directly).
- If a broad catch is unavoidable, document why in a comment and include contextual logging.
- Add robust error handling and clear debug/info logs.

## Local tooling (common commands)

- Use `pre-commit`, `mypy`, and `pytest` configured in the repo. You must run these inside `./.venv`.
- Prefer invoking tooling via `./.venv/bin/python -m ...` rather than relying on global/shell entry points (e.g., `pre-commit`).
- `ruff` is used for linting and formatting but should be called using `pre-commit`.
- Run tests:
  - `./.venv/bin/python -m pytest`
- Run pre-commit on all files (includes `ruff`):
  - `./.venv/bin/python -m pre_commit run --all-files`
- Run mypy (use repo configuration):
  - `./.venv/bin/python -m mypy`

## Testing

- Use pytest (not unittest) and pytest plugins for all tests.
- Use pytest-homeassistant-custom-component for Home Assistant–specific testing utilities (prefer `MockConfigEntry` for config entries).
- Parameterize tests instead of creating multiple similar test functions when appropriate.
- Aim for at least 80% code coverage.
- Don't run pytest with `--disable-warnings` and address all warnings.
- By default, the agent should run the full pytest suite when tests are requested (the repo is small and full pytest runs are acceptable). If the user specifically asks for a focused test run, the agent may run targeted tests instead.
- Use fixtures and mocks to isolate tests.
- Use `conftest.py` for shared test utilities and fixtures.
- Add typed, well-documented tests in `tests/` and use fixtures in `conftest.py`. Test documentation must use NumPy format.
- One test file per integration file: every integration source file should have a single corresponding test module; add new unit tests for that integration to that existing test module. Only split into additional test modules if the existing test module would exceed ~1000 lines, except for explicit end-to-end/integration tests in `test_integration.py`.
- If tests fail due to missing dev dependencies, install them into `./.venv` and add them into the `pyproject.toml` dependencies when appropriate.
- When parameterizing tests, delete any legacy placeholder tests and related comments.
- When making changes to code, include tests for the new/changed behavior; the agent should add tests alongside code edits even when changes are not minimally invasive.

## PR and branch behavior

- The agent will only create branches or open PRs when the user explicitly requests it or includes the hashtag `#github-pull-request_copilot-coding-agent` to hand off to the asynchronous coding agent.

## Network / install consent

- Obtain explicit consent before any network operations outside the repository not strictly needed to run local tests.
- Package installs required for running tests are allowed when user approves.

## CI/CD

- Use GitHub Actions for CI/CD where applicable.
