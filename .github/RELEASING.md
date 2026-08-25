# Releasing Places

## Normal release

1. Merge the release-ready changes into the default branch.
2. From that branch, run the **Release** workflow with one of these inputs:

   - To release an explicit tag (including every prerelease), provide an unused,
     valid `v`-prefixed tag and leave **bump** set to `none`.
   - To make a stable automatic bump, leave **tag** blank, set **prerelease** to
     false, and choose `patch`, `minor`, or `major`. The workflow derives the
     next tag from the published stable releases.

3. Wait for the workflow to validate the tag, create a local version-only
   commit and annotated tag, build and test `places.zip` from that tag, push
   only the tag, and create the GitHub release with generated notes.

No personal access token is needed. The workflow never pushes `main`.

## Rare recovery after a tag push

If the tag push succeeds but GitHub release creation fails, do not rerun the
workflow: it correctly rejects existing tags. This is especially important for
automatic bumps: they intentionally have no persisted retry state. Do not
force-move the tag.

1. Inspect the existing tag and its version files:

   ```sh
   git fetch --tags origin
   git show --no-patch --decorate <tag>
   git show <tag>:custom_components/places/manifest.json
   git show <tag>:custom_components/places/const.py
   ```

2. If the tag and both version files are correct, build and test the archive
   directly from the tag:

   ```sh
   git archive --format=zip --output=places.zip <tag>:custom_components/places
   unzip -t places.zip
   ```

3. Inspect the GitHub release. If none exists, create it with the archive; if
   a matching draft exists, finish that draft and attach the archive. Do not
   create a second release for the tag.

   ```sh
   gh release view <tag>
   gh release create <tag> places.zip --generate-notes --title <tag> --verify-tag
   # Or, for an existing matching draft:
   gh release upload <tag> places.zip --clobber
   gh release edit <tag> --draft=false
   ```

   Add `--prerelease` when the tag is a prerelease.

If the tag points to the wrong commit or contains wrong version files, leave it
unchanged and release a new, correct version instead.
