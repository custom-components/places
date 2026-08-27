# Releasing Places

<!-- cspell:ignore Hassfest -->

## Stable release

1. Merge the release-ready changes into the default branch. Publish a GitHub
   Release with the intended unused, numeric, `v`-prefixed tag, targeting that
   branch. The tag and target must initially resolve to the same commit.
   Publishing the release starts the stable-release workflow.
2. The workflow creates a temporary pre-validation branch containing the
   deterministic release commit. It dispatches the required workflows for that
   exact commit SHA and waits a bounded time for all of these checks to pass:

   - `HACS Validation`
   - `Hassfest Validation`
   - `pytest and coverage report`
   - `review`

   The gates receive the candidate as an `expected_sha` input. The workflow
   verifies their exact branch and SHA, GitHub Actions check suite, and one
   successful job with each listed name; it waits at most 30 minutes. Coverage
   publishing is a separate non-gating job and is not dispatched for release
   validation.

3. After those checks pass, the workflow updates the release commit on the
   protected default branch and its tag, then builds `places.zip` from the
   tag's `custom_components/places` tree. The final tag and archive therefore
   identify the same release source.
4. Wait for the release workflow to finish, then verify the published GitHub
   release has the expected tag and `places.zip` asset. The temporary
   pre-validation branch is removed after a successful stable release.

No personal access token, GitHub App token, or deploy key is required. The
workflow uses `GITHUB_TOKEN`; branch protection and the repository ruleset
remain active throughout the release. Tokens are provided only to the steps
that dispatch checks, update refs, upload the asset, or delete the temporary
branch.

## Prereleases

Publish a GitHub Release with an explicit unused prerelease tag. A prerelease
follows the existing tag and GitHub-release path; it does not mutate the
default branch. Automatic version changes are stable-only.

## Failure handling and safe retries

The workflow stops before promotion when validation fails, a required check
does not complete before its wait limit, or `main` changes after the
pre-validation SHA was selected. Start a new release from current `main`; do
not reuse a stale validation result. A failed stable run retains its temporary
validation branch for diagnosis. After recording the failure, delete that
branch with normal repository access before retrying. First verify the exact
branch name and that its SHA is the failed run's candidate SHA:

```sh
git fetch origin refs/heads/<temporary-ref>
git show -s --format='%H%n%s%n%P' FETCH_HEAD
git push origin --delete <temporary-ref>
```

Delete it only after the shown SHA and release-commit details match
the failed run; never use a broad branch pattern or force deletion.

The workflow attempts an atomic branch-and-tag update. It fails closed if the
remote rejects or does not support that update; it does not promise that a
partial remote update is impossible. Inspect remote state before retrying:

```sh
git fetch --tags origin
git log -1 --decorate origin/main
git show --no-patch --decorate <tag>
git show <tag>:custom_components/places/manifest.json
git show <tag>:custom_components/places/const.py
```

- If `main` moved or the tag and `main` do not name the same release commit,
  stop. Do not force-push or move the tag; treat a tag/main split as an
  incident and resolve it before creating a new release from current `main`.
- If validation failed, fix the cause and publish a new release. Do not push
  the pre-validation commit directly to bypass required checks.
- If the branch/tag update was rejected, inspect both remote refs rather than
  assuming they are unchanged, then refresh from `main`. Escalate a confirmed
  partial update rather than attempting to repair it by force.
- If the tag and default branch are correct but the GitHub release or asset
  upload failed, preserve the tag and rerun the failed workflow. It can resume
  only when the tag and `main` still name the same single-parent `Release
  <tag>` commit and both version files match the tag; do not create a second
  release or force-move the tag.

For any recovery upload, first rebuild and test the archive from the existing
tag so the asset remains tied to the release source:

```sh
git archive --format=zip --output=places.zip <tag>:custom_components/places
unzip -t places.zip
```
