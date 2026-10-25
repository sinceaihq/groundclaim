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

# A sentence ends at ., ! or ? followed by whitespace and not by a lower-case word (so not inside "pager.py",
# "1.4.0" or "go test ./... passes"), or at a line break.
SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?![a-z])|\n+")
NEGATION_RE = re.compile(
    r"\b(?:not|n't|never|no longer|unable|failed to|fails?|failing|could not|couldn't|cannot|can't|did not|didn't|"
    r"won't|haven't|hasn't|without|except|but \d+ fail)\b",
    re.IGNORECASE,
)
HEDGE_RE = re.compile(
    r"\b(?:should|would|might|may|probably|likely|i think|i believe|seems?|appears?)\b", re.IGNORECASE
)
PATH_RE = re.compile(
    r"`([^`\s]+\.[A-Za-z0-9]{1,8}|(?:[\w.-]+/)*(?:Dockerfile|Makefile|Procfile|Jenkinsfile|Gemfile|Containerfile))`|(?<![\w/.-])((?:[\w.-]+/)*[\w-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|kt|rb|php|cs|c|h|cpp|md|json|yml|yaml|toml|sql|sh|html|css|txt|csv|pdf|xlsx|docx))(?![\w/])"
)
SHA_RE = re.compile(r"(?<![0-9A-Za-z])((?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40})(?![0-9A-Za-z])")
VERSION_RE = re.compile(r"\bv?(\d+\.\d+(?:\.\d+)?(?:[-.]?(?:rc|a|b|alpha|beta|dev)\.?\d*)?)\b")
PR_RE = re.compile(r"(?:\bPR|pull request|merge request|MR)\s*#?\s*(\d+)|/pull/(\d+)|#(\d+)", re.IGNORECASE)
COUNT_RE = re.compile(
    r"\b(\d+)\s+(?:of\s+\d+\s+)?(?:(?:unit |integration |e2e )?tests?\b|passed\b)", re.IGNORECASE
)
ENV_RE = re.compile(
    r"\b(production|prod|staging|stage|preview|dev(?:elopment)?|test(?:ing)? environment|qa)\b", re.IGNORECASE
)

