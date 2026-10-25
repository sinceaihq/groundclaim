from __future__ import annotations

import pytest

from groundclaim.claims import extract_claims


def types(text: str) -> list[str]:
    return [c.type for c in extract_claims(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("All tests pass now.", ["tests_passed"]),
        ("I ran pytest: 42 passed.", ["tests_passed"]),
        ("CI is green.", ["tests_passed"]),
        ("The build succeeds.", ["build_succeeded"]),
        ("ruff reports no errors.", ["lint_clean"]),
        ("I fixed the off-by-one bug in `src/pager.py`.", ["bug_fixed"]),
        ("I updated `src/app.py` to validate input.", ["code_changed"]),
        ("I committed the changes.", ["committed"]),
        ("Pushed to main.", ["pushed"]),
        ("I opened PR #12.", ["pr_opened"]),
        ("Deployed to production.", ["deployed"]),
        ("I published version 1.2.0.", ["released"]),
        ("I created `reports/summary.md`.", ["file_created"]),
        ("The task is complete.", ["task_completed"]),
    ],
)
def test_claim_types(text: str, expected: list[str]) -> None:
    assert types(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Tests are still failing.",
        "I could not deploy to production.",
        "I didn't push the changes yet.",
        "Should I open a PR?",
        "I looked through the module first.",
        "I added a note to the description.",
    ],
)
def test_not_claims(text: str) -> None:
    assert types(text) == []


def test_details() -> None:
    claims = extract_claims(
        "I fixed the bug in `src/pager.py`. All 42 tests pass. Committed as 3f9a1c2. Pushed to `feature/x`. "
        "Opened PR #7. Deployed to prod. Released v1.4.0. I created `out/report.csv`."
    )
    d = {c.type: c.details for c in claims}
    assert d["bug_fixed"]["files"] == ["src/pager.py"]
    assert d["tests_passed"]["count"] == 42
    assert d["committed"]["commit"] == "3f9a1c2"
    assert d["pushed"]["branch"] == "feature/x"
    assert d["pr_opened"]["pr"] == 7
    assert d["deployed"]["environment"] == "production"
    assert d["released"]["version"] == "1.4.0"
    assert d["file_created"]["path"] == "out/report.csv"


def test_hedged_claims_are_kept_and_marked() -> None:
    (claim,) = extract_claims("The tests should pass now.")
    assert claim.type == "tests_passed" and claim.details.get("hedged") is True


def test_spans_point_at_the_sentence() -> None:
    text = "Some context. All tests pass now. More."
    (claim,) = extract_claims(text)
    assert text[claim.span[0] : claim.span[1]] == "All tests pass now."


def test_filenames_with_dots_do_not_split_sentences() -> None:
    (claim,) = extract_claims("I updated pager.py and utils.py to fix the parser.")
    assert claim.details["files"] == ["pager.py", "utils.py"]
