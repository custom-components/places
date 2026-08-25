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


def _automatic_retry_environment(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """Build command paths and environment for an automatic release retry.

    Args:
        tmp_path (Path): Temporary command, state, and output directory.

    Returns:
        tuple[Path, Path, dict[str, str]]: Fake GitHub CLI path, workflow output
            path, and retry environment.
    """
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    gh = bin_directory / "gh"
    output = tmp_path / "output"
    environment = {
        **os.environ,
        "ARTIFACT_NAME": "release-resolution-123",
        "BUMP_TYPE": "patch",
        "EXPLICIT_TAG": "",
        "GITHUB_OUTPUT": str(output),
        "GITHUB_REPOSITORY": "example/places",
        "GITHUB_RUN_ID": "123",
        "IS_PRERELEASE": "false",
        "PATH": f"{bin_directory}{os.pathsep}{os.environ['PATH']}",
        "PERSISTED_TAG_PATH": str(tmp_path / "release-resolution" / "release-tag"),
        "REQUIRE_PERSISTED_TAG": "true",
    }
    return gh, output, environment


def test_missing_retry_artifact_recomputes_automatic_tag(tmp_path: Path) -> None:
    """Recompute safely when attempt one failed before persisting its tag.

    Args:
        tmp_path (Path): Temporary command, state, and output directory.
    """
    gh, output, environment = _automatic_retry_environment(tmp_path)
    gh.write_text(
        """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ["api", "--paginate"]:
    print(json.dumps([[
        {
            "draft": False,
            "prerelease": False,
            "published_at": "2026-08-24T00:00:00Z",
            "tag_name": "v3.0.0",
        }
    ]]))
elif sys.argv[1] == "api":
    print(json.dumps({"artifacts": []}))
else:
    raise SystemExit(f"Unexpected gh arguments: {sys.argv[1:]}")
""",
        encoding="utf-8",
    )
    gh.chmod(0o755)

    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS / "resolve_release_tag.py")],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8") == "release-tag=v3.0.1\n"


def test_retry_artifact_api_failure_does_not_recompute_tag(tmp_path: Path) -> None:
    """Fail closed when retry identity cannot be checked reliably.

    Args:
        tmp_path (Path): Temporary command, state, and output directory.
    """
    gh, output, environment = _automatic_retry_environment(tmp_path)
    gh.write_text(
        """#!/usr/bin/env python3
import sys

sys.stderr.write("GitHub artifact API unavailable\\n")
raise SystemExit(1)
""",
        encoding="utf-8",
    )
    gh.chmod(0o755)

    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS / "resolve_release_tag.py")],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "returned non-zero exit status" in result.stderr
    assert not output.exists()


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


