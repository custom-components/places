"""Tests for immutable release check verification and workflow contracts."""

from collections.abc import Sequence
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

SCRIPT_PATH = Path(__file__).parents[1] / ".github" / "scripts" / "verify_release_checks.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("verify_release_checks", SCRIPT_PATH)
assert SCRIPT_SPEC is not None
assert SCRIPT_SPEC.loader is not None
verify = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(verify)

WORKFLOW_ROOT = Path(__file__).parents[1] / ".github" / "workflows"
REPOSITORY = "owner/repository"
REF = "release-validation/v3.0.1-123-1"
SHA = "a" * 40


def test_dispatch_workflow_sends_ref_and_expected_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dispatch the named workflow for exactly the candidate ref and SHA.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture for replacing the API helper.
    """
    calls: list[tuple[list[str], int | None]] = []

    def fake_api(arguments: Sequence[str], expected_status: int | None = None) -> dict[str, Any]:
        calls.append((list(arguments), expected_status))
        return {"workflow_run_id": 42}

    monkeypatch.setattr(verify, "github_api", fake_api)

    assert verify.dispatch_workflow(REPOSITORY, "validate.yml", REF, SHA) == 42

    assert len(calls) == 1
    arguments, expected_status = calls[0]
    assert expected_status == 200
    assert arguments[arguments.index("--method") + 1] == "POST"
    assert f"repos/{REPOSITORY}/actions/workflows/validate.yml/dispatches" in arguments
    assert f"ref={REF}" in arguments
    assert f"inputs[expected_sha]={SHA}" in arguments
    assert "Accept: application/vnd.github+json" in arguments
    assert "X-GitHub-Api-Version: 2026-03-10" in arguments


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"workflow_run_id": None},
        {"workflow_run_id": 0},
        {"workflow_run_id": -1},
        {"workflow_run_id": True},
        {"workflow_run_id": "42"},
    ],
)
def test_dispatch_workflow_rejects_invalid_authoritative_run_id(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> None:
    """Fail closed when dispatch omits or corrupts the authoritative run ID.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture for replacing the API helper.
        response (dict[str, Any]): Invalid dispatch response fixture.
    """
    monkeypatch.setattr(
        verify,
        "github_api",
        lambda _arguments, expected_status=None: response,
    )

    with pytest.raises(verify.GitHubCommandError, match="valid workflow_run_id"):
        verify.dispatch_workflow(REPOSITORY, "validate.yml", REF, SHA)


@pytest.mark.parametrize(("status", "body"), [(204, ""), (200, ""), (200, "not-json")])
def test_dispatch_workflow_rejects_non_authoritative_http_responses(
    monkeypatch: pytest.MonkeyPatch, status: int, body: str
) -> None:
    """Reject 204, empty, and malformed dispatch API responses.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture for replacing CLI execution.
        status (int): HTTP status returned by the fixture.
        body (str): Response body returned by the fixture.
    """
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=f"HTTP/2 {status} status\n\n{body}",
            stderr="",
        ),
    )

    with pytest.raises((verify.GitHubCommandError, json.JSONDecodeError)):
        verify.dispatch_workflow(REPOSITORY, "validate.yml", REF, SHA)


def test_wait_for_workflow_returns_completed_run_id_after_pending_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return the exact completed run ID after tolerating an in-progress run.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture for replacing clock and checks.
    """
    responses = iter(
        [
            {"id": 7},
            {
                "id": 42,
                "workflow_id": 7,
                "event": "workflow_dispatch",
                "head_branch": REF,
                "head_sha": SHA,
                "status": "in_progress",
            },
            {
                "id": 42,
                "workflow_id": 7,
                "event": "workflow_dispatch",
                "head_branch": REF,
                "head_sha": SHA,
                "status": "completed",
                "conclusion": "success",
            },
        ]
    )
    sleeps: list[float] = []
    suite_calls: list[tuple[dict[str, Any], str]] = []
    job_calls: list[tuple[int, set[str]]] = []
    clock = iter([0.0, 0.1])

    monkeypatch.setattr(verify, "github_api", lambda _arguments: next(responses))
    monkeypatch.setattr(verify.time, "monotonic", lambda: next(clock, 1.0))
    monkeypatch.setattr(verify.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        verify,
        "verify_check_suite",
        lambda _repository, run, sha: suite_calls.append((run, sha)),
    )
    monkeypatch.setattr(
        verify,
        "verify_jobs",
        lambda _repository, run_id, checks: job_calls.append((run_id, checks)),
    )

    assert (
        verify.wait_for_workflow(
            REPOSITORY,
            "validate.yml",
            REF,
            SHA,
            {"HACS Validation"},
            deadline=1.0,
            expected_run_id=42,
        )
        == 42
    )
    assert sleeps == [10]
    assert suite_calls == [
        (
            {
                "id": 42,
                "workflow_id": 7,
                "event": "workflow_dispatch",
                "head_branch": REF,
                "head_sha": SHA,
                "status": "completed",
                "conclusion": "success",
            },
            SHA,
        )
    ]
    assert job_calls == [(42, {"HACS Validation"})]


