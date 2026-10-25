"""Baselines for GroundClaim-Bench. Each maps (claim, sources) to a verdict.

* ``trust_all`` — believe the agent: every claim is confirmed. This is what
  happens when nobody checks.
* ``trace_keywords`` — a naive log check: a claim is confirmed if the trace has
  a matching command that exited 0, contradicted if every matching command
  failed, and otherwise insufficient. No recency, masking, tampering or
  independent-source logic. It needs a trace.
"""

from __future__ import annotations

from collections.abc import Callable

from groundclaim.model import Claim, Verdict
from groundclaim.verify import Sources

CATEGORY = {"tests_passed": "test", "build_succeeded": "build", "lint_clean": "lint", "committed": "commit",
            "pushed": "push", "pr_opened": "pr", "deployed": "deploy", "released": "release"}  # fmt: skip


def trust_all(claim: Claim, sources: Sources) -> Verdict:
    return "confirmed"


def trace_keywords(claim: Claim, sources: Sources) -> Verdict:
    events = sources.events
    if events is None:
        return "insufficient_evidence"
    cat = CATEGORY.get(claim.type)
    if cat:
        runs = [e for e in events if e.kind == "command" and cat in e.categories]
        if any(e.exit_code == 0 for e in runs):
            return "confirmed"
        if runs and all(e.exit_code not in (0, None) for e in runs):
            return "contradicted"
        return "insufficient_evidence"
    paths = [e.path or "" for e in events if e.kind == "file_write"]
    wanted = claim.details.get("files") or ([claim.details["path"]] if claim.details.get("path") else [])
    if wanted:
        return (
            "confirmed" if all(any(p.endswith(w) for p in paths) for w in wanted) else "insufficient_evidence"
        )
    return "insufficient_evidence"


BASELINES: dict[str, Callable[[Claim, Sources], Verdict]] = {
    "trust_all": trust_all,
    "trace_keywords": trace_keywords,
}