# (type, pattern). Patterns are matched against one sentence at a time.
_CI = r"(?:the\s+)?(?:ci|pipeline|workflow|github\s+actions|actions|checks?)(?:\s+(?:run|build|checks?|jobs?|pipeline))?"
_OK = r"(?:is\s+|are\s+|has\s+|have\s+)?(?:now\s+)?(?:all\s+)?(?:green|passing|passes|pass|passed|succeeded|successful)"
PATTERNS: list[tuple[ClaimType, re.Pattern[str]]] = [
    ("tests_passed", re.compile(
        r"\b(?:all\s+(?:of\s+)?(?:the\s+)?(?:\d+\s+)?(?:unit\s+|integration\s+|e2e\s+|smoke\s+)?(?:and\s+\w+\s+)?tests?\s+(?:now\s+)?(?:pass|passed|passing|succeed|are\s+green|are\s+passing)"
        r"|(?:every|each)\s+(?:single\s+)?test\b(?:\s+in\s+\S+)?\s+(?:now\s+)?(?:passes|passed)"
        r"|tests?\s+(?:are\s+|is\s+)?(?:now\s+)?(?:passing|green|all\s+pass)"
        r"|tests?\s+(?:now\s+)?(?:all\s+)?pass(?:es|ed)?\b"
        r"|tests?\s+(?:should|will|now)\s+(?:all\s+)?(?:now\s+)?pass"
        r"|(?:test\s+suite|tests|test\s+run|pytest|jest|vitest|npm\s+test|go\s+test|cargo\s+test|unit\s+tests|make\s+test)`?(?:\s+\./\.\.\.)?\s+(?:now\s+)?(?:is\s+)?(?:passes|passed|passing|succeeds|succeeded|green|clean)"
        r"|\btests?:\s*(?:✅|passing|pass|green|ok)\b|\beverything\s+passes\b"
        r"|\d+\s+(?:of\s+\d+\s+)?(?:\w+\s+)?tests?\s+passed|\d+\s+pass(?:ed|ing)\b|test\s+suite:?\s*(?:✅|passing)"
        r"|" + _CI + r"\s+" + _OK + r")",
        re.IGNORECASE)),
    ("build_succeeded", re.compile(
        r"\b(?:build\s+(?:now\s+)?(?:is\s+)?(?:succeeds|succeeded|passes|passed|works|green|successful|ok)\b|builds?\s+(?:cleanly|successfully|without\s+errors)"
        r"|compil(?:es?|ation)\s+(?:cleanly|successfully|succeeds|without\s+errors)|successfully\s+(?:built|compiled)"
        r"|build(?:\s+--?[\w-]+)*`?\s+(?:completes|completed|finished)\s+(?:successfully|without)|build:\s*✅|\bbuild\s+compiles\b)",
        re.IGNORECASE)),
    ("lint_clean", re.compile(
        r"\b(?:lint(?:ing|er)?\s+(?:passes|passed|is\s+clean|reports\s+no)|no\s+(?:lint|type|mypy|eslint|ruff)\s+(?:errors|warnings|issues)"
        r"|type[- ]?check(?:s|ing)?\s+(?:passes|passed|is\s+clean)|(?:mypy|tsc|eslint|ruff|flake8|clippy|pylint|prettier)(?:\s+check)?`?\s+(?:passes|passed|is\s+clean|reports\s+no))",
        re.IGNORECASE)),
    ("bug_fixed", re.compile(
        r"\b(?:fixed|resolved|repaired|patched)\s+(?:the\s+|a\s+|this\s+|an?\s+)?(?:[\w-]+\s+){0,3}?(?:bug|issue|error|problem|crash|regression|failure|exception|leak|race|vulnerability|injection)"
        r"|\b(?:bug|issue|error|crash|regression|leak)\b(?:\s+[\w-]+){0,4}?\s+(?:is|has\s+been|was)\s+(?:now\s+)?fixed|\bfixes\s+(?:#\d+|(?:the\s+|a\s+)?(?:[\w-]+\s+){0,3}?(?:bug|crash|issue|error|regression|leak))|\bresolved\s+(?:issue\s+)?#\d+|^bug\s+fixed\b",
        re.IGNORECASE)),
    ("code_changed", re.compile(
        r"\b(?:implemented|added|updated|modified|changed|refactored|rewrote|edited|removed|renamed|introduced|migrated)\b"
        r"|\bchanges?\s+(?:made|applied)\s+(?:to|in)\b|\bmade\s+(?:the\s+)?(?:\w+\s+)?changes\b|\bis\s+implemented\b|\bwrote\s+(?:\w+\s+)?tests\b",
        re.IGNORECASE)),
    ("committed", re.compile(
        r"\b(?:committed|made\s+(?:a|two|\d+)\s+commits?|created\s+a\s+commit|commit(?:ted)?\s+(?:the\s+)?changes)\b|\bin\s+commit\s+[0-9a-f]{7,40}\b",
        re.IGNORECASE)),
    ("pushed", re.compile(r"\bpushed\b", re.IGNORECASE)),
    ("pr_opened", re.compile(
        r"\b(?:opened|created|submitted|raised)\s+(?:a\s+|the\s+)?(?:new\s+|draft\s+)?(?:pull\s+request|PR|merge\s+request|MR)\b|/pull/\d+"
        r"|\b(?:pull\s+request|PR|merge\s+request|MR)\s+(?:#\d+\s+)?(?:is\s+)?(?:now\s+)?(?:up|open|opened|created)\b",
        re.IGNORECASE)),
    ("deployed", re.compile(
        r"\b(?:deployed|shipped|rolled\s+out|released\s+to\s+(?:production|prod|staging))\b"
        r"|\bdeploy(?:ment)?(?:\s+(?:to|on)\s+\w+)?\s+(?:succeeded|was\s+successful|completed|finished|is\s+(?:live|complete|done))\b"
        r"|(?:\b(?:is|are)|'s)\s+(?:now\s+)?live\s+(?:on|at|in)\b|\brollout\s+(?:finished|completed|succeeded)\b",
        re.IGNORECASE)),
    ("released", re.compile(
        r"\b(?:published|released|tagged|cut)\s+(?:the\s+)?(?:version\s+|release\s+)?v?\d+\.\d+|\bpublished\s+(?:it\s+|the\s+package\s+)?(?:to|on)\s+(?:pypi|npm|crates\.io|the\s+registry)\b"
        r"|\bcreated\s+(?:a\s+|the\s+)?(?:github\s+)?release\b|\b(?:created|pushed|added)\s+(?:a\s+|the\s+)?tag\s+v?\d"
        r"|\bv?\d+\.\d+\S{0,20}\s+(?:is|has\s+been|was)\s+(?:now\s+)?(?:tagged|released|published|out)\b|\bv?\d+\.\d+\S{0,20}\s+release\s+is\s+(?:now\s+)?(?:out|live|published)\b"
        r"|\b(?:version|release)\s+v?\d+\.\d+\S{0,20}\s+(?:is\s+|was\s+)?(?:now\s+)?(?:published|released|out)\b|\bcut\s+(?:a\s+|the\s+)?release\b|\bv?\d+\.\d+\S{0,20}\s+and\s+released\s+it\b",
        re.IGNORECASE)),
    ("file_created", re.compile(
        r"\b(?:generated|created|wrote|produced|exported|saved)\s+(?:the\s+|a\s+|an\s+)?(?:[\w,-]+\s+){0,5}?(?:file|report|document|pdf|spreadsheet|csv|xlsx|docx|`)"
        r"|`[^`\s]+\.[A-Za-z0-9]{1,8}`\s+\((?:generated|created|new)\)"
        r"|\b(?:is|are|was|were)\s+(?:now\s+)?(?:written|saved|generated|exported)\s+(?:to|at|in|as)\s+`"
        r"|\b(?:report|output|file|results?|chart|export)\s+is\s+(?:now\s+)?(?:at|in)\s+`|\bnew\s+file\s+`",
        re.IGNORECASE)),
    ("task_completed", re.compile(
        r"\b(?:task\s+is\s+(?:now\s+)?(?:complete|completed|done|finished)|(?:everything|all)\s+(?:is\s+)?(?:working|done|complete)"
        r"|i(?:'ve|\s+have)\s+completed\s+(?:the\s+task|everything)|(?:that|this)\s+completes\s+the\s+(?:task|work)"
        r"|(?:the\s+)?task\s+is\s+(?:now\s+)?finished|(?:changes|work|implementation)\s+(?:is\s+|are\s+)?(?:now\s+)?(?:complete|completed|done|finished)"
        r"|ready\s+to\s+merge)\b|^(?:✅\s*)?done\b",
        re.IGNORECASE)),
]  # fmt: skip

