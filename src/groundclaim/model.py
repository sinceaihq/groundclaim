"""Claims, evidence and verdicts.

Vocabulary (also in docs/SCHEMA.md and schema/report.schema.json):

* A **claim** is something an agent says it did ("all tests pass", "deployed to
  production"), extracted from its own words.
* **Evidence** is a record that bears on a claim, with a **provenance** level:

  - ``self_reported``: the agent's own text or output it produced itself
    (e.g. ``echo "tests passed"``). Never confirms anything.
  - ``observed``: recorded by the harness that ran the agent — a command, its
    exit code, its output. Trustworthy only as far as the harness is.
  - ``independent``: obtained by GroundClaim from an authoritative source it
    queried itself: the git repository, a test report file, the CI or
    deployment API — for the exact revision in question.
  - ``attested``: independent evidence with a verified signature (e.g. a
    Sigstore/in-toto attestation). Reported, not yet verified by v0.1.

  Evidence either **supports** or **contradicts** a claim (or is neutral context).

* A **verdict** per claim:

  - ``confirmed``: independent (or attested) evidence supports it and nothing contradicts it;
  - ``supported``: only observed evidence supports it — plausible, not proven;
  - ``contradicted``: some evidence contradicts it (this overrides support);
  - ``insufficient_evidence``: nothing relevant was found;
  - ``unverifiable``: GroundClaim has no way to check this kind of claim.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = "0.1"

ClaimType = Literal[
    "tests_passed",
    "build_succeeded",
    "lint_clean",
    "code_changed",
    "bug_fixed",
    "committed",
    "pushed",
    "pr_opened",
    "deployed",
    "released",
    "file_created",
    "task_completed",
]
Provenance = Literal["self_reported", "observed", "independent", "attested"]
Stance = Literal["supports", "contradicts", "neutral"]
Verdict = Literal["confirmed", "supported", "contradicted", "insufficient_evidence", "unverifiable"]

PROVENANCE_ORDER = {"self_reported": 0, "observed": 1, "independent": 2, "attested": 3}


@dataclass
class Claim:
    id: str
    type: ClaimType
    text: str  # the sentence the claim was taken from
    span: tuple[int, int]  # character offsets in the agent's message
    # Specifics mentioned in the claim: {"environment": "production"}, {"files": [...]},
    # {"count": 42}, {"commit": "abc123"}, {"pr": 12}, {"version": "1.2.0"}, {"path": "report.pdf"}
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Evidence:
    id: str
    kind: str  # "test_report", "command", "git_commit", "git_diff", "ci_check", "deployment", "file", "agent_text" ...
    provenance: Provenance
    source: str  # where it came from: a file path, "git", "github:owner/repo", "trace:run.jsonl#12"
    summary: str  # one line for humans
    revision: str | None = None  # the git commit the evidence is about, if known
    time: str | None = None  # ISO 8601, if known
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Link:
    """How one piece of evidence bears on one claim."""

    evidence: str  # Evidence.id
    stance: Stance
    reason: str
    decisive: bool = False  # by itself enough to confirm the claim (independent, current revision)


@dataclass
class Assessment:
    claim: Claim
    verdict: Verdict
    reason: str
    links: list[Link] = field(default_factory=list)


@dataclass
class Report:
    schema_version: str
    subject: dict[str, Any]  # what was checked: repository, revision, message source
    assessments: list[Assessment]
    evidence: list[Evidence]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for a in self.assessments:
            out[a.verdict] = out.get(a.verdict, 0) + 1
        return out
