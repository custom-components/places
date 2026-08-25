"""Validate an existing generated release commit before resuming publication."""

from __future__ import annotations

import subprocess
import sys

RELEASE_PATHS = {
    "custom_components/places/const.py",
    "custom_components/places/manifest.json",
}


def _git(*arguments: str) -> str:
    """Run Git and return trimmed standard output."""
    return subprocess.run(  # noqa: S603
        ["git", *arguments],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def validate_release_commit(source_sha: str, release_sha: str, release_tag: str) -> None:
    """Require a direct release-only child of the dispatched source revision."""
    ancestry = _git("rev-list", "--parents", "-n", "1", release_sha).split()
    expected_subject = f"Release {release_tag}"
    if (
        len(ancestry) != 2
        or ancestry[0] != release_sha
        or ancestry[1] != source_sha
        or _git("log", "-1", "--format=%s", release_sha) != expected_subject
    ):
        msg = (
            f"Existing release tag {release_tag} is not a release commit directly based "
            "on this dispatch revision."
        )
        raise ValueError(msg)

    changed_paths = set(_git("diff", "--name-only", source_sha, release_sha).splitlines())
    unexpected_paths = changed_paths - RELEASE_PATHS
    if unexpected_paths:
        msg = f"Existing release tag {release_tag} changes unexpected path: {min(unexpected_paths)}"
        raise ValueError(msg)


def main() -> int:
    """Validate command-line release commit arguments."""
    if len(sys.argv) != 4:
        sys.stderr.write(f"Usage: {sys.argv[0]} SOURCE_SHA RELEASE_SHA RELEASE_TAG\n")
        return 2
    validate_release_commit(*sys.argv[1:])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, subprocess.CalledProcessError) as error:
        sys.stderr.write(f"{error}\n")
        raise SystemExit(1) from error