@pytest.mark.parametrize("conclusion", ["failure", "cancelled"])
def test_wait_for_workflow_rejects_unsuccessful_conclusion(
    monkeypatch: pytest.MonkeyPatch, conclusion: str
) -> None:
    """Stop promotion for both failed and cancelled workflow conclusions.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture for replacing workflow polling.
        conclusion (str): Unsuccessful conclusion under test.
    """
    responses = iter(
        [
            {"id": 7},
            {
                "id": 42,
                "workflow_id": 7,
                "event": "workflow_dispatch",
                "head_branch": REF,
                "head_sha": SHA,
                "status": "completed",
                "conclusion": conclusion,
            },
        ]
    )
    monkeypatch.setattr(verify, "github_api", lambda _arguments: next(responses))
    monkeypatch.setattr(verify.time, "monotonic", lambda: 0.0)

    with pytest.raises(verify.GitHubCommandError, match=f"{conclusion!r}"):
        verify.wait_for_workflow(
            REPOSITORY,
            "validate.yml",
            REF,
            SHA,
            set(),
            deadline=1.0,
            expected_run_id=42,
        )


def test_wait_for_workflow_times_out_with_bounded_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop polling at the deadline when no matching run is returned.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture for replacing clock and polling.
    """
    sleeps: list[float] = []
    clock = iter([0.0, 1.0])
    responses = iter([{"id": 7}, verify.GitHubCommandError("404 Not Found")])

    def fake_api(_arguments: Sequence[str]) -> dict[str, Any]:
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(verify, "github_api", fake_api)
    monkeypatch.setattr(verify.time, "monotonic", lambda: next(clock, 1.0))
    monkeypatch.setattr(verify.time, "sleep", sleeps.append)

    with pytest.raises(verify.GitHubCommandError, match="Timed out"):
        verify.wait_for_workflow(
            REPOSITORY,
            "validate.yml",
            REF,
            SHA,
            set(),
            deadline=1.0,
            expected_run_id=42,
        )

    assert sleeps == [5]


def test_wait_for_workflow_rejects_mismatched_authoritative_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a response whose ID does not equal the authoritative dispatch ID.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture for replacing workflow polling.
    """
    responses = iter(
        [
            {"id": 7},
            {
                "id": 41,
                "workflow_id": 7,
                "event": "workflow_dispatch",
                "head_branch": REF,
                "head_sha": SHA,
                "status": "completed",
                "conclusion": "success",
            },
        ]
    )
    monkeypatch.setattr(verify, "github_api", lambda _arguments: next(responses))
    monkeypatch.setattr(verify.time, "monotonic", lambda: 0.0)

    with pytest.raises(verify.GitHubCommandError, match="does not match"):
        verify.wait_for_workflow(
            REPOSITORY,
            "validate.yml",
            REF,
            SHA,
            set(),
            deadline=1.0,
            expected_run_id=42,
        )


