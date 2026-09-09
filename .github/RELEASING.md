# Releasing Places

Release Please manages the release pull request, version tag, and GitHub
Release from conventional commits merged to `main`.

The release pull request updates all version sources together:

- `.release-please-manifest.json`
- `custom_components/places/const.py`
- `custom_components/places/manifest.json`

Review and merge the release pull request after its normal required checks
pass. The next `Release Please` workflow run creates the `v`-prefixed tag and
GitHub Release, then builds and uploads `places.zip` for HACS. Release Please
does not create or maintain a changelog file in this repository.
