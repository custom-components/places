"""Behavior tests for Dependabot automatic-merge authorization."""

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / ".github" / "scripts" / "dependabot-auto-merge.mjs"
DEPENDABOT_SHA = "1" * 40
FIRST_BASE_SHA = "2" * 40
FIRST_UPDATE_SHA = "3" * 40
BASE_SHA = "4" * 40
HEAD_SHA = "5" * 40


def pull_request_event(action: str = "reopened") -> dict[str, Any]:
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
        "committer": {"login": "web-flow"},
        "commit": {"verification": {"verified": True}},
        "parents": [],
        "sha": sha,
    }


def update_branch_commit(previous_sha: str, base_sha: str, sha: str) -> dict[str, Any]:
    """Build a verified GitHub Update branch merge record.

    Args:
        previous_sha (str): First-parent SHA from the preceding Dependabot change.
        base_sha (str): Second-parent base SHA used by the web-flow merge.
        sha (str): Merge commit SHA.

    Returns:
        dict[str, Any]: GitHub pull-request commit record.
    """
    return {
        "author": {"login": "maintainer"},
        "committer": {"login": "web-flow"},
        "commit": {"verification": {"verified": True}},
        "parents": [{"sha": previous_sha}, {"sha": base_sha}],
        "sha": sha,
    }


def ancestry_proof(parent_sha: str, status: str = "ahead") -> dict[str, Any]:
    """Build compare output proving an update-merge base parent is current ancestry.

    Args:
        parent_sha (str): Merge commit second-parent SHA.
        status (str): GitHub compare status between parent and current base.

    Returns:
        dict[str, Any]: Minimized compare response consumed by the helper.
    """
    return {
        "ahead_by": 0 if status == "identical" else 1,
        "base_commit": parent_sha,
        "base_sha": BASE_SHA,
        "behind_by": 0,
        "head_commit": BASE_SHA,
        "merge_base_commit": parent_sha,
        "parent_sha": parent_sha,
        "status": status,
    }


def update_chain() -> list[dict[str, Any]]:
    """Build a Dependabot branch updated twice through GitHub's web flow.

    Returns:
        list[dict[str, Any]]: Ordered PR commits from GitHub's commits endpoint.
    """
    return [
        dependabot_commit(DEPENDABOT_SHA),
        update_branch_commit(DEPENDABOT_SHA, FIRST_BASE_SHA, FIRST_UPDATE_SHA),
        update_branch_commit(FIRST_UPDATE_SHA, BASE_SHA, HEAD_SHA),
    ]


def update_chain_proofs() -> list[dict[str, Any]]:
    """Return evidence that each update-merge base parent precedes the current base.

    Returns:
        list[dict[str, Any]]: Compare evidence in update-merge order.
    """
    return [ancestry_proof(FIRST_BASE_SHA), ancestry_proof(BASE_SHA, "identical")]


