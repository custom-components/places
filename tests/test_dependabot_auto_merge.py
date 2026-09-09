"""Behavior tests for Dependabot automatic-merge authorization."""

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest
import yaml

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


def _load_workflow(path: str) -> dict[str, Any]:
    """Load a workflow for behavior-level contracts.

    Args:
        path (str): Repository-relative workflow path.

    Returns:
        dict[str, Any]: Parsed workflow document.
    """
    document = yaml.safe_load((SCRIPT_PATH.parents[1] / "workflows" / path).read_text())
    assert isinstance(document, dict)
    return document


def _authorization_step(job: dict[str, Any]) -> dict[str, Any]:
    """Find the step that invokes the trusted Dependabot authorizer.

    Args:
        job (dict[str, Any]): Parsed workflow job.

    Returns:
        dict[str, Any]: Authorization step.
    """
    return next(
        step
        for step in job["steps"]
        if isinstance(step, dict) and "dependabot-auto-merge.mjs" in step.get("run", "")
    )


def _uses_major_action(step: dict[str, Any], action: str) -> bool:
    """Identify an action by its stable owner/name and major-release prefix.

    Args:
        step (dict[str, Any]): Parsed workflow step.
        action (str): Action owner/name without a release suffix.

    Returns:
        bool: Whether the step uses the action on a major release line.
    """
    return str(step.get("uses", "")).startswith(f"{action}@v")


def _workflow_job_with_authorizer(document: dict[str, Any]) -> dict[str, Any]:
    """Find the job that invokes the Dependabot authorization helper.

    Args:
        document (dict[str, Any]): Parsed workflow document.

    Returns:
        dict[str, Any]: Job containing the authorizer invocation.
    """
    return next(
        job
        for job in document["jobs"].values()
        if any(
            isinstance(step, dict) and "dependabot-auto-merge.mjs" in step.get("run", "")
            for step in job["steps"]
        )
    )


def _coverage_step(job: dict[str, Any], activity: str) -> dict[str, Any]:
    """Find a coverage action by its explicit behavior rather than its step ID.

    Args:
        job (dict[str, Any]): Parsed workflow job.
        activity (str): Coverage action activity.

    Returns:
        dict[str, Any]: Coverage action step with the requested activity.
    """
    return next(
        step
        for step in job["steps"]
        if isinstance(step, dict)
        and _uses_major_action(step, "py-cov-action/python-coverage-comment-action")
        and step.get("with", {}).get("ACTIVITY") == activity
    )


