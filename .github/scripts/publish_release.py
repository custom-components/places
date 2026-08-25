"""Validate, create, resume, and publish a GitHub release."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

NOT_FOUND_PATTERN = re.compile(r"HTTP 404|release not found", re.IGNORECASE)


def _required_environment(name: str) -> str:
    """Read a required non-empty environment variable.

    Args:
        name (str): Environment variable name.

    Returns:
        str: Trimmed environment variable value.

    Raises:
        ValueError: If the environment variable is empty or missing.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        msg = f"{name} is required"
        raise ValueError(msg)
    return value


def _release_state(release_tag: str) -> tuple[bool, bool] | None:
    """Return an existing release's draft and prerelease state.

    Args:
        release_tag (str): Release tag to inspect.

    Returns:
        tuple[bool, bool] | None: Draft and prerelease flags, or ``None`` when
            the release does not exist.

    Raises:
        TypeError: If GitHub returns an unexpected response.
        subprocess.CalledProcessError: If the release lookup fails for a reason
            other than the release not existing.
    """
    result = subprocess.run(  # noqa: S603
        ["gh", "release", "view", release_tag, "--json", "isDraft,isPrerelease"],  # noqa: S607
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if NOT_FOUND_PATTERN.search(result.stderr):
            return None
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )

    payload: object = json.loads(result.stdout)
    if not isinstance(payload, dict):
        msg = "GitHub release response has an unexpected shape"
        raise TypeError(msg)
    is_draft = payload.get("isDraft")
    is_prerelease = payload.get("isPrerelease")
    if not isinstance(is_draft, bool) or not isinstance(is_prerelease, bool):
        msg = "GitHub release response is missing boolean state fields"
        raise TypeError(msg)
    return is_draft, is_prerelease


def _run_gh(*arguments: str) -> None:
    """Run a GitHub CLI command.

    Args:
        *arguments (str): GitHub CLI arguments.
    """
    subprocess.run(["gh", *arguments], check=True)  # noqa: S603, S607


def publish_release(mode: str) -> None:
    """Validate release state and optionally create or publish the release.

    Args:
        mode (str): Either ``check`` for validation or ``publish`` for mutation.

    Raises:
        ValueError: If the request or existing release state is invalid.
    """
    if mode not in {"check", "publish"}:
        msg = "Mode must be check or publish"
        raise ValueError(msg)

    release_tag = _required_environment("RELEASE_TAG")
    prerelease_value = _required_environment("IS_PRERELEASE")
    if prerelease_value not in {"true", "false"}:
        msg = "IS_PRERELEASE must be true or false"
        raise ValueError(msg)
    is_prerelease = prerelease_value == "true"
    archive = Path(_required_environment("RELEASE_ARCHIVE")) if mode == "publish" else None

    state = _release_state(release_tag)
    if state is not None:
        is_draft, existing_is_prerelease = state
        if not is_draft:
            msg = f"Published GitHub release already exists: {release_tag}"
            raise ValueError(msg)
        if existing_is_prerelease != is_prerelease:
            msg = "Existing GitHub release prerelease state does not match the request."
            raise ValueError(msg)
        if mode == "publish" and archive is not None:
            _run_gh("release", "upload", release_tag, f"{archive}#places.zip", "--clobber")
    elif mode == "publish" and archive is not None:
        arguments = [
            "release",
            "create",
            release_tag,
            f"{archive}#places.zip",
            "--draft",
            "--generate-notes",
            "--title",
            release_tag,
            "--verify-tag",
        ]
        if is_prerelease:
            arguments.append("--prerelease")
        _run_gh(*arguments)

    if mode == "publish":
        _run_gh("release", "edit", release_tag, "--draft=false")


def main() -> int:
    """Parse arguments and run the requested release operation.

    Returns:
        int: Zero when the release operation succeeds, otherwise one.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "publish"))
    args = parser.parse_args()
    try:
        publish_release(args.mode)
    except (
        OSError,
        TypeError,
        ValueError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as error:
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            sys.stderr.write(error.stderr)
        else:
            sys.stderr.write(f"{error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
