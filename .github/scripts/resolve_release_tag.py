"""Resolve an explicit or automatically bumped release tag."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

STABLE_TAG_PATTERN = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
BUMP_TYPES = {"none", "patch", "minor", "major"}


def _stable_versions(releases: list[dict[str, Any]]) -> list[tuple[int, int, int]]:
    """Return published stable semantic versions from GitHub release data."""
    versions: list[tuple[int, int, int]] = []
    for release in releases:
        if release.get("draft") is not False or release.get("prerelease") is not False:
            continue
        if not isinstance(release.get("published_at"), str):
            continue
        match = STABLE_TAG_PATTERN.fullmatch(str(release.get("tag_name", "")))
        if match is not None:
            major, minor, patch = (int(part) for part in match.groups())
            versions.append((major, minor, patch))
    return versions


def resolve_release_tag(
    explicit_tag: str,
    is_prerelease: bool,
    bump_type: str,
    releases: list[dict[str, Any]],
) -> str:
    """Resolve the requested tag while reserving automatic bumps for stable releases."""
    explicit_tag = explicit_tag.strip()
    if bump_type not in BUMP_TYPES:
        msg = "Bump type must be none, patch, minor, or major"
        raise ValueError(msg)
    if explicit_tag or is_prerelease:
        if not explicit_tag:
            msg = "Prereleases require an explicit release tag"
            raise ValueError(msg)
        return explicit_tag
    if bump_type == "none":
        msg = "Provide an explicit release tag or select a version bump"
        raise ValueError(msg)

    versions = _stable_versions(releases)
    if not versions:
        msg = "No published stable semantic release is available to bump"
        raise ValueError(msg)
    major, minor, patch = max(versions)
    if bump_type == "patch":
        patch += 1
    elif bump_type == "minor":
        minor += 1
        patch = 0
    else:
        major += 1
        minor = 0
        patch = 0
    return f"v{major}.{minor}.{patch}"


def _required_environment(name: str) -> str:
    """Read a required non-empty environment variable."""
    value = os.environ.get(name, "").strip()
    if not value:
        msg = f"{name} is required"
        raise ValueError(msg)
    return value


def _read_persisted_tag(path: Path) -> str | None:
    """Read and validate a tag persisted by an earlier run attempt."""
    try:
        tag = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    if STABLE_TAG_PATTERN.fullmatch(tag) is None:
        msg = "Persisted automatic release tag is invalid"
        raise ValueError(msg)
    return tag


def _github_releases(repository: str) -> list[dict[str, Any]]:
    """Load every GitHub release page for the repository."""
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repository}/releases?per_page=100",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    pages = json.loads(result.stdout)
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        msg = "GitHub releases response has an unexpected shape"
        raise ValueError(msg)
    return [release for page in pages for release in page if isinstance(release, dict)]


def main() -> int:
    """Resolve and write the release tag as a workflow output."""
    explicit_tag = os.environ.get("EXPLICIT_TAG", "")
    prerelease_value = os.environ.get("IS_PRERELEASE", "")
    bump_type = os.environ.get("BUMP_TYPE", "none").strip()
    require_persisted = os.environ.get("REQUIRE_PERSISTED_TAG", "false").strip()
    if prerelease_value not in {"true", "false"}:
        msg = "IS_PRERELEASE must be true or false"
        raise ValueError(msg)
    if require_persisted not in {"true", "false"}:
        msg = "REQUIRE_PERSISTED_TAG must be true or false"
        raise ValueError(msg)

    persisted_path_value = os.environ.get("PERSISTED_TAG_PATH", "").strip()
    persisted_path = Path(persisted_path_value) if persisted_path_value else None
    automatic_release = not explicit_tag.strip() and prerelease_value == "false"
    tag: str | None = None
    if automatic_release:
        if persisted_path is not None:
            tag = _read_persisted_tag(persisted_path)
        if tag is None and require_persisted == "true":
            msg = "Persisted automatic release tag is missing"
            raise ValueError(msg)
    if tag is None:
        releases = []
        if automatic_release and bump_type != "none":
            releases = _github_releases(_required_environment("GITHUB_REPOSITORY"))
        tag = resolve_release_tag(
            explicit_tag,
            prerelease_value == "true",
            bump_type,
            releases,
        )
        if persisted_path is not None and automatic_release:
            persisted_path.parent.mkdir(parents=True, exist_ok=True)
            persisted_path.write_text(f"{tag}\n", encoding="utf-8")

    output_path = Path(_required_environment("GITHUB_OUTPUT"))
    with output_path.open("a", encoding="utf-8") as output:
        output.write(f"release-tag={tag}\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        sys.stderr.write(f"{error}\n")
        raise SystemExit(1) from error
