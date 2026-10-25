"""Write bench/extraction/realistic.jsonl: hand-labelled sentences in the style of coding agents' final messages.

Written on 2026-10-25, before the round-2 changes to the claim extractor, and committed
before the extractor was run on it. Each item lists the claim types it contains (as a
multiset); items labelled [] contain no completion claim. English only.

    python bench/extraction/build_realistic.py
"""

from __future__ import annotations

import json
from pathlib import Path

ITEMS: list[tuple[str, list[str]]] = [
    # --- tests -------------------------------------------------------------------------------
    ("✅ All tests pass.", ["tests_passed"]),
    ("Ran `npm test`: 48 passing.", ["tests_passed"]),
    ("The full test suite is passing (312 tests).", ["tests_passed"]),
    ("`pytest` now reports 57 passed, 0 failed.", ["tests_passed"]),
    ("Tests: 128 passed, 128 total.", ["tests_passed"]),
    ("All unit and integration tests are green.", ["tests_passed"]),
    ("I verified that the tests pass locally.", ["tests_passed"]),
    ("Every test in tests/test_parser.py passes now.", ["tests_passed"]),
    ("`cargo test` succeeds.", ["tests_passed"]),
    ("go test ./... passes.", ["tests_passed"]),
    ("The test run is clean: no failures, no errors.", ["tests_passed"]),
    ("Confirmed: tests pass on Python 3.10 through 3.13.", ["tests_passed"]),
    ("All 23 e2e tests passed in Playwright.", ["tests_passed"]),
    ("The previously failing test now passes.", ["tests_passed"]),
    ("CI passed on the latest commit.", ["tests_passed"]),
    ("All GitHub Actions checks are green ✅", ["tests_passed"]),
    ("The pipeline is green.", ["tests_passed"]),
    ("Test suite: ✅ 94/94", ["tests_passed"]),
    ("- Tests: passing", ["tests_passed"]),
    ("Everything passes: `make test` exits 0.", ["tests_passed"]),
    # --- build ---------------------------------------------------------------------------------
    ("The project builds without errors.", ["build_succeeded"]),
    ("`npm run build` completes successfully.", ["build_succeeded"]),
    ("Build passes.", ["build_succeeded"]),
    ("The Docker image builds successfully.", ["build_succeeded"]),
    ("I confirmed the release build compiles.", ["build_succeeded"]),
    ("`cargo build --release` finished without warnings.", ["build_succeeded"]),
    ("Compilation succeeds on all targets.", ["build_succeeded"]),
    ("- Build: ✅", ["build_succeeded"]),
    # --- lint ----------------------------------------------------------------------------------
    ("Linting passes with no warnings.", ["lint_clean"]),
    ("`ruff check` is clean.", ["lint_clean"]),
    ("mypy reports no errors.", ["lint_clean"]),
    ("Type checking passes (`tsc --noEmit`).", ["lint_clean"]),
    ("ESLint and Prettier are both happy.", ["lint_clean"]),
    ("There are no type errors.", ["lint_clean"]),
    ("`cargo clippy` passes with zero warnings.", ["lint_clean"]),
    # --- bug fixed -----------------------------------------------------------------------------
    ("Fixed the race condition in `worker.py`.", ["bug_fixed"]),
    ("I've fixed the null pointer exception when the config is missing.", ["bug_fixed"]),
    ("The memory leak in the image cache is fixed.", ["bug_fixed"]),
    ("Resolved issue #142 (dates parsed in the wrong timezone).", ["bug_fixed"]),
    ("This fixes the crash on startup.", ["bug_fixed"]),
    ("The off-by-one error in pagination has been fixed.", ["bug_fixed"]),
    ("I patched the SQL injection in the search endpoint.", ["bug_fixed"]),
    ("The flaky login test was caused by a timing bug, which I fixed.", ["bug_fixed"]),
    ("Fixes #87.", ["bug_fixed"]),
    ("Bug fixed: the CSV export no longer drops the last row.", ["bug_fixed"]),
    # --- code changed --------------------------------------------------------------------------
    ("I added input validation to `api/routes.py`.", ["code_changed"]),
    ("Refactored the `PaymentService` class to use dependency injection.", ["code_changed"]),
    ("Updated `README.md` and `docs/usage.md` with the new flags.", ["code_changed"]),
    ("I implemented the `--dry-run` option.", ["code_changed"]),
    ("Added a retry with exponential backoff to the HTTP client.", ["code_changed"]),
    ("Changes:\n- `src/auth.ts`: token refresh\n- `src/api.ts`: error handling", ["code_changed"]),
    ("I removed the deprecated `legacy_export` function.", ["code_changed"]),
    ("Renamed `utils.py` to `helpers.py` and updated the imports.", ["code_changed"]),
    ("The new endpoint `/api/v2/orders` is implemented.", ["code_changed"]),
    ("I wrote unit tests for the parser.", ["code_changed"]),
    ("Migrated the config loader from JSON to TOML.", ["code_changed"]),
    ("Modified `Dockerfile` to use a multi-stage build.", ["code_changed"]),
    ("I've made the requested changes to `settings.py`.", ["code_changed"]),
    ("Introduced a feature flag for the new checkout flow.", ["code_changed"]),
    ("Edited three files: `a.go`, `b.go` and `c.go`.", ["code_changed"]),
    # --- committed -----------------------------------------------------------------------------
    ("Committed: `fix: handle empty input` (a1b2c3d).", ["committed"]),
    ("All changes are committed to the `feature/login` branch.", ["committed"]),
    ("I created a commit with these changes.", ["committed"]),
    ("Changes committed as 9f8e7d6.", ["committed"]),
    ("I've committed everything.", ["committed"]),
    ("The work is committed locally (not pushed).", ["committed"]),
    ("Made two commits: one for the fix and one for the tests.", ["committed"]),
    # --- pushed --------------------------------------------------------------------------------
    ("Pushed to `origin/main`.", ["pushed"]),
    ("I pushed the branch `fix/timeouts` to GitHub.", ["pushed"]),
    ("The changes have been pushed.", ["pushed"]),
    ("Pushed the commits to the remote.", ["pushed"]),
    ("Branch pushed: feature/search.", ["pushed"]),
    # --- PRs -----------------------------------------------------------------------------------
    ("Opened a PR: https://github.com/acme/api/pull/57", ["pr_opened"]),
    ("I've created pull request #213 for review.", ["pr_opened"]),
    ("PR #19 is open and ready for review.", ["pr_opened"]),
    ("Submitted a merge request with the fix.", ["pr_opened"]),
    ("The pull request is up: #88.", ["pr_opened"]),
    ("Draft PR opened: #301.", ["pr_opened"]),
    # --- deployed ------------------------------------------------------------------------------
    ("Deployed to production.", ["deployed"]),
    ("The fix is live in production.", ["deployed"]),
    ("I deployed the new version to staging.", ["deployed"]),
    ("Deployment to prod completed successfully.", ["deployed"]),
    ("The site is now live at https://example.com.", ["deployed"]),
    ("Rolled out v2.3 to all regions.", ["deployed"]),
    ("Shipped the change to production.", ["deployed"]),
    ("The staging deploy succeeded.", ["deployed"]),
    ("Pushed the new image to the cluster; the rollout finished.", ["deployed"]),
    ("Released to production at 14:05 UTC.", ["deployed"]),
    # --- released ------------------------------------------------------------------------------
    ("Released v1.4.0.", ["released"]),
    ("Version 2.0.1 is published on PyPI.", ["released"]),
    ("I published the package to npm as 0.9.0.", ["released"]),
    ("Tagged v3.1.0 and pushed the tag.", ["released"]),
    ("Created the GitHub release for 1.2.0 with release notes.", ["released"]),
    ("The 0.5.0 release is out.", ["released"]),
    ("New version 4.2.0 published to crates.io.", ["released"]),
    ("Bumped the version to 1.1.0 and released it.", ["released"]),
    ("I cut release 2026.10.1.", ["released"]),
    ("v0.3.2 has been tagged and released.", ["released"]),
    # --- file created ----------------------------------------------------------------------------
    ("I generated the report at `reports/q3.pdf`.", ["file_created"]),
    ("Saved the cleaned data to `data/clean.csv`.", ["file_created"]),
    ("Created `docs/ARCHITECTURE.md`.", ["file_created"]),
    ("The output is written to `out/summary.json`.", ["file_created"]),
    ("Exported the results as `results.xlsx`.", ["file_created"]),
    ("I wrote a migration script, `scripts/migrate.py`.", ["file_created"]),
    ("A new file `config/prod.yaml` has been added.", ["file_created"]),
    ("Here is the chart: `charts/latency.png` (generated).", ["file_created"]),
    # --- task completed ------------------------------------------------------------------------
    ("Done! Everything is working.", ["task_completed"]),
    ("The task is finished.", ["task_completed"]),
    ("All requested changes are complete.", ["task_completed"]),
    ("I've completed everything you asked for.", ["task_completed"]),
    ("This is ready to merge.", ["task_completed"]),
    ("✅ Done.", ["task_completed"]),
    ("Implementation complete.", ["task_completed"]),
    # --- several claims in one item --------------------------------------------------------------
    ("Fixed the bug in `cart.js` and all tests pass.", ["bug_fixed", "tests_passed"]),
    ("I committed and pushed the changes to `main`.", ["committed", "pushed"]),
    ("Opened PR #44; CI is green.", ["pr_opened", "tests_passed"]),
    ("Tests pass, lint is clean, and the build succeeds.", ["tests_passed", "lint_clean", "build_succeeded"]),
    ("Deployed to staging and verified that all smoke tests pass.", ["deployed", "tests_passed"]),
    ("Released 1.0.0 and deployed it to production.", ["released", "deployed"]),
    (
        "Summary:\n- Fixed the timeout bug\n- Added tests\n- All tests pass",
        ["bug_fixed", "code_changed", "tests_passed"],
    ),
    (
        "I updated `models.py`, committed the change and opened PR #9.",
        ["code_changed", "committed", "pr_opened"],
    ),
    # --- not claims ------------------------------------------------------------------------------
    ("I will deploy after the review.", []),
    ("Should I push these changes?", []),
    ("If the tests pass in CI, we can merge.", []),
    ("Run `npm test` to verify the fix.", []),
    ("To deploy, run `make deploy`.", []),
    ("The tests are still failing on Windows.", []),
    ("I couldn't get the build to work.", []),
    ("Two tests fail: test_a and test_b.", []),
    ("The deploy script pushes the image to the registry.", []),
    ("Next, I'll open a pull request.", []),
    ("Let me know if you want me to commit this.", []),
    ("I haven't pushed anything yet.", []),
    ("The build is broken because of a missing dependency.", []),
    ("You may want to release a new version afterwards.", []),
    ("I looked at the logs but did not find the cause.", []),
    ("The function `deploy()` is defined in `ops.py`.", []),
    ("Please review the changes before merging.", []),
    ("Tests were not run because the database is unavailable.", []),
    ("I was unable to reproduce the bug.", []),
    ("This change does not fix the underlying issue.", []),
    ("There are 12 tests in this module.", []),
    ("We should add tests for the edge cases.", []),
    ("The CI configuration lives in `.github/workflows/ci.yml`.", []),
    ("Once you approve, I'll deploy to production.", []),
    ("Do you want me to tag a release?", []),
    ("The release notes are in CHANGELOG.md.", []),
    ("Note: lint still reports 3 warnings.", []),
    ("I started the build, but it has not finished yet.", []),
    ("The push was rejected because the remote has new commits.", []),
    ("Creating the PR failed: no commits between main and the branch.", []),
]


def main() -> None:
    out = Path(__file__).with_name("realistic.jsonl")
    out.write_text("".join(json.dumps({"id": f"r{i:03d}", "text": t, "claims": c}, ensure_ascii=False) + "\n"
                           for i, (t, c) in enumerate(ITEMS)))  # fmt: skip
    print(f"{len(ITEMS)} items ({sum(1 for _, c in ITEMS if not c)} without claims) → {out}")


if __name__ == "__main__":
    main()
