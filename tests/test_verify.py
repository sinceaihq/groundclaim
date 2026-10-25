"""Verdict rules, one scenario each (docs/RULES.md)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from groundclaim.git import Repo
from groundclaim.github import GitHub, fixture_transport
from groundclaim.reports import load_report
from groundclaim.trace import load_trace
from groundclaim.verify import CommandRun, Sources, verify

from .conftest import Workspace


def verdicts(message: str, sources: Sources) -> list[tuple[str, str]]:
    return [(a.claim.type, a.verdict) for a in verify(message, sources).assessments]


def src(ws: Workspace, trace: bool = True, **kw: Any) -> Sources:
    events = load_trace(ws.save_trace())[1] if trace and ws.trace else None
    return Sources(repo=Repo(ws.path), base=ws.base, events=events, **kw)


def test_passing_run_after_the_last_edit_supports(ws: Workspace) -> None:
    ws.write("app.py", "def f():\n    return 2\n")
    ws.cmd("pytest -q", 0, "3 passed in 0.1s")
    assert verdicts("All tests pass.", src(ws)) == [("tests_passed", "supported")]


def test_failing_latest_run_contradicts(ws: Workspace) -> None:
    ws.cmd("pytest -q", 0, "3 passed in 0.1s")
    ws.write("app.py", "def f():\n    return 2\n")
    ws.cmd("pytest -q", 1, "1 failed, 2 passed in 0.1s")
    assert verdicts("All tests pass.", src(ws)) == [("tests_passed", "contradicted")]


def test_earlier_failure_fixed_later_is_not_held_against_the_claim(ws: Workspace) -> None:
    ws.cmd("pytest -q", 1, "1 failed, 2 passed in 0.1s")
    ws.write("app.py", "def f():\n    return 2\n")
    ws.cmd("pytest -q", 0, "3 passed in 0.1s")
    assert verdicts("All tests pass.", src(ws)) == [("tests_passed", "supported")]


def test_stale_run_is_not_evidence(ws: Workspace) -> None:
    ws.cmd("pytest -q", 0, "3 passed in 0.1s")
    ws.write("app.py", "def f():\n    return 3\n")
    assert verdicts("All tests pass.", src(ws)) == [("tests_passed", "insufficient_evidence")]


def test_masked_exit_code_uses_the_printed_summary(ws: Workspace) -> None:
    ws.cmd("pytest -q | tail -3", 0, "2 failed, 1 passed in 0.1s")
    assert verdicts("All tests pass.", src(ws)) == [("tests_passed", "contradicted")]


def test_agents_own_success_message_is_not_support(ws: Workspace) -> None:
    ws.cmd('echo "All tests passed"', 0, "All tests passed")
    report = verify("All tests pass.", src(ws))
    assert report.assessments[0].verdict == "insufficient_evidence"
    assert any("printed its own success message" in w for w in report.warnings)


def test_subset_run_does_not_support_all_tests(ws: Workspace) -> None:
    ws.cmd("pytest -q -k test_add", 0, "1 passed, 2 deselected in 0.1s")
    assert verdicts("All 3 tests pass.", src(ws)) == [("tests_passed", "insufficient_evidence")]


def test_wrong_count_contradicts(ws: Workspace) -> None:
    ws.cmd("pytest -q", 0, "40 passed in 0.1s")
    assert verdicts("All 42 tests pass.", src(ws)) == [("tests_passed", "contradicted")]


def test_disabled_tests_block_support(ws: Workspace) -> None:
    ws.write("tests/test_app.py", "import pytest\n\n@pytest.mark.skip\ndef test_f():\n    assert True\n")
    ws.cmd("pytest -q", 0, "1 skipped in 0.1s")
    ws.cmd("pytest -q", 0, "3 passed in 0.1s")
    report = verify("All tests pass.", src(ws))
    assert report.assessments[0].verdict == "insufficient_evidence"
    assert "disabled" in report.assessments[0].reason


def test_ci_check_on_head_confirms(ws: Workspace, fixture_file: Callable[[dict[str, Any]], Path]) -> None:
    head = ws.rev()
    gh = GitHub("o/r", fixture_transport(fixture_file({f"/repos/o/r/commits/{head}/check-runs": {"status": 200, "body": {
        "check_runs": [{"id": 1, "name": "test", "status": "completed", "conclusion": "success"}]}}})))  # fmt: skip
    assert verdicts("CI is green.", src(ws, trace=False, github=gh)) == [("tests_passed", "confirmed")]


def test_ci_failure_contradicts(ws: Workspace, fixture_file: Callable[[dict[str, Any]], Path]) -> None:
    head = ws.rev()
    gh = GitHub("o/r", fixture_transport(fixture_file({f"/repos/o/r/commits/{head}/check-runs": {"status": 200, "body": {
        "check_runs": [{"id": 1, "name": "tests (3.12)", "status": "completed", "conclusion": "failure"}]}}})))  # fmt: skip
    assert verdicts("All tests pass.", src(ws, trace=False, github=gh)) == [("tests_passed", "contradicted")]


def test_trusted_report_for_head_confirms_untrusted_supports(ws: Workspace) -> None:
    head = ws.rev()
    p = ws.root / "junit.xml"
    p.write_text(f'<testsuite><properties><property name="commit" value="{head}"/></properties>'
                 '<testcase name="a"/><testcase name="b"/></testsuite>')  # fmt: skip
    run = load_report(p)
    assert verdicts("All tests pass.", src(ws, trace=False, reports=[run], reports_trusted=True)) == [
        ("tests_passed", "confirmed")
    ]
    assert verdicts("All tests pass.", src(ws, trace=False, reports=[run])) == [("tests_passed", "supported")]


def test_report_for_another_commit_is_not_evidence(ws: Workspace) -> None:
    p = ws.root / "junit.xml"
    p.write_text(
        '<testsuite><properties><property name="commit" value="1234567"/></properties><testcase name="a"/></testsuite>'
    )
    v = verdicts("All tests pass.", src(ws, trace=False, reports=[load_report(p)], reports_trusted=True))
    assert v == [("tests_passed", "insufficient_evidence")]


def test_own_test_run_is_independent(ws: Workspace) -> None:
    run = CommandRun("pytest -q", 0, "3 passed in 0.2s", ws.rev())
    assert verdicts("All tests pass.", src(ws, trace=False, runs=[run])) == [("tests_passed", "confirmed")]


def test_code_change_confirmed_and_missing_file_contradicted(ws: Workspace) -> None:
    ws.write("app.py", "def f():\n    return 2\n")
    ws.commit("change")
    assert verdicts("I updated `app.py`.", src(ws)) == [("code_changed", "confirmed")]
    assert verdicts("I updated `app.py` and `lib.py`.", src(ws)) == [("code_changed", "contradicted")]


def test_nothing_changed_contradicts(ws: Workspace) -> None:
    assert verdicts("I implemented the feature.", src(ws, trace=False)) == [("code_changed", "contradicted")]


def test_bug_fixed_is_at_most_supported(ws: Workspace) -> None:
    ws.write("app.py", "def f():\n    return 2\n")
    ws.cmd("pytest -q", 0, "3 passed in 0.1s")
    assert verdicts("I fixed the bug in app.py.", src(ws)) == [("bug_fixed", "supported")]


def test_bug_fixed_with_failing_tests_is_insufficient(ws: Workspace) -> None:
    ws.write("app.py", "def f():\n    return 2\n")
    ws.cmd("pytest -q", 1, "1 failed in 0.1s")
    assert verdicts("I fixed the bug in app.py.", src(ws)) == [("bug_fixed", "insufficient_evidence")]


def test_commit_claims(ws: Workspace) -> None:
    assert verdicts("I committed the changes.", src(ws, trace=False)) == [("committed", "contradicted")]
    ws.write("app.py", "def f():\n    return 2\n")
    ws.commit("change")
    sha = ws.rev()[:7]
    assert verdicts("I committed the changes.", src(ws)) == [("committed", "confirmed")]
    assert verdicts(f"Committed as {sha}.", src(ws)) == [("committed", "confirmed")]
    assert verdicts("Committed as 7a7a7a7.", src(ws)) == [("committed", "contradicted")]


def test_edits_left_uncommitted_contradict_commit_claim(ws: Workspace) -> None:
    ws.write("app.py", "def f():\n    return 2\n")
    ws.commit("change")
    ws.write("app.py", "def f():\n    return 3\n")
    assert verdicts("I committed the changes.", src(ws)) == [("committed", "contradicted")]


def test_push_checked_on_github(ws: Workspace, fixture_file: Callable[[dict[str, Any]], Path]) -> None:
    head = ws.rev()
    yes = GitHub(
        "o/r",
        fixture_transport(
            fixture_file(
                {f"/repos/o/r/compare/main...{head}": {"status": 200, "body": {"status": "identical"}}}
            )
        ),
    )
    assert verdicts("Pushed to main.", src(ws, trace=False, github=yes)) == [("pushed", "confirmed")]
    no = GitHub(
        "o/r", fixture_transport(fixture_file({"/repos/o/r/branches/main": {"status": 200, "body": {}}}))
    )
    assert verdicts("Pushed to main.", src(ws, trace=False, github=no)) == [("pushed", "contradicted")]


def test_push_followed_by_commit_is_not_support(ws: Workspace) -> None:
    ws.cmd("git push origin main", 0)
    ws.cmd("git commit -am more", 0)
    assert verdicts("Pushed to main.", src(ws)) == [("pushed", "insufficient_evidence")]


def test_pr_claims(ws: Workspace, fixture_file: Callable[[dict[str, Any]], Path]) -> None:
    gh = GitHub("o/r", fixture_transport(fixture_file({"/repos/o/r/pulls/7": {"status": 200, "body": {
        "number": 7, "state": "open", "head": {"sha": ws.rev()}}}})))  # fmt: skip
    assert verdicts("I opened PR #7.", src(ws, trace=False, github=gh)) == [("pr_opened", "confirmed")]
    assert verdicts("I opened PR #8.", src(ws, trace=False, github=gh)) == [("pr_opened", "contradicted")]


def test_pr_number_mismatch_with_command_output(ws: Workspace) -> None:
    ws.cmd("gh pr create --fill", 0, "https://github.com/o/r/pull/12\n")
    assert verdicts("I opened PR #13.", src(ws)) == [("pr_opened", "contradicted")]


def test_deploy_claims(ws: Workspace, fixture_file: Callable[[dict[str, Any]], Path]) -> None:
    head = ws.rev()

    def gh(state: str) -> GitHub:
        return GitHub("o/r", fixture_transport(fixture_file({
            "/repos/o/r/deployments": {"status": 200, "body": [{"id": 5, "sha": head, "environment": "production", "created_at": "1"}]},
            "/repos/o/r/deployments/5/statuses": {"status": 200, "body": [{"state": state, "created_at": "2"}]},
        })))  # fmt: skip

    assert verdicts("Deployed to production.", src(ws, trace=False, github=gh("success"))) == [
        ("deployed", "confirmed")
    ]
    assert verdicts("Deployed to production.", src(ws, trace=False, github=gh("failure"))) == [
        ("deployed", "contradicted")
    ]
    assert verdicts("Deployed to staging.", src(ws, trace=False, github=gh("success"))) == [
        ("deployed", "insufficient_evidence")
    ]


def test_release_and_tag_claims(ws: Workspace, fixture_file: Callable[[dict[str, Any]], Path]) -> None:
    ws.git("tag", "v1.2.0")
    none = GitHub("o/r", fixture_transport(fixture_file({})))
    assert verdicts("I tagged v1.2.0.", src(ws, trace=False, github=none)) == [("released", "confirmed")]
    assert verdicts("I published version 1.2.0.", src(ws, trace=False, github=none)) == [
        ("released", "contradicted")
    ]
    rel = GitHub("o/r", fixture_transport(fixture_file({"/repos/o/r/releases/tags/v1.2.0": {"status": 200, "body": {
        "tag_name": "v1.2.0", "draft": False}}})))  # fmt: skip
    assert verdicts("I published version 1.2.0.", src(ws, trace=False, github=rel)) == [
        ("released", "confirmed")
    ]


def test_draft_release_command_contradicts(ws: Workspace) -> None:
    ws.cmd("gh release create v1.0.0 --draft", 0, "https://github.com/o/r/releases/tag/v1.0.0\n")
    assert verdicts("I published version 1.0.0.", src(ws)) == [("released", "contradicted")]


def test_file_claims(ws: Workspace) -> None:
    (ws.path / "out").mkdir()
    (ws.path / "out" / "report.csv").write_text("a,b\n")
    (ws.path / "empty.md").write_text("")
    assert verdicts("I created `out/report.csv`.", src(ws)) == [("file_created", "confirmed")]
    assert verdicts("I created `empty.md`.", src(ws)) == [("file_created", "contradicted")]
    assert verdicts("I created `missing.pdf`.", src(ws)) == [("file_created", "contradicted")]
    assert verdicts("I created `../../etc/passwd.txt`.", src(ws)) == [
        ("file_created", "insufficient_evidence")
    ]


def test_task_completed_follows_other_claims(ws: Workspace) -> None:
    ws.cmd("pytest -q", 1, "1 failed in 0.1s")
    assert verdicts("All tests pass. The task is complete.", src(ws)) == [
        ("tests_passed", "contradicted"), ("task_completed", "contradicted")]  # fmt: skip
    assert verdicts("The task is complete.", src(ws)) == [("task_completed", "unverifiable")]


def test_no_sources_means_unverifiable(tmp_path: Path) -> None:
    v = verify("All tests pass. Deployed to production.", Sources()).assessments
    assert [a.verdict for a in v] == ["unverifiable", "unverifiable"]


def test_ignored_checks_are_left_out(ws: Workspace, fixture_file: Callable[[dict[str, Any]], Path]) -> None:
    head = ws.rev()
    gh = GitHub("o/r", fixture_transport(fixture_file({f"/repos/o/r/commits/{head}/check-runs": {"status": 200, "body": {
        "check_runs": [{"id": 1, "name": "test", "status": "completed", "conclusion": "success"},
                       {"id": 2, "name": "groundclaim test", "status": "in_progress", "conclusion": None}]}}})))  # fmt: skip
    s = src(ws, trace=False, github=gh, ignore_checks={"groundclaim test"})
    report = verify("All tests pass.", s)
    assert report.assessments[0].verdict == "confirmed"
    assert all("groundclaim test" not in e.summary for e in report.evidence)


def test_pr_number_found_anywhere_end_to_end(
    ws: Workspace, fixture_file: Callable[[dict[str, Any]], Path]
) -> None:
    # Regression: "The pull request is up: #8." once lost its number, and the PR from the current branch (#7)
    # then confirmed the claim. The number must be extracted and checked.
    pr = {"number": 7, "state": "open", "head": {"sha": ws.rev(), "label": "o:main"}}
    gh = GitHub("o/r", fixture_transport(fixture_file({
        "/repos/o/r/pulls/7": {"status": 200, "body": pr}, "/repos/o/r/pulls": {"status": 200, "body": [pr]}})))  # fmt: skip
    assert verdicts("The pull request is up: #8.", src(ws, trace=False, github=gh)) == [
        ("pr_opened", "contradicted")
    ]
    assert verdicts("The pull request is up: #7.", src(ws, trace=False, github=gh)) == [
        ("pr_opened", "confirmed")
    ]