def test_auto_merge_authorizes_with_trusted_history_and_compare_evidence() -> None:
    """Require trusted-base, read-only authorization in dedicated auto-merge CI."""
    auto_merge = _load_workflow("dependabot-auto-merge.yml")
    auto_authorizer = _workflow_job_with_authorizer(auto_merge)
    auto_authorizer_id = next(
        job_id for job_id, job in auto_merge["jobs"].items() if job is auto_authorizer
    )
    assert auto_authorizer["permissions"]["contents"] == "read"
    assert auto_authorizer["permissions"]["pull-requests"] == "read"
    assert all(
        permission in {"contents", "pull-requests"} for permission in auto_authorizer["permissions"]
    )
    authorization = _authorization_step(auto_authorizer)
    authorization_index = auto_authorizer["steps"].index(authorization)
    trusted_checkout = next(
        step
        for step in auto_authorizer["steps"][:authorization_index]
        if isinstance(step, dict)
        and _uses_major_action(step, "actions/checkout")
        and step.get("with", {}).get("ref") == "${{ github.event.pull_request.base.sha }}"
    )
    assert trusted_checkout["with"]["persist-credentials"] is False
    assert all(
        not _uses_major_action(step, "actions/checkout")
        or step.get("with", {}).get("ref") == "${{ github.event.pull_request.base.sha }}"
        for step in auto_authorizer["steps"][:authorization_index]
        if isinstance(step, dict)
    )
    assert "compare/" in authorization["run"]
    assert "dependabot-ancestry-proofs.json" in authorization["run"]
    assert authorization["env"]["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert 'base_sha="${BASE_SHA}"' in authorization["run"]
    assert "pull_request.user.login == 'dependabot[bot]'" in auto_authorizer["if"]
    assert "repository.fork" not in auto_authorizer["if"]
    enable = next(
        job
        for job in auto_merge["jobs"].values()
        if any("gh pr merge --auto" in str(step.get("run", "")) for step in job["steps"])
    )
    assert enable["needs"] == auto_authorizer_id
    assert "if" not in enable
    cleanup = next(
        job
        for job in auto_merge["jobs"].values()
        if any("gh pr merge --disable-auto" in str(step.get("run", "")) for step in job["steps"])
    )
    assert cleanup["needs"] == auto_authorizer_id
    for term in [
        "failure()",
        "!cancelled()",
        "repository.fork == false",
        "pull_request.user.login == 'dependabot[bot]'",
        "pull_request.head.repo.full_name == github.repository",
        "pull_request.base.ref == github.event.repository.default_branch",
    ]:
        assert term in cleanup["if"]


def test_coverage_generation_and_trusted_publishing_have_separate_capabilities() -> None:
    """Keep source coverage read-only and writers scoped to their trusted run types."""
    pytest_check = _load_workflow("pytest_check.yml")
    post_coverage = _load_workflow("pytest_post_coverage.yml")
    assert "concurrency" not in post_coverage
    source = next(
        job
        for job in pytest_check["jobs"].values()
        if any(
            isinstance(step, dict)
            and _uses_major_action(step, "py-cov-action/python-coverage-comment-action")
            and step.get("with", {}).get("ACTIVITY") == "process_pr"
            for step in job["steps"]
        )
    )
    assert "write" not in source["permissions"].values()
    coverage = _coverage_step(source, "process_pr")
    coverage_condition = str(coverage["if"])
    assert "github.event_name == 'pull_request'" in coverage_condition
    assert "pull_request.user.login != 'prek-autoupdate-bot'" in coverage_condition
    assert "dependabot[bot]" not in coverage_condition
    stored_coverage = next(
        step
        for step in source["steps"]
        if isinstance(step, dict)
        and _uses_major_action(step, "actions/upload-artifact")
        and step.get("with", {}).get("name") == "python-coverage-data"
    )
    assert "github.event_name == 'push'" in stored_coverage["if"]
    assert stored_coverage["with"]["path"] == ".coverage"
    assert stored_coverage["with"]["include-hidden-files"] is True

    comment_writer = next(
        job
        for job in post_coverage["jobs"].values()
        if any(
            isinstance(step, dict)
            and _uses_major_action(step, "py-cov-action/python-coverage-comment-action")
            and step.get("with", {}).get("ACTIVITY") == "post_comment"
            for step in job["steps"]
        )
    )
    assert comment_writer["permissions"]["pull-requests"] == "write"
    assert comment_writer["permissions"]["actions"] == "read"
    assert comment_writer["permissions"]["contents"] == "read"
    assert all(
        permission in {"actions", "contents", "pull-requests"}
        for permission in comment_writer["permissions"]
    )
    assert "concurrency" not in comment_writer
    assert all(
        not (isinstance(step, dict) and _uses_major_action(step, "actions/checkout"))
        for step in comment_writer["steps"]
    )
    publisher = next(
        job
        for job in post_coverage["jobs"].values()
        if any(
            isinstance(step, dict)
            and _uses_major_action(step, "py-cov-action/python-coverage-comment-action")
            and step.get("with", {}).get("ACTIVITY") == "save_coverage_data_files"
            for step in job["steps"]
        )
    )
    publisher_permissions = publisher["permissions"]
    assert publisher_permissions["actions"] == "read"
    assert publisher_permissions["contents"] == "write"
    assert all(permission in {"actions", "contents"} for permission in publisher_permissions)
    for term in [
        "workflow_run.event == 'push'",
        "workflow_run.conclusion == 'success'",
        "workflow_run.head_branch == github.event.repository.default_branch",
        "workflow_run.head_repository.full_name == github.repository",
    ]:
        assert term in publisher["if"]
    assert publisher["concurrency"]["cancel-in-progress"] is True
    assert "github.event.repository.default_branch" in publisher["concurrency"]["group"]
    checkout = next(
        step
        for step in publisher["steps"]
        if isinstance(step, dict) and _uses_major_action(step, "actions/checkout")
    )
    checkout_with = checkout["with"]
    assert checkout_with["persist-credentials"] is False
    assert checkout_with["ref"] == "${{ github.event.repository.default_branch }}"
    verification = next(
        step
        for step in publisher["steps"]
        if isinstance(step, dict) and "git rev-parse HEAD" in step.get("run", "")
    )
    assert verification["env"]["EXPECTED_SHA"] == "${{ github.event.workflow_run.head_sha }}"
    download = next(
        step
        for step in publisher["steps"]
        if isinstance(step, dict) and _uses_major_action(step, "actions/download-artifact")
    )
    download_with = download["with"]
    assert download_with["github-token"] == "${{ secrets.GITHUB_TOKEN }}"
    assert download_with["name"] == "python-coverage-data"
    assert download_with["path"] == "."
    assert download_with["run-id"] == "${{ github.event.workflow_run.id }}"
    publish = _coverage_step(publisher, "save_coverage_data_files")
    assert publisher["steps"].index(checkout) < publisher["steps"].index(verification)
    assert publisher["steps"].index(verification) < publisher["steps"].index(download)
    assert publisher["steps"].index(download) < publisher["steps"].index(publish)
