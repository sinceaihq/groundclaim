from __future__ import annotations

import json
from pathlib import Path

import pytest

from groundclaim.reports import ReportError, load_report

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="3" timestamp="2026-10-01T10:00:00">
<properties><property name="commit" value="abc1234"/></properties>
<testcase classname="t" name="a"/><testcase classname="t" name="b"><failure message="x"/></testcase>
<testcase classname="t" name="c"><skipped/></testcase>
</testsuite></testsuites>"""


def test_junit(tmp_path: Path) -> None:
    p = tmp_path / "r.xml"
    p.write_text(JUNIT)
    run = load_report(p)
    assert (run.tests, run.passed, run.failed, run.skipped) == (3, 1, 1, 1)
    assert run.revision == "abc1234" and run.time == "2026-10-01T10:00:00"
    assert run.failing == ["t::b"] and not run.ok


def test_junit_with_dtd_is_refused(tmp_path: Path) -> None:
    p = tmp_path / "r.xml"
    p.write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><testsuite>&a;</testsuite>')
    with pytest.raises(ReportError):
        load_report(p)


def test_ctrf(tmp_path: Path) -> None:
    p = tmp_path / "ctrf.json"
    p.write_text(json.dumps({"results": {
        "tool": {"name": "jest"},
        "summary": {"tests": 2, "passed": 2, "failed": 0, "skipped": 0, "pending": 0, "other": 0, "start": 1760000000000},
        "tests": [{"name": "a", "status": "passed"}, {"name": "b", "status": "passed"}],
        "environment": {"commit": "def5678"},
    }}))  # fmt: skip
    run = load_report(p)
    assert run.ok and run.tool == "jest" and run.revision == "def5678" and run.time


def test_unknown_report(tmp_path: Path) -> None:
    p = tmp_path / "r.txt"
    p.write_text("all good")
    with pytest.raises(ReportError):
        load_report(p)
