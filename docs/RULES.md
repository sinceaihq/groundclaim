# Verdict rules

GroundClaim is deterministic: the same message and evidence always give the same report. This page lists every rule;
each has a test in [`tests/test_verify.py`](../tests/test_verify.py).

## Evidence and provenance

| provenance | produced by | examples | can confirm? |
|---|---|---|---|
| `self_reported` | the agent itself | its message; `echo "All tests passed"` in its own commands | never (and it never counts as support) |
| `observed` | the harness that ran the agent | a command and its exit code in a trace; remote-tracking refs; a test report written in the agent's workspace; a GitHub commit status (anyone with write access can post one) | no — gives at most **supported** |
| `independent` | GroundClaim, from a source it queried itself | `git diff` / `git log` in the repository; a GitHub check run, pull request, deployment or release; the file on disk; a test command run with `--run-tests`; a report passed with `--trusted-reports` | yes, when it is about the current state |
| `attested` | a signed statement (Sigstore / in-toto) | — | reserved; v0.1 produces none |

Every link between a claim and a piece of evidence has a stance — `supports`, `contradicts` or `neutral` — and a
`decisive` flag: decisive links are independent evidence about the current state that would, alone, establish the
claim.

## Deciding the verdict

1. **Contradiction wins.** Any contradicting link from observed or better evidence makes the claim
   **contradicted**, whatever supports it.
2. **Confirmed needs a decisive link** and nothing contradicting.
3. **Otherwise, observed support gives supported** ("plausible, no independent evidence for the current revision").
4. **Ceilings.** Some situations cap the verdict even when support exists (below): the verdict becomes the ceiling,
   with the reason.
5. **Nothing decisive either way** gives **insufficient evidence**; if no given source could check this kind of claim
   at all, **unverifiable**.
6. **Whole-task claims** ("the task is complete") are **contradicted** if another claim in the same message is
   contradicted, and otherwise **unverifiable**.

## Tests, builds and lint

- **The latest complete run decides.** An earlier failure followed by a passing run does not count against the claim.
  Runs still in progress or started in the background are ignored.
- **Stale runs are neutral:** if the trace shows code being edited after the run, the run says nothing about the
  final code. (Documentation files — `*.md`, `*.rst`, `*.txt`, README, CHANGELOG — do not make a run stale.)
- **Hidden exit codes:** for `pytest | tail`, `pytest || true`, `set +e`, the exit code is not the test runner's.
  GroundClaim then uses the printed summary (pytest, jest, vitest, mocha, cargo, go test, unittest); without a
  summary the run is neutral.
- **Printed summaries override exit codes:** "2 failed" contradicts even with exit code 0. "No tests ran" (0 passed)
  contradicts.
- **Counts:** "all 42 tests pass" is contradicted by a full run showing 40 passed (skipped tests may make up the
  difference).
- **Subsets are neutral:** `-k`, `--lf`, `-t`, `--grep`, `::test_name`, `.only` — a passing selection says nothing
  about the tests that were not selected. A failing selection still contradicts.
- **Self-reported success** (`echo "Tests: OK"`) is linked as neutral and produces a warning.
- **Disabled tests:** if test files were deleted or skip/xfail markers added since the starting commit (pytest,
  unittest, jest/vitest/mocha `.skip`/`xit`, JUnit `@Disabled`, Go `t.Skip`, Rust `#[ignore]`), test claims are at most
  **insufficient evidence**, with a warning. Removing a test *function* is not detected.
- **Reports:** a JUnit or CTRF report supports or contradicts by its counts. Reports name the commit they tested only
  sometimes (`<property name="commit">`, CTRF `environment.commit`); a report for another commit is neutral; a report
  written before the trace's last code edit (by its timestamp or file time) is neutral. Reports are observed unless
  `--trusted-reports` says they were produced outside the agent's control; a trusted report for the current commit,
  with no uncommitted code changes, is decisive.
- **CI on GitHub:** check runs on the checked-out commit whose names look like test, build or lint jobs. Success is
  decisive (unless there are uncommitted code changes the CI did not see); failure, timeout or cancellation
  contradicts; unfinished runs are neutral. For test and build claims, if no check name matches, all checks are used
  but are not decisive.
  Commit statuses are observed only.
- **`--run-tests`:** GroundClaim runs the command itself (no shell); exit 0 is decisive, anything else contradicts.

## Code changes and bug fixes

- **Named files** must have changed since `--base` (committed or not): changed → decisive support; not changed →
  contradicted. Without `--base`, GroundClaim can only look at the working tree and the last commit, and a missing file
  is neutral.
- **No file named:** some change since `--base` supports (not decisive — GroundClaim does not judge *what* changed);
  no change at all contradicts.
- **"Fixed the bug"** is at most **supported**: whether a change fixes a bug is a judgement. If the latest complete
  test run fails (and nothing was edited after it), at most **insufficient evidence**.

## Commits and pushes

- **A commit id in the claim** must exist and be in the current branch's history.
- **"Committed"** with `--base`: new commits since base are decisive, none contradict. Files the agent edited (per the
  trace) that are still uncommitted contradict; other uncommitted files are noted.
- **"Pushed":** GitHub is decisive (the branch contains the commit, via the compare API); a missing branch or commit
  contradicts. Local remote-tracking refs are observed only. A `git push` in the trace followed by another commit is
  neutral; a failed push contradicts.

## Pull requests, deployments, releases, files

- **PR:** GitHub has the numbered PR (or one from the current branch) → decisive; it does not → contradicted. A PR URL
  printed by `gh pr create` with a different number contradicts.
- **Deployed:** the latest GitHub deployment of the current commit to the claimed environment: `success` decisive,
  `failure`/`error` contradicts, others neutral; no deployment record is neutral (not every deploy creates one). A
  deploy command in the trace supports or contradicts by its exit code.
- **Released:** "tagged v1.2.0" is checked against git tags (decisive); "released/published 1.2.0" against GitHub
  releases (published → decisive; draft or missing → contradicted). A `gh release create --draft` in the trace
  contradicts a published release. Package registries are not checked in v0.1.
- **File created:** exists and is not empty → decisive; missing or empty → contradicted. Paths outside the workspace
  and symbolic links are not followed (neutral).
