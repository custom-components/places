"""Tests for release version preparation."""

import importlib.util
import json
from pathlib import Path

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
