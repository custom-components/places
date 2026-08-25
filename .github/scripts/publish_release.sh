#!/usr/bin/env bash
set -euo pipefail

mode="${1:-}"
if [[ "$mode" != "check" && "$mode" != "publish" ]]; then
  echo "Usage: $0 check|publish" >&2
  exit 2
fi
if [[ -z "${RELEASE_TAG:-}" ]]; then
  echo "RELEASE_TAG is required" >&2
  exit 1
fi
if [[ "${IS_PRERELEASE:-}" != "true" && "${IS_PRERELEASE:-}" != "false" ]]; then
  echo "IS_PRERELEASE must be true or false" >&2
  exit 1
fi

release_view_error="$RUNNER_TEMP/release-view-error.txt"
if release_state="$(
  gh release view "$RELEASE_TAG" \
    --json isDraft,isPrerelease \
    --jq '[.isDraft, .isPrerelease] | @tsv' \
    2>"$release_view_error"
)"; then
  IFS=$'\t' read -r is_draft is_prerelease <<< "$release_state"
  if [[ "$is_draft" != "true" ]]; then
    echo "Published GitHub release already exists: $RELEASE_TAG" >&2
    exit 1
  fi
  if [[ "$is_prerelease" != "$IS_PRERELEASE" ]]; then
    echo "Existing GitHub release prerelease state does not match the request." >&2
    exit 1
  fi
  if [[ "$mode" == "publish" ]]; then
    gh release upload "$RELEASE_TAG" "$RELEASE_ARCHIVE#places.zip" --clobber
  fi
elif ! grep -Eq "HTTP 404|release not found" "$release_view_error"; then
  cat "$release_view_error" >&2
  exit 1
elif [[ "$mode" == "publish" ]]; then
  release_args=(
    "$RELEASE_TAG"
    "$RELEASE_ARCHIVE#places.zip"
    --draft
    --generate-notes
    --title "$RELEASE_TAG"
    --verify-tag
  )
  if [[ "$IS_PRERELEASE" == "true" ]]; then
    release_args+=(--prerelease)
  fi
  gh release create "${release_args[@]}"
fi

if [[ "$mode" == "publish" ]]; then
  gh release edit "$RELEASE_TAG" --draft=false
fi