@pytest.mark.parametrize(
    ("suite", "message"),
    [
        ({"head_sha": "b" * 40, "app": {"slug": "github-actions"}}, "check suite"),
        ({"head_sha": SHA, "app": {"slug": "other-app"}}, "check suite"),
        ({"head_sha": SHA}, "check suite"),
    ],
)
def test_verify_check_suite_requires_github_actions_source_and_sha(
    monkeypatch: pytest.MonkeyPatch,
    suite: dict[str, Any],
    message: str,
) -> None:
    """Accept only a GitHub Actions check suite attached to the candidate SHA.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture for replacing the API helper.
        suite (dict[str, Any]): Check-suite response fixture.
        message (str): Expected validation-error fragment.
    """
    monkeypatch.setattr(verify, "github_api", lambda _arguments: suite)

    with pytest.raises(verify.GitHubCommandError, match=message):
        verify.verify_check_suite(REPOSITORY, {"check_suite_id": 99}, SHA)


@pytest.mark.parametrize(
    ("required_checks", "jobs", "failed_category", "failed_name"),
    [
        ({"missing"}, [], "missing", "missing"),
        (
            {"duplicate"},
            [
                {"name": "duplicate", "conclusion": "success"},
                {"name": "duplicate", "conclusion": "success"},
                {"name": "unrelated", "conclusion": "failure"},
            ],
            "duplicate",
            "duplicate",
        ),
        (
            {"failed"},
            [
                {"name": "failed", "conclusion": "failure"},
                {"name": "unrelated", "conclusion": "success"},
            ],
            "unsuccessful",
            "failed",
        ),
    ],
)
def test_verify_jobs_reports_mutually_exclusive_fail_closed_categories(
    monkeypatch: pytest.MonkeyPatch,
    required_checks: set[str],
    jobs: list[dict[str, Any]],
    failed_category: str,
    failed_name: str,
) -> None:
    """Report missing, duplicate, and single unsuccessful jobs separately.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture for replacing the API helper.
        required_checks (set[str]): Required job names for the deterministic fixture.
        jobs (list[dict[str, Any]]): Workflow jobs returned by the API fixture.
        failed_category (str): Diagnostic category expected for the fixture.
        failed_name (str): Required job expected in that category.
    """
    monkeypatch.setattr(
        verify,
        "github_api",
        lambda _arguments: {"total_count": len(jobs), "jobs": jobs},
    )

    with pytest.raises(verify.GitHubCommandError) as error:
        verify.verify_jobs(REPOSITORY, 42, required_checks)

    message = str(error.value)
    assert f"{failed_category}=[{failed_name!r}]" in message
    for category in {"missing", "duplicate", "unsuccessful"} - {failed_category}:
        assert f"{category}=[]" in message


def test_parse_required_checks_groups_exact_names_and_rejects_malformed_values() -> None:
    """Group checks by workflow while retaining exact job-name boundaries."""
    checks = verify.parse_required_checks(
        [
            "pytest_coverage.yml::pytest and coverage report",
            "validate.yml::HACS Validation",
            "validate.yml::Hassfest Validation",
            "prek-autofix-review.yml::review",
            "pytest_coverage.yml::pytest and coverage report",
        ]
    )

    assert list(checks) == [
        "pytest_coverage.yml",
        "validate.yml",
        "prek-autofix-review.yml",
    ]
    assert checks == {
        "pytest_coverage.yml": {"pytest and coverage report"},
        "validate.yml": {"HACS Validation", "Hassfest Validation"},
        "prek-autofix-review.yml": {"review"},
    }

    with pytest.raises(ValueError, match="workflow::exact job name"):
        verify.parse_required_checks(["validate.yml:HACS Validation"])


