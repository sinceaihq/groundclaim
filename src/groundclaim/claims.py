"""Find completion claims in an agent's message.

Deterministic patterns, sentence by sentence. A sentence that negates the
action ("tests are still failing", "I could not deploy") is not a claim; a
hedged one ("tests should pass now") is kept and marked ``hedged``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from .model import Claim, ClaimType

# A sentence ends at ., ! or ? followed by whitespace (not inside "pager.py" or "1.4.0"), or at a line break.
SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+|\n+")
NEGATION_RE = re.compile(
    r"\b(?:not|n't|never|no longer|unable|failed to|fails?|failing|could not|couldn't|cannot|can't|did not|didn't|"
    r"won't|haven't|hasn't|without|except|but \d+ fail)\b",
    re.IGNORECASE,
)
HEDGE_RE = re.compile(
    r"\b(?:should|would|might|may|probably|likely|i think|i believe|seems?|appears?)\b", re.IGNORECASE
)
PATH_RE = re.compile(
    r"`([^`\s]+\.[A-Za-z0-9]{1,8})`|(?<![\w/.-])((?:[\w.-]+/)*[\w-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|kt|rb|php|cs|c|h|cpp|md|json|yml|yaml|toml|sql|sh|html|css|txt|csv|pdf|xlsx|docx))(?![\w/])"
)
SHA_RE = re.compile(r"(?<![0-9A-Za-z])((?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40})(?![0-9A-Za-z])")
VERSION_RE = re.compile(r"\bv?(\d+\.\d+(?:\.\d+)?(?:[-.]?(?:rc|a|b|alpha|beta|dev)\.?\d*)?)\b")
PR_RE = re.compile(r"(?:\bPR|pull request|merge request|MR)\s*#?\s*(\d+)|/pull/(\d+)", re.IGNORECASE)
COUNT_RE = re.compile(
    r"\b(\d+)\s+(?:of\s+\d+\s+)?(?:(?:unit |integration |e2e )?tests?\b|passed\b)", re.IGNORECASE
)
ENV_RE = re.compile(
    r"\b(production|prod|staging|stage|preview|dev(?:elopment)?|test(?:ing)? environment|qa)\b", re.IGNORECASE
)

# (type, pattern). Patterns are matched against one sentence at a time.
PATTERNS: list[tuple[ClaimType, re.Pattern[str]]] = [
    ("tests_passed", re.compile(
        r"\b(?:all\s+(?:the\s+)?(?:\d+\s+)?(?:unit\s+|integration\s+|e2e\s+)?tests?\s+(?:now\s+)?(?:pass|passed|passing|succeed|are\s+green|are\s+passing)"
        r"|tests?\s+(?:are\s+|is\s+)?(?:now\s+)?(?:passing|green|all\s+pass)"
        r"|tests?\s+(?:should|will|now)\s+(?:all\s+)?(?:now\s+)?pass"
        r"|(?:test\s+suite|tests|test\s+run|pytest|jest|vitest|npm test|go test|cargo test|unit tests)\s+(?:now\s+)?(?:passes|passed|succeeds|succeeded|is\s+green)"
        r"|(?:every|each)\s+test\s+(?:now\s+)?(?:passes|passed)"
        r"|\d+\s+(?:of\s+\d+\s+)?tests?\s+passed|\d+\s+passed\b|(?:ci|pipeline|checks?)(?:\s+(?:run|checks?))?\s+(?:is\s+|are\s+)?(?:now\s+)?(?:green|passing|passes|pass|passed))",
        re.IGNORECASE)),
    ("build_succeeded", re.compile(
        r"\b(?:build\s+(?:now\s+)?(?:succeeds|succeeded|passes|passed|works|is\s+green|is\s+successful)|builds?\s+(?:cleanly|successfully)"
        r"|compiles?\s+(?:cleanly|successfully|without errors)|successfully\s+(?:built|compiled))",
        re.IGNORECASE)),
    ("lint_clean", re.compile(
        r"\b(?:lint(?:ing|er)?\s+(?:passes|passed|is\s+clean|reports no)|no\s+(?:lint|type|mypy|eslint|ruff)\s+(?:errors|warnings|issues)"
        r"|type[- ]?check(?:s|ing)?\s+(?:passes|passed|is\s+clean)|(?:mypy|tsc|eslint|ruff|flake8|clippy)\s+(?:passes|passed|is\s+clean|reports no))",
        re.IGNORECASE)),
    ("bug_fixed", re.compile(r"\b(?:fixed|resolved|repaired|patched)\s+(?:the\s+|a\s+|this\s+|an?\s+)?(?:[\w-]+\s+){0,3}?(?:bug|issue|error|problem|crash|regression|failure|exception|leak)", re.IGNORECASE)),
    ("code_changed", re.compile(
        r"\b(?:implemented|added|updated|modified|changed|refactored|rewrote|edited|removed|renamed|introduced)\b|\bchanges\s+made\s+to\b",
        re.IGNORECASE)),
    ("committed", re.compile(r"\b(?:committed|made\s+a\s+commit|created\s+a\s+commit|commit(?:ted)?\s+(?:the\s+)?changes)\b|\bin\s+commit\s+[0-9a-f]{7,40}\b", re.IGNORECASE)),
    ("pushed", re.compile(r"\bpushed\b", re.IGNORECASE)),
    ("pr_opened", re.compile(r"\b(?:opened|created|submitted|raised)\s+(?:a\s+|the\s+)?(?:new\s+)?(?:pull\s+request|PR|merge\s+request|MR)\b|/pull/\d+|\b(?:pull\s+request|PR)\s+is\s+(?:now\s+)?up\b", re.IGNORECASE)),
    ("deployed", re.compile(
        r"\b(?:deployed|shipped|rolled\s+out|released\s+to\s+(?:production|prod|staging))\b|\bdeployment(?:\s+to\s+\w+)?\s+(?:succeeded|was\s+successful|is\s+(?:live|complete))\b"
        r"|(?:\b(?:is|are)|'s)\s+(?:now\s+)?live\s+(?:on|at|in)\b",
        re.IGNORECASE)),
    ("released", re.compile(
        r"\b(?:published|released|tagged)\s+(?:version\s+|release\s+)?v?\d+\.\d+|\bversion\s+v?\d+\.\d+\S*\s+is\s+(?:now\s+)?released\b|\bcreated\s+(?:a\s+)?tag\s+v?\d|\bpublished\s+(?:it\s+|the\s+package\s+)?(?:to|on)\s+(?:pypi|npm|crates\.io|the\s+registry)\b"
        r"|\bcreated\s+(?:a\s+|the\s+)?(?:github\s+)?release\b",
        re.IGNORECASE)),
    ("file_created", re.compile(r"\b(?:generated|created|wrote|produced|exported|saved)\s+(?:the\s+|a\s+|an\s+)?(?:\w+\s+){0,3}?(?:file|report|document|pdf|spreadsheet|csv|xlsx|docx|`)|\breport\s+is\s+at\s+`", re.IGNORECASE)),
    ("task_completed", re.compile(r"\b(?:task\s+is\s+(?:now\s+)?(?:complete|completed|done|finished)|(?:everything|all)\s+(?:is\s+)?(?:working|done|complete)|i(?:'ve| have)\s+completed\s+the\s+task|that\s+completes\s+the\s+task)\b", re.IGNORECASE)),
]  # fmt: skip


# "without errors", "0 failed": negative words that report success.
POSITIVE_NEGATIVES_RE = re.compile(r"\bwithout\s+errors\b|\b0\s+fail(?:ed|ures?)?\b", re.IGNORECASE)


def _sentences(text: str) -> Iterator[tuple[int, int, str]]:
    pos = 0
    for m in [*SENTENCE_END_RE.finditer(text), None]:
        end = m.start() if m else len(text)
        chunk = text[pos:end]
        if chunk.strip():
            start = pos + (len(chunk) - len(chunk.lstrip()))
            yield start, start + len(chunk.strip()), chunk.strip()
        if m:
            pos = m.end()


def _details(kind: ClaimType, sentence: str) -> dict[str, Any]:
    d: dict[str, Any] = {}
    paths = [a or b for a, b in PATH_RE.findall(sentence)]
    if paths and kind in ("code_changed", "bug_fixed", "file_created"):
        d["files"] = sorted(set(paths))
    if kind == "file_created" and paths:
        d["path"] = paths[0]
    if kind in ("committed", "pushed", "deployed"):
        shas = SHA_RE.findall(sentence)
        if shas:
            d["commit"] = shas[0]
    if kind == "pushed":
        m = re.search(r"\bto\s+(?:the\s+)?(?:branch\s+)?`?([\w./-]+)`?", sentence, re.IGNORECASE)
        if m and m.group(1).lower() not in ("the", "remote", "origin", "github"):
            d["branch"] = m.group(1).rstrip(".,;:")
    if kind == "pr_opened":
        m = PR_RE.search(sentence)
        if m:
            d["pr"] = int(m.group(1) or m.group(2))
    if kind == "deployed":
        m = ENV_RE.search(sentence)
        if m:
            env = m.group(1).lower()
            d["environment"] = {"prod": "production", "stage": "staging"}.get(env, env)
    if kind == "released":
        m = VERSION_RE.search(sentence)
        if m:
            d["version"] = m.group(1)
    if kind == "tests_passed":
        m = COUNT_RE.search(sentence)
        if m:
            d["count"] = int(m.group(1))
    if HEDGE_RE.search(sentence):
        d["hedged"] = True
    return d


def extract_claims(message: str) -> list[Claim]:
    """Typed claims in ``message`` (at most one claim of each type per sentence)."""
    claims: list[Claim] = []
    for start, end, sentence in _sentences(message):
        if sentence.endswith("?"):
            continue
        for kind, pattern in PATTERNS:
            m = pattern.search(sentence)
            if not m:
                continue
            # "tests are still failing", "I couldn't deploy": negation near the matched words
            window = POSITIVE_NEGATIVES_RE.sub(" ", sentence[max(0, m.start() - 40) : m.end() + 25])
            if NEGATION_RE.search(window):
                continue
            if kind == "code_changed" and not (PATH_RE.search(sentence) or re.search(
                r"\b(?:function|method|class|endpoint|test|feature|support|handler|check|validation|fix|option|flag|module|component|config)\b",
                sentence, re.IGNORECASE)):  # fmt: skip
                continue  # "I added a note" is not a code change
            claims.append(
                Claim(
                    id=f"c{len(claims) + 1}",
                    type=kind,
                    text=sentence,
                    span=(start, end),
                    details=_details(kind, sentence),
                )
            )
    return claims
