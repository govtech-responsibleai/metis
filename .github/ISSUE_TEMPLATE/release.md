---
name: Release
about: Point users to the plan for a release (maintainers only)
title: "release/vX.Y.Z"
labels: release
---

<!--
Before you submit:
- Replace vX.Y.Z in the title and below with the tag, for example v1.0.0b4, X.Y.Z with the
  version without the v, for example 1.0.0b4, and NUMBER with the milestone's number.
- After you submit, set the milestone of the same name in the sidebar, assign the maintainer
  who runs the release, and pin this issue if it is the next release.
- The planned release notes live in the milestone description, not here. Its skeleton is in the
  Milestones section of CONTRIBUTING.md.
- When the plan changes, update the milestone description and its "Plan last updated" line, then
  comment here with what changed so that subscribers are notified.
-->

<!-- One sentence on what this release is for. -->

The planned release notes and the full list of work are in the
[vX.Y.Z milestone](https://github.com/govtech-responsibleai/metis/milestone/NUMBER), with the
expected ship date. Plans may change before the release. Subscribe to this issue to be told when
they do, and ask questions about the release here.

## Shipping

Each step is described in "Beta releases" in `CONTRIBUTING.md`.

- [ ] Every issue in the milestone is closed or moved to a later milestone
- [ ] A pull request from `chore/bump-X.Y.Z` into `next`, titled
      `chore(release): bump the version to X.Y.Z`, is merged. It sets every
      `pyproject.toml` version and the Status section of `README.md` to `X.Y.Z`, and re-locks with
      `uv lock`
- [ ] On `next`, `git grep -n '^version = ' -- '*pyproject.toml'` shows `X.Y.Z` on each of its
      8 lines, and `uv lock --check` passes
- [ ] A pull request from `next` into `main`, titled `release/vX.Y.Z`, is approved by another
      maintainer and merged with a merge commit, not a squash. Its body says "Part of #N", not
      "Closes #N", so that this issue stays open until the last box
- [ ] The merge commit on `main` is tagged with an annotated `vX.Y.Z` tag, and the tag is pushed
- [ ] The GitHub release is published from the tag with generated release notes, as a prerelease
      for a beta
- [ ] The milestone is closed
- [ ] This issue is closed with a link to the release, and the next release issue is pinned
