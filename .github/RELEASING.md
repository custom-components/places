# Releasing Places

<!-- cspell:ignore Hassfest -->

## Stable releases

1. Merge release-ready changes into the default branch, then publish a GitHub
   Release with an unused numeric `v`-prefixed tag targeting that branch. The
   new tag and branch must initially name the same commit.
2. The workflow creates one deterministic commit changing only `manifest.json`
   and `const.py`, then builds and validates `places.zip` from that candidate.
3. It publishes the candidate to a unique validation branch and dispatches its
   exact SHA to `HACS Validation`, `Hassfest Validation`, `pytest check and
   post coverage`, and `review`. After each exact job succeeds, the workflow
   atomically advances the default branch and annotated tag, rechecks them, and
   uploads the already verified candidate archive.

No personal access token, GitHub App token, or deploy key is required. The
workflow uses `GITHUB_TOKEN`; branch protection and repository rules remain
active throughout promotion.

## Prereleases

Publish an explicit unused prerelease tag whose `manifest.json` and `const.py`
versions already match. The workflow only builds and uploads `places.zip`; it
does not create a commit or move a ref. Before upload, the default branch and
tag must still resolve to the exact source selected by the published release.

## Failure handling and safe retries

The workflow stops before promotion when validation fails, a required check
does not complete before its wait limit, or `main` changes after candidate
selection. A failed stable run retains its temporary validation branch. Verify
its exact SHA before deleting it:

```sh
git fetch origin refs/heads/<temporary-ref>
git show -s --format='%H%n%s%n%P' FETCH_HEAD
git push --force-with-lease=refs/heads/<temporary-ref>:<candidate-sha> origin --delete <temporary-ref>
```

Do not promote that candidate directly or force-move its tag.

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
  the validation commit directly to bypass required checks.
- If the branch/tag update was rejected, inspect both remote refs rather than
  assuming they are unchanged, then refresh from `main`. Escalate a confirmed
  partial update rather than attempting to repair it by force.
- If upload failed after promotion, preserve the tag and rerun the workflow
  only when the tag and `main` still name the same one-parent `Release <tag>`
  commit, its only changed paths are the two version files, and regenerating
  them from the parent produces identical contents. Do not create a second
  release or force-move the tag.