@pytest.mark.parametrize(
    ("path", "content"),
    [
        (
            "custom_components/places/const.py",
            'VERSION = "v3.0.1"\nSAFE = False\n',
        ),
        (
            "custom_components/places/manifest.json",
            '{"version":"v3.0.1","requirements":["unexpected==1.0"]}\n',
        ),
    ],
)
def test_existing_release_commit_rejects_unexpected_allowed_file_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    content: str,
) -> None:
    """Reject unrelated changes hidden inside an allowed release file.

    Args:
        tmp_path (Path): Temporary repository directory.
        monkeypatch (pytest.MonkeyPatch): Working-directory test fixture.
        path (str): Allowed release file containing an unrelated mutation.
        content (str): Mutated release file contents.
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

    (tmp_path / path).write_text(content, encoding="utf-8")
    other_path = {
        "custom_components/places/const.py",
        "custom_components/places/manifest.json",
    }.difference({path}).pop()
    other_content = (
        'VERSION = "v3.0.1"\n' if other_path.endswith("const.py") else '{"version":"v3.0.1"}\n'
    )
    (tmp_path / other_path).write_text(other_content, encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "Release v3.0.1")
    release_sha = _git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="contains unexpected content"):
        validate_release_commit.validate_release_commit(source_sha, release_sha, "v3.0.1")


def test_validate_release_commit_cli_resolves_prepare_script_before_cwd_change(
    tmp_path: Path,
) -> None:
    """Validate exact release content when the CLI script was invoked relatively.

    Args:
        tmp_path (Path): Temporary repository and relative script directory.
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

    subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS / "prepare_release.py"), "v3.0.1"],
        cwd=tmp_path,
        check=True,
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "Release v3.0.1")
    release_sha = _git(tmp_path, "rev-parse", "HEAD")
    script_directory = tmp_path / ".github" / "scripts"
    script_directory.mkdir(parents=True)
    for name in ("prepare_release.py", "validate_release_commit.py"):
        (script_directory / name).symlink_to(SCRIPTS / name)

    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            ".github/scripts/validate_release_commit.py",
            source_sha,
            release_sha,
            "v3.0.1",
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def _publish_environment(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """Create isolated GitHub CLI state for publish-release subprocess tests.

    Args:
        tmp_path (Path): Temporary command and archive directory.

    Returns:
        tuple[Path, Path, dict[str, str]]: Fake CLI path, call log, and environment.
    """
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    archive = tmp_path / "places.zip"
    archive.write_bytes(b"archive")
    calls = tmp_path / "calls"
    environment = {
        **os.environ,
        "CALLS_FILE": str(calls),
        "GH_LOOKUP_EXIT": "0",
        "GH_LOOKUP_STDERR": "",
        "GH_LOOKUP_STDOUT": "",
        "IS_PRERELEASE": "false",
        "PATH": f"{bin_directory}{os.pathsep}{os.environ['PATH']}",
        "RELEASE_ARCHIVE": str(archive),
        "RELEASE_TAG": "v3.1.0",
    }
    return bin_directory / "gh", calls, environment


def _write_publish_gh(gh: Path) -> None:
    """Write a fake GitHub CLI that records calls and controls lookup results.

    Args:
        gh (Path): Fake GitHub CLI executable path.
    """
    gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$CALLS_FILE"
if [[ "$1 $2" == "release view" ]]; then
  if [[ -n "$GH_LOOKUP_STDOUT" ]]; then
    printf '%s\\n' "$GH_LOOKUP_STDOUT"
  fi
  if [[ -n "$GH_LOOKUP_STDERR" ]]; then
    printf '%s\\n' "$GH_LOOKUP_STDERR" >&2
  fi
  exit "$GH_LOOKUP_EXIT"
fi
""",
        encoding="utf-8",
    )
    gh.chmod(0o755)


def _run_publish(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the publish-release CLI with a controlled environment.

    Args:
        environment (dict[str, str]): Environment supplied to the release CLI.

    Returns:
        subprocess.CompletedProcess[str]: Completed release CLI subprocess.
    """
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS / "publish_release.py"), "publish"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def test_existing_published_release_stops_before_mutation(tmp_path: Path) -> None:
    """Reject a non-draft release instead of overwriting or publishing it.

    Args:
        tmp_path (Path): Temporary command and archive directory.
    """
    gh, calls, environment = _publish_environment(tmp_path)
    environment["GH_LOOKUP_STDOUT"] = '{"isDraft":false,"isPrerelease":false}'
    _write_publish_gh(gh)

    result = _run_publish(environment)

    assert result.returncode != 0
    assert "Published GitHub release already exists" in result.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "release view v3.1.0 --json isDraft,isPrerelease"
    ]


@pytest.mark.parametrize(
    ("is_prerelease", "release_tag"),
    [(False, "v3.1.0"), (True, "v3.1.0-beta.1")],
)
def test_not_found_release_create_uses_prerelease_flag_only_when_requested(
    tmp_path: Path,
    is_prerelease: bool,
    release_tag: str,
) -> None:
    """Create absent releases and pass the prerelease flag only when needed.

    Args:
        tmp_path (Path): Temporary command and archive directory.
        is_prerelease (bool): Whether the requested release is a prerelease.
        release_tag (str): Requested release tag.
    """
    gh, calls, environment = _publish_environment(tmp_path)
    environment.update(
        {
            "GH_LOOKUP_EXIT": "1",
            "GH_LOOKUP_STDERR": "HTTP 404: release not found",
            "IS_PRERELEASE": str(is_prerelease).lower(),
            "RELEASE_TAG": release_tag,
        }
    )
    _write_publish_gh(gh)

    result = _run_publish(environment)

    assert result.returncode == 0, result.stderr
    create_call = next(
        call
        for call in calls.read_text(encoding="utf-8").splitlines()
        if call.startswith("release create")
    )
    assert ("--prerelease" in create_call) is is_prerelease


def test_release_lookup_failure_other_than_not_found_fails_closed(tmp_path: Path) -> None:
    """Do not create or publish when release lookup fails unexpectedly.

    Args:
        tmp_path (Path): Temporary command and archive directory.
    """
    gh, calls, environment = _publish_environment(tmp_path)
    environment.update(
        {
            "GH_LOOKUP_EXIT": "1",
            "GH_LOOKUP_STDERR": "HTTP 503: service unavailable",
        }
    )
    _write_publish_gh(gh)

    result = _run_publish(environment)

    assert result.returncode != 0
    assert "HTTP 503: service unavailable" in result.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "release view v3.1.0 --json isDraft,isPrerelease"
    ]


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
  printf '{"isDraft":true,"isPrerelease":false}\\n'
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
        [sys.executable, str(SCRIPTS / "publish_release.py"), "publish"],
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