def test_main_dispatches_workflows_in_required_check_first_seen_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the required-check manifest as the sole ordered workflow input.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture for replacing dispatch and polling helpers.
    """
    dispatches: list[str] = []
    waits: list[tuple[str, set[str], int]] = []

    def fake_dispatch(_repository: str, workflow: str, _ref: str, _sha: str) -> int:
        dispatches.append(workflow)
        return len(dispatches)

    def fake_wait(
        _repository: str,
        workflow: str,
        _ref: str,
        _sha: str,
        checks: set[str],
        _deadline: float,
        run_id: int,
    ) -> int:
        waits.append((workflow, checks, run_id))
        return run_id

    monkeypatch.setattr(verify, "dispatch_workflow", fake_dispatch)
    monkeypatch.setattr(verify, "wait_for_workflow", fake_wait)
    monkeypatch.setattr(verify.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(
        verify.sys,
        "argv",
        [
            "verify_release_checks.py",
            "--repository",
            REPOSITORY,
            "--ref",
            REF,
            "--sha",
            SHA,
            "--required-check",
            "pytest_coverage.yml::pytest and coverage report",
            "--required-check",
            "validate.yml::HACS Validation",
            "--required-check",
            "validate.yml::Hassfest Validation",
        ],
    )

    assert verify.main() == 0
    assert dispatches == ["pytest_coverage.yml", "validate.yml"]
    assert waits == [
        ("pytest_coverage.yml", {"pytest and coverage report"}, 1),
        ("validate.yml", {"HACS Validation", "Hassfest Validation"}, 2),
    ]


def test_github_api_fails_closed_for_unavailable_or_malformed_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject missing CLI, command errors, non-object JSON, and malformed JSON.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture for replacing CLI discovery and calls.
    """
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(verify.GitHubCommandError, match="unavailable"):
        verify.github_api([])

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="API failed"),
    )
    with pytest.raises(verify.GitHubCommandError, match="API failed"):
        verify.github_api([])

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="[]", stderr=""),
    )
    with pytest.raises(verify.GitHubCommandError, match="not an object"):
        verify.github_api([])

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="{", stderr=""),
    )
    with pytest.raises(json.JSONDecodeError):
        verify.github_api([])


