from __future__ import annotations

import json
from pathlib import Path

import pytest

from groundclaim import Recorder
from groundclaim.cli import main
from groundclaim.render import report_from_dict, to_html, to_markdown

from .conftest import Workspace


def run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(args)
    out, err = capsys.readouterr()
    return code, out, err


def test_exit_codes_and_json(ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    ws.cmd("pytest -q", 1, "1 failed in 0.1s")
    trace = ws.save_trace()
    code, out, err = run(
        ["check", "--repo", str(ws.path), "--trace", str(trace), "-m", "All tests pass.", "-f", "json"],
        capsys,
    )
    assert code == 1 and "contradicted" in err
    data = json.loads(out)
    assert data["schema_version"] == "0.1" and data["assessments"][0]["verdict"] == "contradicted"
    code, _, _ = run(["check", "--repo", str(ws.path), "-m", "Hello there."], capsys)
    assert code == 0


def test_require_policy(ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    ws.write("app.py", "def f():\n    return 2\n")
    ws.cmd("pytest -q", 0, "3 passed in 0.1s")
    trace = ws.save_trace()
    base = ["check", "--repo", str(ws.path), "--trace", str(trace), "-m", "All tests pass."]
    assert run(base, capsys)[0] == 0
    assert run([*base, "--require", "supported"], capsys)[0] == 0
    assert run([*base, "--require", "confirmed"], capsys)[0] == 1


def test_message_from_trace_and_outputs(
    ws: Workspace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws.cmd("pytest -q", 0, "3 passed in 0.1s")
    ws.trace.append(
        {"type": "message", "role": "assistant", "text": "All tests pass <script>alert(1)</script>."}
    )
    trace = ws.save_trace()
    html_path = tmp_path / "r.html"
    code, out, _ = run(["check", "--repo", str(ws.path), "--trace", str(trace), "-f", "markdown",
                        "--also", f"html={html_path}", "--also", f"json={tmp_path / 'r.json'}"], capsys)  # fmt: skip
    assert code == 0 and "<script>" not in out
    page = html_path.read_text()
    assert "<script>" not in page and "&lt;script&gt;" in page and "default-src 'none'" in page
    code, out, _ = run(["render", str(tmp_path / "r.json"), "-f", "text"], capsys)
    assert code == 0 and "supported" in out


def test_bad_inputs_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "t.jsonl"
    bad.write_text("not json\n")
    assert run(["check", "--trace", str(bad), "-m", "x"], capsys)[0] == 2
    assert run(["check", "--no-git"], capsys)[0] == 2
    assert run(["check", "--repo", str(tmp_path), "-m", "x"], capsys)[0] == 2
    assert run(["check", "--no-git", "-m", "x", "--github", "not a repo"], capsys)[0] == 2


def test_claims_and_schema(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["claims", "All tests pass. Deployed to prod."], capsys)
    assert code == 0 and [c["type"] for c in json.loads(out)] == ["tests_passed", "deployed"]
    code, out, _ = run(["schema"], capsys)
    assert code == 0 and json.loads(out)["title"] == "GroundClaim report"


def test_report_matches_schema(ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    ws.cmd("pytest -q", 0, "3 passed in 0.1s")
    trace = ws.save_trace()
    _, out, _ = run(["check", "--repo", str(ws.path), "--base", ws.base, "--trace", str(trace), "-f", "json",
                     "-m", "All tests pass. I committed the changes. I created `x.txt`. The task is complete."], capsys)  # fmt: skip
    _, schema, _ = run(["schema"], capsys)
    jsonschema.validate(json.loads(out), json.loads(schema))


def test_recorder_round_trip(ws: Workspace, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "run.jsonl"
    with Recorder(path) as rec:
        proc = rec.run(["git", "-C", str(ws.path), "status", "--short"])
        assert proc.returncode == 0
        rec.command("pytest -q", 0, "3 passed in 0.1s password=hunter22")
        rec.message("All tests pass.")
    assert "hunter22" not in path.read_text()
    code, out, _ = run(["check", "--repo", str(ws.path), "--trace", str(path)], capsys)
    assert code == 0 and "supported" in out


def test_markdown_escapes_agent_text() -> None:
    report = report_from_dict({"schema_version": "0.1", "subject": {}, "evidence": [], "warnings": ["a|b"],
        "assessments": [{"claim": {"id": "c1", "type": "tests_passed", "text": "| ![x](http://e/x) <img src=x> `c`",
                                   "span": [0, 1], "details": {}}, "verdict": "supported", "reason": "r", "links": []}]})  # fmt: skip
    md = to_markdown(report)
    assert "<img" not in md and "![x]" not in md and "\\|" in md
    assert "<img" not in to_html(report)


def test_wait_for_checks_polls_until_finished(monkeypatch: pytest.MonkeyPatch) -> None:
    from groundclaim import cli
    from groundclaim.github import GitHub

    calls = {"n": 0}

    def transport(path: str) -> tuple[int, object]:
        calls["n"] += 1
        status = "completed" if calls["n"] >= 3 else "in_progress"
        return 200, {
            "check_runs": [{"name": "test", "status": status}, {"name": "me", "status": "in_progress"}]
        }

    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    cli._wait_for_checks(GitHub("o/r", transport), "abc1234", {"me"}, timeout=60)
    assert calls["n"] == 3
