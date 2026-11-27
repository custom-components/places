# Contribution guidelines

Contributing to this project should be as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features

## Github is used for everything

Github is used to host code, to track issues and feature requests, as well as accept pull requests.

Pull requests are the best way to propose changes to the codebase.

1. Fork the repo and create your branch from `main`.
2. If you've changed something, update the documentation.
3. Make sure your code lints (using black).
4. Issue that pull request!

## Any contributions you make will be under the GPL-3.0 Software License

In short, when you submit code changes, your submissions are understood to be under the same [License](../../blob/main/LICENSE) that covers the project. Feel free to contact the maintainers if that's a concern.

## Report bugs using Github's [issues](../../issues)

GitHub issues are used to track public bugs.  
Report a bug by [opening a new issue](../../issues/new/choose); it's that easy!

## Write bug reports with detail, background, and sample code

**Great Bug Reports** tend to have:

- A quick summary and/or background
- Steps to reproduce
  - Be specific!
  - Give sample code if you can.
- Show logs
  - Ideally enable debug logging in Home Assistant
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening, or stuff you tried that didn't work)

People *love* thorough bug reports. I'm not even kidding.

## Enable debug logging in Home Assistant

To enable, add this or modify the logging section of your Home Assistant configuration.yaml:
```yaml
logger:
  default: warning
  logs:
    custom_components.places: debug
```

## Use a Consistent Coding Style

Use [ruff](https://docs.astral.sh/ruff) to make sure the code follows the style.

## Test against the supported Home Assistant versions

CI runs the tests twice: once with the Home Assistant release locked in `uv.lock`, and once with the oldest testable release for the minimum declared in `hacs.json` (the `pytest Home Assistant minimum` leg of the matrix in `.github/workflows/pytest_check.yml`). That leg resolves the oldest Home Assistant release at or above that minimum that a test plugin pins: `pytest-homeassistant` from Home Assistant 2026.11, otherwise its predecessor `pytest-homeassistant-custom-component`. This can be newer than the declared minimum, leaving the releases in between untested; the job log shows the version used. The leg installs both pins with the project dependencies and the `pytest-base` group in a separate environment. Raising the minimum in `hacs.json` is all it needs. Both legs use the Python range declared by `[project].requires-python` in [`pyproject.toml`](pyproject.toml). They check the installed test environment and print its Python, Home Assistant and test plugin versions.

Import Home Assistant test plugin helpers such as `MockConfigEntry` from `tests.common` so the tests work with either plugin.

To reproduce it locally, run the workflow's minimum steps from a separate clone with `RUNNER_TEMP` set to a scratch directory. The steps create their own `.venv` in the current directory. If one already exists, `uv venv` fails without a terminal, but in a terminal it asks whether to replace it, and the default answer is yes.

## License

By contributing, you agree that your contributions will be licensed under its GPL-3.0 License.
