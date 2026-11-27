# Coding standards

Rules for code in this repository, read during review. Use the terms defined in [`GLOSSARY.md`](./GLOSSARY.md) in names, docstrings, and user-visible text. Agent workflow rules (permissions, venv, running tests, PR behavior) live in [`AGENTS.md`](./AGENTS.md).

## Enforced by tooling

Do not restate or hand-check these. `prek` runs them, and CI should agree:

- Ruff (`select = ["ALL"]`, 100-column lines, double quotes, Google docstring convention) for lint and formatting.
- mypy for types, and pydoclint for docstring/signature agreement.
- cspell and codespell for spelling. Add a legitimate new word to `cspell.config.toml` instead of rewording around it.

Run them with `./.venv/bin/python -m prek run -a`.

## Judgement calls

### Types

- Annotate every function and class, including return types.
- Use `Any` only when the value really is arbitrary. Do not use `cast` unless there is no alternative.
- Do not use `assert` outside tests.

### Documentation

- Every file, class, and method has a docstring, including private and nested methods. Method docstrings use Google style.
- Update the docstring in the same change that alters the behavior or interface it describes.
- Keep existing comments unless they are now wrong; correct those.

### Errors and logging

- Log through Home Assistant's logging framework, with clear debug and info messages.
- Catch specific exceptions. A broad catch needs a comment saying why it is unavoidable and a log line with context.

### Structure

- Keep modules focused: separate files for entity types, services, and utilities.
- Constants live in `const.py`. Configuration flows live in `config_flow.py`.
- Imports go at the top of the file.
- Fix the root cause rather than the symptom, and keep each change minimal and consistent with the surrounding style.

### Home Assistant integration

- Changing config or options text, or any user-visible string, means updating `translations/*.json` in the same change.
- Changing install or configuration steps means updating `README.md` and `hacs.json` as needed.
- Target the latest Home Assistant core and the Python range declared in [`pyproject.toml`](./pyproject.toml).

## Tests

- Use pytest and its plugins, not `unittest`. Use Home Assistant test plugin helpers, preferring `MockConfigEntry` for config entries, and import them from `tests.common` so tests run on every supported Home Assistant version.
- Parameterize similar cases instead of writing near-duplicate tests, and delete placeholder tests the parameterized version replaces.
- Add or update tests when they protect a meaningful behavioral contract or reproduce a bug that existing coverage would miss.
- Test observable behavior at the real interface, including material failure paths. Do not add tests that mirror the implementation, assert configuration text, or duplicate existing checks.
- Each behavior test goes red when the rule it names is broken. When reviewing a test that looks like it could pass without its rule, break the rule in a scratch copy and run the test.
- Each integration source file has one test module. Add to the existing module, and split only past about 1000 lines. End-to-end tests belong in `test_integration.py`.
- Use fixtures and mocks to isolate tests. Shared fixtures and helpers go in `conftest.py`. Tests are typed and documented in Google style.
- For documentation, declarative configuration, and small workflow changes, run the relevant validators, linters, or focused runtime checks when they give enough confidence. Add automation tests only when executable logic or material operational risk warrants them, and keep those separate from unrelated integration tests.
- Keep coverage at 80% or higher. Address warnings rather than suppressing them: never run pytest with `--disable-warnings`.
