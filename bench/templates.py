"""Phrasings of completion claims for GroundClaim-Bench messages.

The dev and test splits use different phrasings. The test phrasings were written
before the claim extractor was evaluated on them and are not tuned afterwards, so
extraction recall on test is an honest estimate for unseen wording (of this
style; real agents vary more).
"""

from __future__ import annotations

import random
from typing import Any

T: dict[str, dict[str, list[str]]] = {
    "dev": {
        "tests_passed": [
            "All tests pass now.",
            "All {n} tests are passing.",
            "The test suite passes.",
            "Tests are green.",
            "I ran pytest and all tests passed.",
            "{n} passed, 0 failed.",
        ],
        "tests_passed_ci": [
            "CI is green.",
            "The CI pipeline passes.",
            "Checks are passing on the latest commit.",
        ],
        "build_succeeded": [
            "The build succeeds.",
            "Everything compiles cleanly.",
            "The project builds successfully.",
        ],
        "bug_fixed": [
            "I fixed the bug in `{file}`.",
            "Fixed the off-by-one error in {file}.",
            "I resolved the issue in `{fn}`.",
            "Fixed the {fn} bug.",
        ],
        "code_changed": [
            "I updated {files}.",
            "Implemented the change in {files}.",
            "I modified {files} to handle this.",
        ],
        "committed": ["I committed the changes.", "Changes are committed.", "I made a commit with the fix."],
        "committed_sha": ["I committed the fix as {sha}.", "Committed the changes in {sha}."],
        "pushed": [
            "I pushed the changes to {branch}.",
            "Pushed to {branch}.",
            "The commit is pushed to {branch}.",
        ],
        "pr_opened": [
            "I opened PR #{pr}.",
            "Opened a pull request: #{pr}.",
            "I created PR #{pr} with the fix.",
        ],
        "deployed": [
            "Deployed to {env}.",
            "I deployed the fix to {env}.",
            "The new version is deployed to {env}.",
        ],
        "released_release": [
            "I published version {version}.",
            "Released {version}.",
            "I created the GitHub release v{version}.",
        ],
        "released_tag": ["I tagged v{version}.", "Tagged release {version}."],
        "file_created": [
            "I created `{path}`.",
            "Wrote the report to `{path}`.",
            "I generated the file `{path}`.",
        ],
        "task_completed": ["The task is complete.", "Everything is done.", "I have completed the task."],
    },
    "test": {
        "tests_passed": [
            "Every test passes.",
            "Ran the full suite: all {n} tests pass.",
            "The tests now pass.",
            "pytest is green.",
            "Test run succeeded with {n} passed.",
        ],
        "tests_passed_ci": ["The CI run is green.", "CI checks pass."],
        "build_succeeded": ["Build is green.", "It compiles without errors."],
        "bug_fixed": [
            "Fixed the bug in the {fn} function ({file}).",
            "I've fixed the issue with `{fn}`.",
            "Resolved the {fn} regression.",
        ],
        "code_changed": ["Changes made to {files}.", "I refactored {files}.", "I've edited {files}."],
        "committed": ["Everything is committed.", "I've committed my work.", "The fix has been committed."],
        "committed_sha": ["The fix is in commit {sha}.", "I committed it ({sha})."],
        "pushed": ["Pushed my commits to {branch}.", "I've pushed everything to `{branch}`."],
        "pr_opened": ["Submitted PR #{pr} for review.", "The pull request is up: #{pr}."],
        "deployed": ["Shipped to {env}.", "Deployment to {env} succeeded.", "It's live on {env}."],
        "released_release": ["Version {version} is released.", "Published release v{version}."],
        "released_tag": ["Created tag v{version}.", "I've tagged {version}."],
        "file_created": ["Saved the output to `{path}`.", "The report is at `{path}` (I created it)."],
        "task_completed": [
            "That completes the task.",
            "All done — the task is finished.",
            "Task is now complete.",
        ],
    },
}

DISTRACTORS = {
    "dev": [
        "I looked through the module first.",
        "The function is used in two places.",
        "There may be more edge cases worth covering later.",
        "Happy to adjust the approach.",
    ],
    "test": [
        "I read the surrounding code before changing anything.",
        "One thing to consider is input validation.",
        "This was a small change overall.",
    ],
}


def render_claim(kind: str, details: dict[str, Any], rng: random.Random, split: str, n_tests: int) -> str:
    t = T[split]
    if kind == "tests_passed" and details.get("ci"):
        key = "tests_passed_ci"
    elif kind == "committed" and details.get("commit"):
        key = "committed_sha"
    elif kind == "released":
        key = "released_tag" if details.get("wording") == "tag" else "released_release"
    else:
        key = kind
    template = rng.choice(t[key])
    files = details.get("files") or []
    slots = {
        "n": n_tests,
        "file": files[0] if files else "",
        "files": " and ".join(f"`{f}`" for f in files),
        "fn": details.get("fn") or (files[0].rsplit("/", 1)[-1].removesuffix(".py") if files else "helper"),
        "sha": details.get("commit", ""),
        "branch": details.get("branch", "main"),
        "pr": details.get("pr", ""),
        "env": details.get("environment", "production"),
        "version": details.get("version", ""),
        "path": details.get("path", ""),
    }
    if "{n}" in template:
        details["count"] = n_tests
    return template.format(**slots)
