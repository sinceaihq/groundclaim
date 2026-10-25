"""Test reports: JUnit XML and CTRF (Common Test Report Format) JSON."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

MAX_REPORT_BYTES = 50_000_000


class ReportError(ValueError):
    pass


@dataclass
class TestRun:
    path: str
    format: str  # "junit" or "ctrf"
    tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    time: str | None = None  # when the run happened, if the report says
    revision: str | None = None  # commit the run was for, if the report says
    tool: str | None = None
    failing: list[str] = field(default_factory=list)  # names of failing tests (first 20)

    @property
    def ok(self) -> bool:
        return self.tests > 0 and self.failed == 0 and self.errors == 0 and self.passed > 0


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_junit(data: bytes, path: str) -> TestRun:
    head = data[:2000].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise ReportError("JUnit reports with a DTD are not accepted")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ReportError(f"not valid XML: {exc}") from exc
    cases = [el for el in root.iter() if _local(el.tag) == "testcase"]
    failed = errors = skipped = 0
    failing: list[str] = []
    for case in cases:
        kinds = {_local(ch.tag) for ch in case}
        name = f"{case.get('classname', '')}::{case.get('name', '')}".strip(":")
        if "failure" in kinds:
            failed += 1
            failing.append(name)
        elif "error" in kinds:
            errors += 1
            failing.append(name)
        elif "skipped" in kinds:
            skipped += 1
    if cases:
        tests = len(cases)
    else:  # aggregate attributes only
        suites = [el for el in root.iter() if _local(el.tag) in ("testsuite", "testsuites")]
        top = suites[0] if suites else root
        tests = int(top.get("tests", 0))
        failed = int(top.get("failures", 0))
        errors = int(top.get("errors", 0))
        skipped = int(top.get("skipped", top.get("disabled", 0)))
    time = None
    revision = None
    for el in root.iter():
        if time is None and el.get("timestamp"):
            time = el.get("timestamp")
        if _local(el.tag) == "property" and (el.get("name") or "").lower() in (
            "commit",
            "git.commit",
            "revision",
            "sha",
            "git_sha",
        ):
            revision = el.get("value")
    return TestRun(path, "junit", tests, tests - failed - errors - skipped, failed, errors, skipped, time, revision,
                   None, failing[:20])  # fmt: skip


def parse_ctrf(data: bytes, path: str) -> TestRun:
    try:
        doc = json.loads(data)
        results = doc["results"]
        summary = results["summary"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ReportError("not a CTRF report") from exc
    failing = [t.get("name", "") for t in results.get("tests", []) if t.get("status") == "failed"][:20]
    env = results.get("environment") or {}
    start = summary.get("start")
    time = None
    if isinstance(start, (int, float)) and start > 0:
        import datetime as dt

        time = dt.datetime.fromtimestamp(start / 1000, dt.timezone.utc).isoformat()
    other = int(summary.get("other", 0))
    return TestRun(
        path, "ctrf", int(summary.get("tests", 0)), int(summary.get("passed", 0)), int(summary.get("failed", 0)),
        other, int(summary.get("skipped", 0)) + int(summary.get("pending", 0)), time,
        env.get("commit") or env.get("revision"), (results.get("tool") or {}).get("name"), failing,
    )  # fmt: skip


def load_report(path: Path) -> TestRun:
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise ReportError("report is too large")
    data = path.read_bytes()
    stripped = data.lstrip()
    if stripped.startswith(b"{"):
        return parse_ctrf(data, str(path))
    if stripped.startswith(b"<"):
        return parse_junit(data, str(path))
    raise ReportError("unknown report format (expected JUnit XML or CTRF JSON)")


SHA_LIKE = re.compile(r"^[0-9a-f]{7,40}$")