def test_github_api_uses_a_bounded_request_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bound each GitHub API request so network stalls cannot defeat polling bounds.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture for replacing CLI discovery and calls.
    """
    calls: list[dict[str, Any]] = []

    def fake_run(*_args: object, **kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert verify.github_api(["repos/example/repo"]) == {}
    assert len(calls) == 1
    assert calls[0]["timeout"] == 30


def _load_workflow(name: str) -> dict[str, Any]:
    """Load one workflow with normalized trigger keys for semantic checks.

    Args:
        name (str): Workflow filename.

    Returns:
        dict[str, Any]: Parsed workflow document.
    """
    document = yaml.safe_load((WORKFLOW_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    if True in document:
        document["on"] = document.pop(True)
    return document


def _workflow_events(document: dict[str, Any]) -> dict[str, Any]:
    """Return the parsed workflow trigger map.

    Args:
        document (dict[str, Any]): Parsed workflow document.

    Returns:
        dict[str, Any]: Workflow event configuration.
    """
    events = document["on"]
    assert isinstance(events, dict)
    return events


def _named_steps(document: dict[str, Any], job_id: str) -> dict[str, dict[str, Any]]:
    """Index named steps for stable semantic assertions.

    Args:
        document (dict[str, Any]): Parsed workflow document.
        job_id (str): Workflow job identifier.

    Returns:
        dict[str, dict[str, Any]]: Named steps in the selected job.
    """
    job = document["jobs"][job_id]
    assert isinstance(job, dict)
    steps = job["steps"]
    assert isinstance(steps, list)
    return {step["name"]: step for step in steps if isinstance(step, dict) and "name" in step}


def test_release_workflow_has_published_trigger_and_stable_prerelease_split() -> None:
    """Keep release promotion event-driven with distinct stable and prerelease paths."""
    document = _load_workflow("release.yml")
    events = _workflow_events(document)
    assert events == {"release": {"types": ["published"]}}

    steps = _named_steps(document, "release")
    assert steps["Build prerelease archive without mutating refs"]["if"] == (
        "github.event.release.prerelease"
    )
    assert steps["Create deterministic stable release commit B"]["if"] == (
        "github.event.release.prerelease == false"
    )
    assert steps["Atomically advance target and guarded release tag"]["if"] == (
        "github.event.release.prerelease == false && steps.base.outputs.resume != 'true'"
    )

    dispatch_run = steps["Dispatch and verify immutable release gates"]["run"]
    assert "--workflow" not in dispatch_run
    assert {
        line.strip().removeprefix("--required-check '").removesuffix("' \\").removesuffix("'")
        for line in dispatch_run.splitlines()
        if line.strip().startswith("--required-check '")
    } == {
        "validate.yml::HACS Validation",
        "validate.yml::Hassfest Validation",
        "pytest_coverage.yml::pytest and coverage report",
        "prek-autofix-review.yml::review",
    }


def test_release_workflow_uses_guarded_atomic_promotion_and_resumable_cleanup() -> None:
    """Require guarded branch/tag promotion, explicit resume state, and cleanup on success."""
    document = _load_workflow("release.yml")
    steps = _named_steps(document, "release")
    promotion = steps["Atomically advance target and guarded release tag"]
    promotion_run = promotion["run"]
    assert "push --atomic" in promotion_run
    assert "refs/tags/$RELEASE_TAG:$ORIGINAL_TAG_OID" in promotion_run
    assert "refs/heads/$RELEASE_TARGET:$TARGET_SHA" in promotion_run
    assert '[[ "$(git rev-parse HEAD^)" == "$TARGET_SHA" ]]' in promotion_run
    assert 'git push origin "refs/tags/$RELEASE_TAG"' not in promotion_run
    assert '[[ "$(git rev-parse "refs/remotes/origin/$RELEASE_TARGET")" == "$TARGET_SHA" ]]' in (
        promotion_run
    )

    candidate_run = steps["Create deterministic stable release commit B"]["run"]
    assert 'if [[ "$RESUME" == true ]]' in candidate_run
    assert 'echo "sha=$RESUME_SHA"' in candidate_run
    cleanup = steps["Delete validated temporary branch"]
    assert cleanup["if"] == "github.event.release.prerelease == false && success()"
    assert 'push origin --delete "$TEMP_REF"' in cleanup["run"]


def test_release_workflow_trusts_only_default_branch_and_scopes_tokens() -> None:
    """Require default-target validation, credential-free checkout, and step-scoped tokens."""
    document = _load_workflow("release.yml")
    job = document["jobs"]["release"]
    assert job["permissions"] == {
        "actions": "write",
        "checks": "read",
        "contents": "write",
        "statuses": "read",
    }
    steps = _named_steps(document, "release")
    target = steps["Require the default-branch release target"]
    assert '"$RELEASE_TARGET" != "$DEFAULT_BRANCH"' in target["run"]
    assert target["env"] == {
        "DEFAULT_BRANCH": "${{ github.event.repository.default_branch }}",
        "RELEASE_TARGET": "${{ github.event.release.target_commitish }}",
    }
    checkout = steps["Checkout trusted default-branch workflow revision"]
    assert checkout["with"]["ref"] == "${{ github.event.repository.default_branch }}"
    assert checkout["with"]["persist-credentials"] is False

    token_steps = {
        name: step
        for name, step in steps.items()
        if name
        in {
            "Build prerelease archive without mutating refs",
            "Publish B to an isolated validation branch",
            "Dispatch and verify immutable release gates",
            "Atomically advance target and guarded release tag",
            "Verify release identity and upload B archive",
            "Delete validated temporary branch",
        }
    }
    for step in token_steps.values():
        assert step["env"]["GH_TOKEN"] == "${{ github.token }}"


def test_release_workflow_uses_scoped_github_cli_credentials_for_git_pushes() -> None:
    """Authenticate release pushes without persisting checkout credentials."""
    document = _load_workflow("release.yml")
    steps = _named_steps(document, "release")
    push_step_names = (
        "Publish B to an isolated validation branch",
        "Atomically advance target and guarded release tag",
        "Delete validated temporary branch",
    )

    for step_name in push_step_names:
        step = steps[step_name]
        assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
        assert "extraheader" not in step["run"].lower()
        assert "gh auth setup-git --hostname github.com" in step["run"]


@pytest.mark.parametrize(
    ("workflow_name", "guarded_jobs"),
    [
        ("validate.yml", ["ha_validation", "hacs_validation"]),
        ("pytest_coverage.yml", ["tests"]),
        ("prek-autofix-review.yml", ["review"]),
    ],
)
def test_release_dispatch_guards_require_lowercase_sha_and_match_workflow_sha(
    workflow_name: str, guarded_jobs: list[str]
) -> None:
    """Validate the exact lowercase 40-hex guard used for release dispatches.

    Args:
        workflow_name (str): Workflow filename under test.
        guarded_jobs (list[str]): Jobs that run release-dispatch guards.
    """
    document = _load_workflow(workflow_name)
    for job_id in guarded_jobs:
        steps = _named_steps(document, job_id)
        guard = steps["Require expected release commit"]
        assert guard["run"] == (
            '[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]\ntest "$WORKFLOW_SHA" = "$EXPECTED_SHA"\n'
        )
        assert guard["env"] == {
            "EXPECTED_SHA": "${{ inputs.expected_sha }}",
            "WORKFLOW_SHA": "${{ github.sha }}",
        }


def test_dispatch_pytest_job_is_read_only_and_preserves_required_check_name() -> None:
    """Run release-dispatched pytest with read-only contents and the required job name."""
    document = _load_workflow("pytest_coverage.yml")
    pytest_job = document["jobs"]["tests"]
    assert pytest_job["name"] == "pytest and coverage report"
    assert "workflow_dispatch" not in pytest_job["if"]
    assert pytest_job["permissions"] == {"contents": "read"}
    assert all(
        not (
            isinstance(step, dict)
            and step.get("uses") == "py-cov-action/python-coverage-comment-action@v3"
        )
        for step in pytest_job["steps"]
    )
    checkout = next(
        step
        for step in pytest_job["steps"]
        if isinstance(step, dict) and step.get("uses") == "actions/checkout@v7"
    )
    assert checkout["with"] == {
        "ref": "${{ inputs.expected_sha || github.sha }}",
        "persist-credentials": False,
    }


@pytest.mark.parametrize(
    ("workflow_name", "has_push_trigger"),
    [("validate.yml", True), ("pytest_coverage.yml", True), ("prek-autofix-review.yml", False)],
)
def test_release_gate_workflows_retain_normal_triggers_and_expected_sha_dispatch(
    workflow_name: str, has_push_trigger: bool
) -> None:
    """Keep PR/push validation while allowing release dispatches to pin one SHA.

    Args:
        workflow_name (str): Workflow filename under test.
        has_push_trigger (bool): Whether the workflow historically runs on main pushes.
    """
    document = _load_workflow(workflow_name)
    events = _workflow_events(document)
    assert "pull_request" in events
    if has_push_trigger:
        assert events["push"]["branches"] == ["main"]
    else:
        assert "push" not in events
    dispatch = events["workflow_dispatch"]
    assert dispatch["inputs"]["expected_sha"]["required"] is True

    jobs = document["jobs"]
    assert isinstance(jobs, dict)
    guarded_jobs = {
        "validate.yml": set(jobs),
        "pytest_coverage.yml": {"tests"},
        "prek-autofix-review.yml": {"review"},
    }[workflow_name]
    for job_id, job in jobs.items():
        assert isinstance(job, dict)
        steps = job["steps"]
        has_guard = any(
            isinstance(step, dict) and step.get("name") == "Require expected release commit"
            for step in steps
        )
        assert has_guard is (job_id in guarded_jobs)


def test_release_gate_workflow_checkouts_pin_dispatch_sha_without_pr_credentials() -> None:
    """Ensure release-dispatched validation checks out the expected SHA credential-free."""
    for workflow_name in ["validate.yml", "pytest_coverage.yml", "prek-autofix-review.yml"]:
        document = _load_workflow(workflow_name)
        jobs = document["jobs"]
        assert isinstance(jobs, dict)
        for job_id, job in jobs.items():
            assert isinstance(job, dict)
            checkout = next(
                step
                for step in job["steps"]
                if isinstance(step, dict) and step.get("uses") == "actions/checkout@v7"
            )
            if workflow_name == "pytest_coverage.yml" and job_id == "tests":
                assert "inputs.expected_sha || github.sha" in checkout["with"]["ref"]
            elif workflow_name == "pytest_coverage.yml":
                assert checkout["with"]["ref"] == "${{ github.sha }}"
            else:
                assert "inputs.expected_sha || github.sha" in checkout["with"]["ref"]
            if workflow_name == "pytest_coverage.yml" and job_id == "tests":
                assert checkout["with"]["persist-credentials"] is False
            elif workflow_name == "pytest_coverage.yml":
                assert checkout["with"]["persist-credentials"] == (
                    "${{ github.event_name == 'push' }}"
                )
            else:
                assert checkout["with"]["persist-credentials"] is False
