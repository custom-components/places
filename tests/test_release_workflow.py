"""Behavior tests for release workflow helpers."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).parents[1] / ".github" / "scripts"


def _load_script(name: str) -> ModuleType:
    """Load a release helper as a Python module.

    Args:
        name (str): Script filename.

    Returns:
        ModuleType: Loaded script module.
    """
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


resolve_release_tag = _load_script("resolve_release_tag.py")
validate_release_commit = _load_script("validate_release_commit.py")


def _release(tag: str, *, draft: bool = False, prerelease: bool = False) -> dict[str, object]:
    """Build representative GitHub release data.

    Args:
        tag (str): Release tag.
        draft (bool): Whether the release is a draft.
        prerelease (bool): Whether the release is a prerelease.

    Returns:
        dict[str, object]: Representative release data.
    """
    return {
        "draft": draft,
        "prerelease": prerelease,
        "published_at": "2026-08-24T00:00:00Z",
        "tag_name": tag,
    }


@pytest.mark.parametrize(
    ("bump", "expected"),
    [("patch", "v3.2.10"), ("minor", "v3.3.0"), ("major", "v4.0.0")],
)
def test_stable_bumps_use_highest_published_stable_release(bump: str, expected: str) -> None:
    """Ignore drafts, prereleases, and non-SemVer tags when automatically bumping.

    Args:
        bump (str): Requested stable version component.
        expected (str): Expected resolved release tag.
    """
    releases = [
        _release("v3.2.9"),
        _release("v4.0.0-beta.1", prerelease=True),
        _release("v9.0.0", draft=True),
        _release("v3.2.9.1"),
        _release("v3.1.20"),
    ]

    assert resolve_release_tag.resolve_release_tag("", False, bump, releases) == expected


def test_explicit_prerelease_tag_overrides_bump() -> None:
    """Use tag text for prereleases even when a stable bump is selected."""
    assert (
        resolve_release_tag.resolve_release_tag("v4.0.0-beta.1", True, "major", [])
        == "v4.0.0-beta.1"
    )


def test_prerelease_requires_explicit_tag() -> None:
    """Do not synthesize prerelease identifiers from the stable bump dropdown."""
    with pytest.raises(ValueError, match="Prereleases require an explicit release tag"):
        resolve_release_tag.resolve_release_tag("", True, "minor", [])


def test_explicit_tag_rerun_does_not_require_automatic_state(tmp_path: Path) -> None:
    """Keep explicit tags independent from persisted automatic bump state.

    Args:
        tmp_path (Path): Temporary test directory.
    """
    output = tmp_path / "output"
    environment = {
        **os.environ,
        "BUMP_TYPE": "major",
        "EXPLICIT_TAG": "v3.1.0-beta.2",
        "GITHUB_OUTPUT": str(output),
        "IS_PRERELEASE": "true",
        "PERSISTED_TAG_PATH": str(tmp_path / "missing" / "release-tag"),
        "REQUIRE_PERSISTED_TAG": "true",
    }

    subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS / "resolve_release_tag.py")],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert output.read_text(encoding="utf-8") == "release-tag=v3.1.0-beta.2\n"


def _git(repository: Path, *arguments: str) -> str:
    """Run Git in a temporary repository.

    Args:
        repository (Path): Repository working directory.
        *arguments (str): Git arguments.

    Returns:
        str: Trimmed standard output.
    """
    return subprocess.run(  # noqa: S603
        ["git", *arguments],  # noqa: S607
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_existing_release_commit_rejects_unexpected_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a matching release commit that would add unrelated content to the archive.

    Args:
        tmp_path (Path): Temporary repository directory.
        monkeypatch (pytest.MonkeyPatch): Working-directory test fixture.
    """
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Release Test")
    _git(tmp_path, "config", "user.email", "release@example.com")
    integration = tmp_path / "custom_components" / "places"
    integration.mkdir(parents=True)
    (integration / "manifest.json").write_text('{"version":"v3.0.0"}\n', encoding="utf-8")
    (integration / "const.py").write_text('VERSION = "v3.0.0"\n', encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "Source")
    source_sha = _git(tmp_path, "rev-parse", "HEAD")

    (integration / "manifest.json").write_text('{"version":"v3.0.1"}\n', encoding="utf-8")
    (integration / "const.py").write_text('VERSION = "v3.0.1"\n', encoding="utf-8")
    (integration / "unexpected.py").write_text("UNEXPECTED = True\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "Release v3.0.1")
    release_sha = _git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="changes unexpected path"):
        validate_release_commit.validate_release_commit(source_sha, release_sha, "v3.0.1")


def test_draft_prerelease_mismatch_stops_before_upload(tmp_path: Path) -> None:
    """Do not upload or publish when an existing draft has different prerelease state.

    Args:
        tmp_path (Path): Temporary command and archive directory.
    """
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    calls = tmp_path / "calls"
    gh = bin_directory / "gh"
    gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$CALLS_FILE"
if [[ "$*" == "release view"* ]]; then
  printf 'true\\tfalse\\n'
fi
""",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    archive = tmp_path / "places.zip"
    archive.write_bytes(b"archive")
    environment = {
        **os.environ,
        "CALLS_FILE": str(calls),
        "IS_PRERELEASE": "true",
        "PATH": f"{bin_directory}{os.pathsep}{os.environ['PATH']}",
        "RELEASE_ARCHIVE": str(archive),
        "RELEASE_TAG": "v3.1.0-beta.1",
        "RUNNER_TEMP": str(tmp_path),
    }

    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPTS / "publish_release.sh"), "publish"],  # noqa: S607
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "prerelease state does not match" in result.stderr
    recorded_calls = calls.read_text(encoding="utf-8")
    assert "release view v3.1.0-beta.1" in recorded_calls
    assert "release upload" not in recorded_calls
    assert "release create" not in recorded_calls
    assert "release edit" not in recorded_calls
