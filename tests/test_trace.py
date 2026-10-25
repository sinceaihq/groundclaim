from __future__ import annotations

import json
from pathlib import Path

import pytest

from groundclaim.trace import (
    TraceError,
    classify_command,
    final_message,
    load_trace,
    parse_test_output,
    redact,
)


@pytest.mark.parametrize(
    ("command", "cats", "flags"),
    [
        ("pytest -q", {"test"}, set()),
        ("uv run pytest tests/ -k foo", {"test"}, {"subset"}),
        ("cd app && npm test", {"test"}, set()),
        ("pytest | tail -5", {"test"}, {"exit_masked"}),
        ("pytest || true", {"test"}, {"exit_masked"}),
        ("set -o pipefail; pytest | tee log", {"test"}, set()),
        ("echo 'All tests passed'", {"fake_report"}, set()),
        ("npm run build", {"build"}, set()),
        ("npx tsc --noEmit", {"lint"}, set()),
        ("ruff check . && mypy src", {"lint"}, set()),
        ("git commit -am 'fix'", {"commit"}, set()),
        ("git push origin main", {"push"}, set()),
        ("gh pr create --fill", {"pr"}, set()),
        ("vercel --prod", {"deploy"}, set()),
        ("gh release create v1.2.0", {"release"}, set()),
        ("timeout 300 cargo test", {"test"}, set()),
        ("ls -la", set(), set()),
    ],
)
def test_classify_command(command: str, cats: set[str], flags: set[str]) -> None:
    assert classify_command(command) == (cats, flags)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("=== 3 failed, 120 passed, 2 skipped in 4.20s ===", {"passed": 120, "failed": 3, "skipped": 2}),
        ("120 passed in 1.2s", {"passed": 120}),
        ("Tests:       2 failed, 1 skipped, 40 passed, 43 total", {"passed": 40, "failed": 2, "skipped": 1}),
        ("      Tests  2 failed | 40 passed (42)", {"passed": 40, "failed": 2}),
        (
            "test result: ok. 10 passed; 0 failed; 1 ignored; 0 measured",
            {"passed": 10, "failed": 0, "skipped": 1},
        ),
        ("Ran 12 tests in 0.1s\n\nFAILED (failures=1, errors=2)", {"passed": 9, "failed": 3, "skipped": 0}),
        ("  40 passing (2s)\n  2 failing", {"passed": 40, "failed": 2}),
        ("nothing here", None),
    ],
)
def test_parse_test_output(output: str, expected: dict[str, int] | None) -> None:
    assert parse_test_output(output) == expected


def test_redact() -> None:
    # fake tokens, assembled at runtime so that no token-shaped literal is in the source
    gh_token, sk_token = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123", "sk-" + "abcdefghijklmnopqrstuvwxyz"
    text = f"git push https://user:{gh_token}@github.com/x token=abc123 {sk_token}"
    out = redact(text)
    assert "ghp_" not in out and "abc123" not in out and "sk-abc" not in out


def _write(tmp_path: Path, name: str, rows: list[object]) -> Path:
    p = tmp_path / name
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def test_groundclaim_jsonl(tmp_path: Path) -> None:
    p = _write(tmp_path, "run.jsonl", [
        {"type": "file_write", "path": "a.py"},
        {"type": "command", "command": "pytest -q", "exit_code": 0, "output": "3 passed in 0.1s"},
        {"type": "message", "role": "assistant", "text": "All tests pass."},
    ])  # fmt: skip
    fmt, events = load_trace(p)
    assert fmt == "groundclaim"
    assert [e.kind for e in events] == ["file_write", "command", "message"]
    assert events[1].exit_code == 0 and "test" in events[1].categories
    assert final_message(events) == "All tests pass."


def test_claude_code_transcript(tmp_path: Path) -> None:
    p = _write(tmp_path, "session.jsonl", [
        {"type": "assistant", "sessionId": "s", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest -q"}}]}},
        {"type": "user", "sessionId": "s", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "Exit code 1\n1 failed, 2 passed in 0.3s", "is_error": True}]}},
        {"type": "assistant", "sessionId": "s", "message": {"content": [
            {"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "/w/a.py"}}]}},
        {"type": "assistant", "sessionId": "s", "message": {"content": [{"type": "text", "text": "Done, tests pass."}]}},
    ])  # fmt: skip
    fmt, events = load_trace(p)
    assert fmt == "claude-code"
    cmd = events[0]
    assert cmd.command == "pytest -q" and cmd.exit_code == 1 and "1 failed" in cmd.output
    assert events[1].kind == "file_write" and events[1].path == "/w/a.py"
    assert final_message(events) == "Done, tests pass."


def test_otel_genai_spans(tmp_path: Path) -> None:
    otlp = {"resourceSpans": [{"scopeSpans": [{"spans": [
        {"name": "execute_tool shell", "startTimeUnixNano": "2", "attributes": [
            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
            {"key": "gen_ai.tool.name", "value": {"stringValue": "shell"}},
            {"key": "gen_ai.tool.call.arguments", "value": {"stringValue": json.dumps({"command": "npm test"})}},
            {"key": "gen_ai.tool.call.result", "value": {"stringValue": json.dumps({"exit_code": 0, "stdout": "ok"})}},
        ]},
    ]}]}]}  # fmt: skip
    p = tmp_path / "spans.json"
    p.write_text(json.dumps(otlp))
    fmt, events = load_trace(p)
    assert fmt == "spans" and events[0].command == "npm test" and events[0].exit_code == 0


def test_openinference_spans(tmp_path: Path) -> None:
    p = _write(tmp_path, "oi.jsonl", [{"name": "tool", "span_id": "1", "start_time": "1", "attributes": {
        "openinference.span.kind": "TOOL", "tool.name": "bash",
        "input.value": json.dumps({"command": "go test ./..."}), "output.value": json.dumps({"returncode": 2})}}])  # fmt: skip
    fmt, events = load_trace(p)
    assert fmt == "spans" and events[0].exit_code == 2 and "test" in events[0].categories


def test_unknown_trace(tmp_path: Path) -> None:
    p = _write(tmp_path, "x.jsonl", [{"hello": "world"}])
    with pytest.raises(TraceError):
        load_trace(p)


def test_output_is_redacted_in_events(tmp_path: Path) -> None:
    p = _write(tmp_path, "run.jsonl", [{"type": "command", "command": "curl -H 'token=abcdef123456'", "exit_code": 0,
                                        "output": "AKIA" + "ABCDEFGHIJKLMNOP"}])  # fmt: skip
    _, events = load_trace(p)
    assert "abcdef123456" not in (events[0].command or "") and "AKIA" not in events[0].output


def test_truncated_private_key_is_redacted() -> None:
    out = redact("key: -----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAA")
    assert "b3Blbn" not in out and out.startswith("key: [redacted]")


def test_adversarial_inputs_are_fast() -> None:
    import time

    from groundclaim.claims import extract_claims

    t = time.monotonic()
    extract_claims("All tests pass " + "a " * 100000 + ".")
    extract_claims("Committed (" + "x) (" * 20000 + "y).")
    extract_claims("1." * 50000)
    redact("-----BEGIN RSA PRIVATE KEY-----" * 5000)
    redact("https://a:b@" * 20000)
    classify_command("pytest " + "| cat " * 20000)
    parse_test_output("1 passed " * 50000)
    assert time.monotonic() - t < 5
