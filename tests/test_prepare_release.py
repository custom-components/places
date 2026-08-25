"""Tests for release version preparation."""

import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / ".github" / "scripts" / "prepare_release.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("prepare_release", SCRIPT_PATH)
assert SCRIPT_SPEC is not None
assert SCRIPT_SPEC.loader is not None
prepare_release = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(prepare_release)


@pytest.mark.parametrize(
    "tag",
    ["v3.0.1", "v3.1.0-beta.1", "v2.9.4.1", "v3.0.0b1"],
)
def test_validate_release_tag_accepts_supported_formats(tag: str) -> None:
    """Accept version formats already used by the repository.

    Args:
        tag (str):
            Supported release tag under test.
    """
    prepare_release.validate_release_tag(tag)


@pytest.mark.parametrize(
    "tag",
    ["", "3.0.1", "v3", "v3.0.1 beta", "v3.0.1;echo-bad"],
)
def test_validate_release_tag_rejects_unsupported_formats(tag: str) -> None:
    """Reject malformed tags before they reach Git or GitHub commands.

    Args:
        tag (str):
            Unsupported release tag under test.
    """
    with pytest.raises(ValueError, match="Invalid release tag"):
        prepare_release.validate_release_tag(tag)


@pytest.mark.parametrize(
    ("bump_type", "expected_tag"),
    [
        ("patch", "v3.12.10"),
        ("minor", "v3.13.0"),
        ("major", "v4.0.0"),
    ],
)
def test_next_stable_release_tag_uses_highest_stable_version(
    bump_type: str, expected_tag: str
) -> None:
    """Ignore non-stable tags while incrementing the highest stable release.

    Args:
        bump_type (str): Requested version increment.
        expected_tag (str): Expected next stable release tag.
    """
    tags = [
        "v3.12.9",
        "v3.12.9-beta.1",
        "v3.12.9.1",
        "v3.12.10b1",
        "invalid",
        "v2.99.99",
        "v3.12.10-rc.1",
        "v3.12.9",
    ]

    assert prepare_release.next_stable_release_tag(tags, bump_type) == expected_tag


@pytest.mark.parametrize(
    ("tags", "bump_type", "message"),
    [
        (["v3.0.0-beta.1", "v3.0.0.1"], "patch", "No stable released tag"),
        (["v3.0.0"], "feature", "Unsupported bump type"),
    ],
)
def test_next_stable_release_tag_rejects_invalid_requests(
    tags: list[str], bump_type: str, message: str
) -> None:
    """Reject requests without a supported stable release increment.

    Args:
        tags (list[str]): Candidate release tag names.
        bump_type (str): Requested version increment.
        message (str): Expected failure message.
    """
    with pytest.raises(ValueError, match=message):
        prepare_release.next_stable_release_tag(tags, bump_type)


def test_next_tag_cli_reads_tags_from_standard_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Print the next stable tag without writing integration version files.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture for replacing CLI inputs.
        capsys (pytest.CaptureFixture[str]): Fixture for capturing CLI output.
    """
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT_PATH), "--next-tag", "minor"],
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO("v2.9.4\nv3.0.0-beta.1\nv2.10.1\n"))

    assert prepare_release.main() == 0
    assert capsys.readouterr().out == "v2.11.0\n"


def test_check_only_cli_preserves_positional_tag_contract(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Validate an explicit positional tag without writing files.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture for replacing CLI arguments.
        capsys (pytest.CaptureFixture[str]): Fixture for capturing CLI output.
    """
    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH), "--check-only", "v3.0.1"])

    assert prepare_release.main() == 0
    assert capsys.readouterr().out == ""


def _write_version_files(repository: Path, const_content: str | None = None) -> tuple[Path, Path]:
    """Create representative integration version files.

    Args:
        repository (Path):
            Temporary repository root.
        const_content (str | None):
            Optional const.py content override.

    Returns:
        tuple[Path, Path]: Paths to manifest.json and const.py.
    """
    integration = repository / "custom_components" / "places"
    integration.mkdir(parents=True)
    manifest_path = integration / "manifest.json"
    const_path = integration / "const.py"
    manifest_path.write_text(
        '{\n  "domain": "places",\n  "version" : "v2.9.4"\n}\n',
        encoding="utf-8",
    )
    const_path.write_text(
        const_content or 'VERSION = "v2.9.4"\nOTHER_VERSION = "v1.0.0"\n',
        encoding="utf-8",
    )
    return manifest_path, const_path


def test_update_release_versions_updates_only_release_declarations(tmp_path: Path) -> None:
    """Update both release declarations without changing unrelated versions.

    Args:
        tmp_path (Path):
            Temporary repository root.
    """
    manifest_path, const_path = _write_version_files(tmp_path)

    prepare_release.update_release_versions(tmp_path, "v3.0.1")

    assert json.loads(manifest_path.read_text(encoding="utf-8"))["version"] == "v3.0.1"
    assert const_path.read_text(encoding="utf-8") == (
        'VERSION = "v3.0.1"\nOTHER_VERSION = "v1.0.0"\n'
    )


def test_update_release_versions_does_not_partially_write(tmp_path: Path) -> None:
    """Leave both files unchanged when either declaration is missing.

    Args:
        tmp_path (Path):
            Temporary repository root.
    """
    manifest_path, const_path = _write_version_files(tmp_path, 'DOMAIN = "places"\n')
    original_manifest = manifest_path.read_text(encoding="utf-8")
    original_const = const_path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="Expected one version declaration"):
        prepare_release.update_release_versions(tmp_path, "v3.0.1")

    assert manifest_path.read_text(encoding="utf-8") == original_manifest
    assert const_path.read_text(encoding="utf-8") == original_const