# A sentence that is a plan, a condition or advice states no completion: "If the tests pass, ...",
# "I'll deploy after review", "You may want to release ...".
NOT_DONE_RE = re.compile(
    r"^(?:if|once|when|after|before|unless|until|to\s+\w+,)\b|\b(?:i'll|i\s+will|we'll|we\s+will|going\s+to|plan\s+to|about\s+to)\b"
    r"|^next\b|\b(?:want\s+me\s+to|you\s+(?:may|might|should|can|could)\s+(?:want\s+to\s+)?|please\b|let\s+me\s+know)",
    re.IGNORECASE,
)
# "without errors", "no failures", "0 failed", "the previously failing test": negative words that report success.
# Claims are short; only the start of very long "sentences" (pasted logs, minified code) is examined.
MAX_SENTENCE = 2000
ASIDE_RE = re.compile(r"\([^()]*\)")
POSITIVE_NEGATIVES_RE = re.compile(
    r"\bwithout\s+(?:any\s+)?(?:errors?|warnings?|failures?|issues?|problems?)\b|\bno\s+(?:errors?|warnings?|failures?|issues?)\b"
    r"|\b(?:0|zero)\s+(?:failed|failures?|errors?|warnings?)\b|\bpreviously\s+failing\b",
    re.IGNORECASE,
)


def _blank_asides(text: str, at: int) -> str:
    """Blank out parenthesised asides in ``text`` except the one containing offset ``at``."""
    return ASIDE_RE.sub(lambda p: p.group() if p.start() <= at < p.end() else " " * len(p.group()), text)


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
        # "PR #12", "pull request 12", ".../pull/12", or a "#12" anywhere in the sentence ("The PR is up: #12")
        m = PR_RE.search(sentence)
        if m:
            d["pr"] = int(m.group(1) or m.group(2) or m.group(3))
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
    """Typed claims in ``message`` (at most one claim of each type per sentence, one whole-task claim per message)."""
    claims: list[Claim] = []
    for start, end, sentence in _sentences(message):
        sentence = sentence[:MAX_SENTENCE]
        end = min(end, start + MAX_SENTENCE)
        if sentence.endswith("?") or NOT_DONE_RE.search(sentence):
            continue
        for kind, pattern in PATTERNS:
            m = pattern.search(sentence)
            if not m:
                continue
            if kind == "task_completed" and any(c.type == "task_completed" for c in claims):
                continue  # "Done! Everything is working." is one whole-task claim
            # "tests are still failing", "I couldn't deploy": negation near the matched words
            lo, hi = max(0, m.start() - 40), m.end() + 25
            window = sentence[lo:hi]
            # asides in parentheses that do not contain the claim do not negate it
            window = _blank_asides(window, m.start() - lo)
            window = POSITIVE_NEGATIVES_RE.sub(" ", window)
            if NEGATION_RE.search(window):
                continue
            if kind == "code_changed" and not (PATH_RE.search(sentence) or re.search(
                r"\b(?:functions?|methods?|class(?:es)?|endpoints?|tests?|features?|support|handlers?|checks?|validation|fix(?:es)?|options?|flags?|modules?|components?|config|client|parser|scripts?|retry|retries|logging|cache|logic|error\s+handling)\b",
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
