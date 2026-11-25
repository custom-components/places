# AGENTS

## Purpose

- Provide clear, repo-specific instructions for autonomous agents working in this repository.

## General Guidelines

- Follow Home Assistant developer docs: https://developers.home-assistant.io/docs/.
- Be concise and explain coding steps briefly when making code changes; include code snippets and tests where relevant.
- For non-trivial edits, provide a short plan. For small, low-risk edits, implement and include a one-line summary.
- Focus on a single conceptual change at a time when public APIs or multiple modules are affected.
- Maintain project style and Python 3.14+ compatibility. Target latest Home Assistant core.
- If deviating from these guidelines, explicitly state which guideline is deviated from and why.

## Agent permissions and venv policy

- Create or refresh the repository-local `./.venv` with `uv sync --frozen --group dev`, which installs the locked lint and pytest tooling, and run commands through `./.venv/bin/python`. Avoid unrelated network operations without explicit consent.

## Folder structure (repo-specific)

- `custom_components/places`: integration code.
- `tests`: pytest test suite and fixtures.
- `README.md`: primary documentation.

## Coding standards

- Follow [`CODING_STANDARDS.md`](./CODING_STANDARDS.md) for types, docstrings, error handling and logging, project structure, Home Assistant integration hygiene, and tests.
- Use the terms defined in [`GLOSSARY.md`](./GLOSSARY.md).
- Verify changes in proportion to their risk and update documentation if needed.

## Local tooling (common commands)

- Use `prek` and `pytest` configured in the repo. You must run these inside `./.venv`.
- Prefer invoking tooling via `./.venv/bin/python -m ...` rather than relying on global/shell entry points (e.g., `prek`).
- `ruff` is used for linting and formatting but should be called using `prek`.
- Run tests:
  - `./.venv/bin/python -m pytest`
- Run prek on all files (includes `ruff` and `mypy`):
  - `./.venv/bin/python -m prek run -a`

## Running tests

- By default, run the full pytest suite when tests are requested (the repo is small and full pytest runs are acceptable). If the user specifically asks for a focused test run, run targeted tests instead.
- If tests fail due to missing dev dependencies, install them into `./.venv` and add them into the `pyproject.toml` dependencies when appropriate.

## PR and branch behavior

- The agent will only push commits or open PRs when the user explicitly requests it.
- Every PR title must start with a [Conventional Commits](https://www.conventionalcommits.org/) prefix, such as `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, `build:`, `ci:`, or `chore:`, with an optional scope like `fix(config_flow):`. Mark breaking changes with `!` before the colon.
- Use the same Conventional Commits prefixes for commit messages.

## Network / install consent

- Obtain explicit consent before any network operations outside the repository not strictly needed to run local tests.
- Package installs required for running tests are allowed when user approves.

## CI/CD

- Use GitHub Actions for CI/CD where applicable.

## Agent skills

### Issue tracker

Issues and specs are local markdown files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), recorded as a `Status:` line in each issue file. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
