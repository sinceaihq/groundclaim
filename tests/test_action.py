"""The GitHub Action entry point, run locally with a simulated pull_request event."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from .conftest import Workspace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "action_check.py"


def load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("action_check", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pull_request_body_is_checked(ws: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws.write("app.py", "def f():\n    return 2\n")
    ws.commit("change")
    marker = tmp_path / "pwned"
    body = (f"- Updated `app.py`.\n- I committed the changes. $(touch {marker}) `touch {marker}`\n"
            "- Deployed to production.\n- I created `missing.txt`.")  # fmt: skip
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"body": body, "base": {"sha": ws.base}}}))
    summary, output = tmp_path / "summary.md", tmp_path / "output.txt"
    monkeypatch.chdir(ws.path)
    for k, v in {"GITHUB_EVENT_PATH": str(event), "RUNNER_TEMP": str(tmp_path), "GITHUB_STEP_SUMMARY": str(summary),
                 "GITHUB_OUTPUT": str(output), "GC_REQUIRE": "none"}.items():  # fmt: skip
        monkeypatch.setenv(k, v)
    for k in ("GC_MESSAGE", "GC_MESSAGE_FILE", "GITHUB_REPOSITORY", "GC_TRACE"):
        monkeypatch.delenv(k, raising=False)
    code = load().run()
    assert code == 1  # missing.txt is contradicted
    assert not marker.exists()
    text = summary.read_text()
    assert "GroundClaim" in text and "contradicted" in text
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert outputs["contradicted"] == "1" and Path(outputs["report"]).is_file()
    verdicts = {
        a["claim"]["type"]: a["verdict"]
        for a in json.loads(Path(outputs["report"]).read_text())["assessments"]
    }
    assert verdicts == {"code_changed": "confirmed", "committed": "confirmed", "deployed": "unverifiable",
                        "file_created": "contradicted"}  # fmt: skip


def test_nothing_to_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"push": {}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    for k in ("GC_MESSAGE", "GC_MESSAGE_FILE", "GC_TRACE", "GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(k, raising=False)
    assert load().run() == 0
