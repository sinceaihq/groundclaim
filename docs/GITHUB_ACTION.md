# GitHub Action

`uses: sinceaihq/groundclaim@v0.1.0` installs GroundClaim (Python, no other dependencies) and checks claims against
the checked-out repository and the GitHub API, read-only. The Markdown report goes to the job summary; JSON and HTML
reports are written to `$RUNNER_TEMP` (`groundclaim.json`, `groundclaim.html`) for upload as artifacts.

## Inputs

| input | default | |
|---|---|---|
| `message` | — | the text to check |
| `message-file` | — | a file with the text to check |
| *(neither)* | the pull request description | from the event payload |
| `base` | the PR's base commit | the revision the work started from |
| `trace` | — | an agent run trace |
| `reports` | — | test reports, one path per line |
| `trusted-reports` | `false` | `true` if this workflow produced the reports |
| `require` | `none` | `supported` or `confirmed`: minimum verdict for each checkable claim |
| `strict` | `false` | also fail on claims nothing could check |
| `wait-for-checks` | `0` | seconds to wait for the commit's other check runs to finish |
| `ignore-checks` | — | check names to leave out, one per line — include this job's own name |
| `github-token` | `${{ github.token }}` | needs read access to contents, checks, statuses, pull requests, deployments |
| `python-version` | `3.12` | |

Outputs: `report` (path of the JSON report) and `contradicted` (count).

## Things to get right

- **Check out the PR's head commit**, not the merge commit GitHub creates: CI reports on the head commit.
  `ref: ${{ github.event.pull_request.head.sha }}` and `fetch-depth: 0` (so the base commit is available).
- **Wait for CI**, or run GroundClaim in a workflow triggered by `workflow_run` after CI completes. With
  `wait-for-checks`, list the GroundClaim job's own name in `ignore-checks`, or it will wait for itself.
- **Pull requests from forks** get a read-only token, which is all GroundClaim needs.
- **Security:** the PR description is untrusted. The action reads it from the event file in Python and passes it as
  data; no input is interpolated into a shell script. GroundClaim never runs commands from the description or a
  trace.

## Example: agent pull requests only

```yaml
on:
  pull_request:
    types: [opened, edited, synchronize]
jobs:
  claims:
    if: contains(github.event.pull_request.labels.*.name, 'agent') || github.event.pull_request.user.type == 'Bot'
    runs-on: ubuntu-latest
    permissions: { contents: read, checks: read, statuses: read, pull-requests: read, deployments: read }
    steps:
      - uses: actions/checkout@v7
        with: { ref: "${{ github.event.pull_request.head.sha }}", fetch-depth: 0 }
      - uses: sinceaihq/groundclaim@v0.1.0
        with:
          require: supported
          wait-for-checks: "1200"
          ignore-checks: claims
```
