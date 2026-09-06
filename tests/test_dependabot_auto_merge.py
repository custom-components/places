"""Behavior tests for Dependabot automatic-merge authorization."""

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

SCRIPT_PATH = Path(__file__).parents[1] / ".github" / "scripts" / "dependabot-auto-merge.mjs"
DEPENDABOT_SHA = "1" * 40
BASE_SHA = "2" * 40
HEAD_SHA = "3" * 40


def pull_request_event(action: str = "opened") -> dict[str, Any]:
    """Build a same-repository Dependabot event with a current default base.

    Args:
        action (str): Pull-request event action.

    Returns:
        dict[str, Any]: Event data accepted before history validation.
    """
    return {
        "action": action,
        "repository": {
            "default_branch": "main",
            "fork": False,
            "full_name": "owner/places",
        },
        "pull_request": {
            "base": {"ref": "main", "sha": BASE_SHA},
            "head": {
                "ref": "dependabot/uv/example-1.0.0",
                "repo": {"full_name": "owner/places"},
                "sha": HEAD_SHA,
            },
            "user": {"login": "dependabot[bot]"},
        },
    }


def dependabot_commit(sha: str = HEAD_SHA) -> dict[str, Any]:
    """Build a verified Dependabot commit record.

    Args:
        sha (str): Commit SHA to assign to the record.

    Returns:
        dict[str, Any]: GitHub pull-request commit record.
    """
    return {
        "author": {"login": "dependabot[bot]"},
        "commit": {"verification": {"verified": True}},
        "parents": [],
        "sha": sha,
    }


def update_branch_commit(previous_sha: str) -> dict[str, Any]:
    """Build a verified GitHub Update branch merge record.

    Args:
        previous_sha (str): First-parent SHA from the preceding Dependabot change.

    Returns:
        dict[str, Any]: GitHub pull-request commit record.
    """
    return {
        "committer": {"login": "web-flow"},
        "commit": {"verification": {"verified": True}},
        "parents": [{"sha": previous_sha}, {"sha": BASE_SHA}],
        "sha": HEAD_SHA,
    }


def authorize(
    tmp_path: Path,
    *,
    actor: str = "dependabot[bot]",
    changed_files: list[str],
    commits: list[dict[str, Any]],
    event: dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    """Execute the helper against an isolated trusted-base directory.

    Args:
        tmp_path (Path): Isolated trusted-base checkout fixture.
        actor (str): Event actor.
        changed_files (list[str]): Pull-request paths.
        commits (list[dict[str, Any]]): Pull-request history from GitHub.
        event (dict[str, Any]): Pull-request event payload.

    Returns:
        subprocess.CompletedProcess[str]: Completed Node authorizer process.
    """
    event_path = tmp_path / "event.json"
    changed_files_path = tmp_path / "changed-files"
    commits_path = tmp_path / "commits.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    changed_files_path.write_text("\n".join(changed_files), encoding="utf-8")
    commits_path.write_text(json.dumps([commits]), encoding="utf-8")
    node = shutil.which("node")
    assert node is not None
    return subprocess.run(  # noqa: S603 -- Test inputs execute the repository's trusted helper.
        [node, str(SCRIPT_PATH), str(event_path), str(changed_files_path), str(commits_path)],
        check=False,
        cwd=tmp_path,
        env={**os.environ, "GITHUB_ACTOR": actor},
        capture_output=True,
        text=True,
    )


def test_authorizes_direct_uv_lock_update(tmp_path: Path) -> None:
    """Authorize a verified direct Dependabot update that changes only uv.lock.

    Args:
        tmp_path (Path): Isolated trusted-base checkout fixture.
    """
    result = authorize(
        tmp_path,
        changed_files=["uv.lock"],
        commits=[dependabot_commit()],
        event=pull_request_event(),
    )

    assert result.returncode == 0, result.stderr


def test_rejects_uv_update_that_changes_project_metadata(tmp_path: Path) -> None:
    """Reject a uv update that includes a file outside its lockfile contract.

    Args:
        tmp_path (Path): Isolated trusted-base checkout fixture.
    """
    result = authorize(
        tmp_path,
        changed_files=["pyproject.toml", "uv.lock"],
        commits=[dependabot_commit()],
        event=pull_request_event(),
    )

    assert result.returncode != 0


def test_authorizes_existing_trusted_action_files(tmp_path: Path) -> None:
    """Authorize existing Actions files from the trusted base only.

    Args:
        tmp_path (Path): Isolated trusted-base checkout fixture.
    """
    workflow = tmp_path / ".github" / "workflows" / "validate.yml"
    workflow.parent.mkdir(parents=True)
    workflow.touch()
    (tmp_path / "action.yml").touch()
    event = pull_request_event()
    event["pull_request"]["head"]["ref"] = "dependabot/github_actions/actions/checkout-7"
    result = authorize(
        tmp_path,
        changed_files=[".github/workflows/validate.yml", "action.yml"],
        commits=[dependabot_commit()],
        event=event,
    )

    assert result.returncode == 0, result.stderr


def test_rejects_action_path_absent_from_trusted_base(tmp_path: Path) -> None:
    """Reject an Actions update that could introduce a new executable workflow.

    Args:
        tmp_path (Path): Isolated trusted-base checkout fixture.
    """
    event = pull_request_event()
    event["pull_request"]["head"]["ref"] = "dependabot/github_actions/actions/checkout-7"
    result = authorize(
        tmp_path,
        changed_files=[".github/workflows/new-workflow.yml"],
        commits=[dependabot_commit()],
        event=event,
    )

    assert result.returncode != 0


def test_authorizes_verified_update_branch_merge(tmp_path: Path) -> None:
    """Preserve auto-merge after GitHub updates a trusted Dependabot branch.

    Args:
        tmp_path (Path): Isolated trusted-base checkout fixture.
    """
    result = authorize(
        tmp_path,
        actor="maintainer",
        changed_files=["uv.lock"],
        commits=[dependabot_commit(DEPENDABOT_SHA), update_branch_commit(DEPENDABOT_SHA)],
        event=pull_request_event("synchronize"),
    )

    assert result.returncode == 0, result.stderr