def authorize(
    tmp_path: Path,
    *,
    actor: str = "dependabot[bot]",
    ancestry_proofs: list[dict[str, Any]] | None = None,
    changed_files: list[str] | None = None,
    commits: list[dict[str, Any]] | None = None,
    event: dict[str, Any] | None = None,
    trusted_base_files: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute the helper against an isolated trusted-base directory.

    Args:
        tmp_path (Path): Isolated trusted-base checkout fixture.
        actor (str): Event actor.
        ancestry_proofs (list[dict[str, Any]] | None): Compare evidence for update merges.
        changed_files (list[str] | None): Pull-request paths.
        commits (list[dict[str, Any]] | None): Pull-request history from GitHub.
        event (dict[str, Any] | None): Pull-request event payload.
        trusted_base_files (list[str] | None): Files present in the trusted base.

    Returns:
        subprocess.CompletedProcess[str]: Completed Node authorizer process.
    """
    for path in trusted_base_files or ["uv.lock"]:
        trusted_base_file = tmp_path / path
        trusted_base_file.parent.mkdir(parents=True, exist_ok=True)
        trusted_base_file.touch()

    event_path = tmp_path / "event.json"
    changed_files_path = tmp_path / "changed-files"
    commits_path = tmp_path / "commits.json"
    ancestry_proofs_path = tmp_path / "ancestry-proofs.json"
    event_path.write_text(json.dumps(event or pull_request_event()), encoding="utf-8")
    changed_files_path.write_text("\n".join(changed_files or ["uv.lock"]), encoding="utf-8")
    commits_path.write_text(json.dumps([commits or [dependabot_commit()]]), encoding="utf-8")
    ancestry_proofs_path.write_text(json.dumps(ancestry_proofs or []), encoding="utf-8")
    node = shutil.which("node")
    assert node is not None
    return subprocess.run(  # noqa: S603 -- Test inputs execute the repository's trusted helper.
        [
            node,
            str(SCRIPT_PATH),
            str(event_path),
            str(changed_files_path),
            str(commits_path),
            str(ancestry_proofs_path),
        ],
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
    event = pull_request_event()
    event["pull_request"]["head"]["ref"] = "dependabot/github_actions/actions/checkout-7"
    result = authorize(
        tmp_path,
        changed_files=[".github/workflows/validate.yml", "action.yml"],
        commits=[dependabot_commit()],
        event=event,
        trusted_base_files=[".github/workflows/validate.yml", "action.yml"],
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


def test_rejects_npm_update_when_the_trusted_base_uses_uv(tmp_path: Path) -> None:
    """Reject an npm update when its required manifests are absent from base.

    Args:
        tmp_path (Path): Isolated trusted-base checkout fixture.
    """
    event = pull_request_event()
    event["pull_request"]["head"]["ref"] = "dependabot/npm_and_yarn/example-1.0.0"
    result = authorize(
        tmp_path,
        changed_files=["package-lock.json"],
        commits=[dependabot_commit()],
        event=event,
    )

    assert result.returncode != 0


def test_authorizes_reopened_verified_update_branch_history(tmp_path: Path) -> None:
    """Preserve auto-merge after GitHub updates a reopened Dependabot branch.

    Args:
        tmp_path (Path): Isolated trusted-base checkout fixture.
    """
    result = authorize(
        tmp_path,
        changed_files=["uv.lock"],
        ancestry_proofs=update_chain_proofs(),
        commits=update_chain(),
    )

    assert result.returncode == 0, result.stderr


def test_reopened_authorization_ignores_trigger_actor_and_action(tmp_path: Path) -> None:
    """Authorize history rather than mutable triggering actor or event action.

    Args:
        tmp_path (Path): Isolated trusted-base checkout fixture.
    """
    for actor, action in [
        ("dependabot[bot]", "opened"),
        ("maintainer", "synchronize"),
        ("any-user", "reopened"),
    ]:
        result = authorize(
            tmp_path,
            actor=actor,
            ancestry_proofs=update_chain_proofs(),
            changed_files=["uv.lock"],
            commits=update_chain(),
            event=pull_request_event(action),
        )
        assert result.returncode == 0, result.stderr


def test_rejects_absent_or_invalid_update_merge_ancestry_evidence(tmp_path: Path) -> None:
    """Fail closed unless each web-flow second parent is a current-base ancestor.

    Args:
        tmp_path (Path): Isolated trusted-base checkout fixture.
    """
    invalid_proofs = [
        [],
        [{}, ancestry_proof(BASE_SHA, "identical")],
        [ancestry_proof(FIRST_BASE_SHA), ancestry_proof("9" * 40)],
        [ancestry_proof(FIRST_BASE_SHA, "diverged"), ancestry_proof(BASE_SHA, "identical")],
        [
            {**ancestry_proof(FIRST_BASE_SHA), "head_commit": "8" * 40},
            ancestry_proof(BASE_SHA, "identical"),
        ],
    ]
    for proofs in invalid_proofs:
        result = authorize(
            tmp_path,
            ancestry_proofs=proofs,
            commits=update_chain(),
        )
        assert result.returncode != 0


def test_rejects_update_branch_history_with_a_non_github_merge(tmp_path: Path) -> None:
    """Reject an update branch chain whose merge lacks GitHub web-flow provenance.

    Args:
        tmp_path (Path): Isolated trusted-base checkout fixture.
    """
    commits = update_chain()
    commits[1]["committer"]["login"] = "maintainer"
    result = authorize(tmp_path, ancestry_proofs=update_chain_proofs(), commits=commits)

    assert result.returncode != 0


@pytest.mark.parametrize(
    ("history", "committer"),
    [("direct", None), ("direct", "maintainer"), ("update", None), ("update", "maintainer")],
)
def test_rejects_dependabot_roots_without_a_verified_web_flow_committer(
    tmp_path: Path, history: str, committer: str | None
) -> None:
    """Reject direct and update roots missing GitHub web-flow provenance.

    Args:
        tmp_path (Path): Isolated trusted-base checkout fixture.
        history (str): Whether to construct direct or GitHub Update branch history.
        committer (str | None): Invalid root committer, or None when omitted.
    """
    commits = [dependabot_commit()] if history == "direct" else update_chain()
    if committer is None:
        del commits[0]["committer"]
    else:
        commits[0]["committer"]["login"] = committer
    result = authorize(
        tmp_path,
        ancestry_proofs=[] if history == "direct" else update_chain_proofs(),
        commits=commits,
    )

    assert result.returncode != 0
