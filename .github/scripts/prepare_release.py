"""Validate a release tag and prepare the integration version files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

TAG_PATTERN = re.compile(
    r"^v[0-9]+(?:\.[0-9]+){1,3}(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?(?:[A-Za-z]+[0-9]+)?$"
)
MANIFEST_VERSION_PATTERN = re.compile(r'("version"\s*:\s*)"[^"]*"')
CONST_VERSION_PATTERN = re.compile(r'^(VERSION\s*=\s*)"[^"]*"', re.MULTILINE)


def validate_release_tag(tag: str) -> None:
    """Validate a release tag against the repository's supported formats.

    Args:
        tag (str):
            Candidate release tag.

    Raises:
        ValueError: If the tag does not use a supported version format.
    """
    if TAG_PATTERN.fullmatch(tag) is None:
        msg = f"Invalid release tag: {tag}"
        raise ValueError(msg)


def _replace_version(
    content: str,
    pattern: re.Pattern[str],
    tag: str,
    path: Path,
) -> str:
    """Replace one version declaration while preserving its formatting.

    Args:
        content (str):
            Original file content.
        pattern (re.Pattern[str]):
            Pattern whose first group precedes the version string.
        tag (str):
            Validated release tag.
        path (Path):
            Source path used in error messages.

    Returns:
        str: Content containing the requested release version.

    Raises:
        ValueError: If the file does not contain exactly one version declaration.
    """
    updated, replacements = pattern.subn(lambda match: f'{match.group(1)}"{tag}"', content)
    if replacements != 1:
        msg = f"Expected one version declaration in {path}, found {replacements}."
        raise ValueError(msg)
    return updated


def update_release_versions(repository: Path, tag: str) -> None:
    """Update manifest.json and const.py to the release tag.

    Both files are validated before either is written, preventing a partial update.

    Args:
        repository (Path):
            Repository root containing the integration.
        tag (str):
            Requested release tag.

    Raises:
        ValueError: If the tag or either version declaration is invalid.
    """
    validate_release_tag(tag)
    integration = repository / "custom_components" / "places"
    manifest_path = integration / "manifest.json"
    const_path = integration / "const.py"

    manifest = _replace_version(
        manifest_path.read_text(encoding="utf-8"),
        MANIFEST_VERSION_PATTERN,
        tag,
        manifest_path,
    )
    const = _replace_version(
        const_path.read_text(encoding="utf-8"),
        CONST_VERSION_PATTERN,
        tag,
        const_path,
    )

    if json.loads(manifest).get("version") != tag:
        msg = f"Failed to update {manifest_path} to {tag}."
        raise ValueError(msg)

    manifest_path.write_text(manifest, encoding="utf-8")
    const_path.write_text(const, encoding="utf-8")


def main() -> int:
    """Run the release preparation command.

    Returns:
        int: Zero when validation or version preparation succeeds.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="Release tag, such as v3.0.1")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate the tag without updating version files",
    )
    args = parser.parse_args()

    try:
        if args.check_only:
            validate_release_tag(args.tag)
        else:
            update_release_versions(Path.cwd(), args.tag)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
