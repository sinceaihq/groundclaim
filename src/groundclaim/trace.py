"""Agent run traces → a list of events (commands, file writes, messages).

Traces are data, never instructions: commands found in a trace are classified
by their text and never executed.

Supported formats (detected automatically):

* GroundClaim JSONL — one event per line, see docs/TRACE_FORMAT.md;
* Claude Code session transcripts (JSONL) — Bash tool calls and their results,
  Edit/Write tool calls, assistant text. The format is not a published
  interface, so this adapter is best-effort;
* OpenTelemetry spans following the GenAI semantic conventions
  (``gen_ai.tool.*`` attributes), as OTLP JSON or one span per line;
* OpenInference spans (``openinference.span.kind = TOOL``).
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

MAX_TRACE_BYTES = 200_000_000
EventKind = Literal["command", "file_write", "message"]
Category = Literal["test", "build", "lint", "commit", "push", "pr", "deploy", "release", "fake_report"]


class TraceError(ValueError):
    pass


@dataclass
class Event:
    index: int  # position in the run (0 = first)
    kind: EventKind
    source: str  # "trace.jsonl#12"
    time: str | None = None
    command: str | None = None
    exit_code: int | None = None  # None = unknown (still running, interrupted, not recorded)
    output: str = ""
    path: str | None = None
    text: str | None = None  # assistant text for kind == "message"
    revision: str | None = None  # git HEAD when the event happened, if the trace records it
    categories: set[str] = field(default_factory=set)
    flags: set[str] = field(default_factory=set)  # "exit_masked", "subset", "background"


# --- secrets in stored snippets -------------------------------------------------------------

SECRET_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|hf_[A-Za-z0-9]{30,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,})"
    r"|(?i:(?<=password=)|(?<=passwd=)|(?<=token=)|(?<=secret=)|(?<=api_key=)|(?<=apikey=))[^\s&'\"]+"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    r"|(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"
)


def redact(text: str) -> str:
    return SECRET_RE.sub("[redacted]", text)


def snippet(text: str, limit: int = 600) -> str:
    """The end of a command's output (where test summaries are), with secrets removed."""
    text = text[-limit:] if len(text) > limit else text
    return redact(text)


# --- what a command does --------------------------------------------------------------------

_WRAPPERS = {"uv", "poetry", "pdm", "hatch", "pipenv", "npx", "pnpx", "bunx", "yarn", "pnpm", "npm", "bun", "time",
             "nice", "timeout", "env", "sudo", "xvfb-run", "dotenv", "rye", "nox", "tox", "make", "just", "task"}  # fmt: skip
TEST_RE = re.compile(
    r"^(?:pytest|py\.test|python\d?(?:\.\d+)? -m (?:pytest|unittest)|(?:npm|pnpm|yarn|bun) (?:run )?test(?::\S+)?|jest|vitest(?! bench)"
    r"|mocha|ava|tap|playwright test|cypress run|go test|cargo (?:test|nextest)|mvn(?:w)? (?:\S+ )*(?:test|verify)|gradlew? (?:\S+ )*test"
    r"|dotnet test|rspec|bundle exec rspec|rake test|phpunit|vendor/bin/phpunit|mix test|swift test|ctest|tox|nox|make (?:test|check)"
    r"|just test|deno test|bazel test|hatch (?:run )?test|uv run pytest|poetry run pytest)\b"
)
BUILD_RE = re.compile(
    r"^(?:(?:npm|pnpm|yarn|bun) run build|(?:npm|pnpm|yarn|bun) build|vite build|next build|tsc(?!.*--noemit)(?: -b| --build| -p)?"
    r"|cargo build|go build|mvn(?:w)? (?:\S+ )*(?:package|install|compile)|gradlew? (?:\S+ )*(?:build|assemble)|dotnet build"
    r"|python\d? -m build|uv build|poetry build|hatch build|docker build|make(?: all| build)?$|cmake --build|bazel build|webpack)\b"
)
LINT_RE = re.compile(
    r"^(?:ruff(?: check)?|flake8|pylint|mypy|pyright|black --check|eslint|(?:npm|pnpm|yarn|bun) run (?:lint|typecheck|check)"
    r"|tsc (?:\S+ )*--noemit|prettier (?:\S+ )*--check|cargo clippy|cargo fmt -- --check|golangci-lint|go vet|rubocop|stylelint"
    r"|biome (?:check|lint)|shellcheck|hadolint|make lint)\b"
)
DEPLOY_RE = re.compile(
    r"^(?:vercel(?: deploy)?(?: --prod)?|netlify deploy|fly(?:ctl)? deploy|kubectl (?:apply|rollout)|helm (?:upgrade|install)"
    r"|terraform apply|pulumi up|serverless deploy|sls deploy|gcloud (?:app deploy|run deploy|functions deploy)|firebase deploy"
    r"|wrangler (?:deploy|publish)|railway up|heroku |cdk deploy|sam deploy|ansible-playbook|eb deploy|az webapp)"
)
RELEASE_RE = re.compile(
    r"^(?:gh release create|npm publish|pnpm publish|yarn publish|twine upload|uv publish|poetry publish|cargo publish|git tag\b|hatch publish)"
)
FAKE_RE = re.compile(
    r"^(?:echo|printf|cat\s*<<|true|:)\b.*\b(?:pass|passed|passing|success|succeeded|ok|green|deployed|built)\b",
    re.IGNORECASE,
)
SUBSET_RE = re.compile(
    r"(?:^|\s)(?:-k|--lf|--last-failed|-t|--testnamepattern|--grep|-run|--filter|--only)(?:\s|=|$)|::\w|\.only\b"
)


def _known(seg: str) -> bool:
    return any(r.match(seg) for r in (TEST_RE, BUILD_RE, LINT_RE, RELEASE_RE, DEPLOY_RE))


def _segments(command: str) -> list[str]:
    """Split a shell command line into simple commands (best effort, no shell is run)."""
    parts = re.split(r"\s*(?:&&|\|\||;|\n|(?<!\|)\|(?!\|))\s*", command)
    out = []
    for part in parts:
        try:
            words = shlex.split(part, posix=True)
        except ValueError:
            words = part.split()
        # drop VAR=value prefixes and wrappers like "uv run", "npx", "timeout 60" until a known tool is first
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]
        while len(words) > 1 and words[0] in _WRAPPERS and not _known(" ".join(words).lower()):
            words = words[1:]
            if len(words) > 1 and words[0] in ("run", "exec", "x", "dlx"):
                words = words[1:]
            while words and re.match(r"^-|^\d+[smh]?$", words[0]):
                words = words[1:]
        if words:
            out.append(" ".join(words))
    return out


def classify_command(command: str) -> tuple[set[str], set[str]]:
    """(categories, flags) for a shell command line."""
    cats: set[str] = set()
    flags: set[str] = set()
    for seg in _segments(command):
        seg_l = seg.lower()
        if FAKE_RE.match(seg):
            cats.add("fake_report")
            continue
        if TEST_RE.match(seg_l):
            cats.add("test")
            if SUBSET_RE.search(seg_l):
                flags.add("subset")
        if BUILD_RE.match(seg_l):
            cats.add("build")
        if LINT_RE.match(seg_l):
            cats.add("lint")
        if re.match(r"^git (?:\S+ )*commit\b", seg_l):
            cats.add("commit")
        if re.match(r"^git (?:\S+ )*push\b", seg_l):
            cats.add("push")
        if re.match(r"^gh pr create\b", seg_l) or re.match(r"^glab mr create\b", seg_l):
            cats.add("pr")
        if DEPLOY_RE.match(seg_l):
            cats.add("deploy")
        if RELEASE_RE.match(seg_l):
            cats.add("release")
    if cats - {"fake_report"}:
        # The recorded exit code may not be the tool's: "pytest || true", "pytest | tail", "set +e"
        if re.search(r"\|\|\s*(?:true|:|exit 0|echo)|;\s*(?:true|exit 0)\s*$|set \+e", command) or \
                (re.search(r"(?<!\|)\|(?!\|)", command) and "pipefail" not in command):  # fmt: skip
            flags.add("exit_masked")
        if re.search(r"(?:^|\s)&\s*$|\bnohup\b", command):
            flags.add("background")
    return cats, flags


# --- what a test run printed ----------------------------------------------------------------

_COUNT = r"(\d+)\s+{}"


def parse_test_output(text: str) -> dict[str, int] | None:
    """Counts from the summary line of common test runners; None if no summary is found."""
    tail = text[-5000:]
    found: dict[str, int] = {}

    def grab(key: str, pattern: str, src: str) -> None:
        m = re.findall(pattern, src, re.M)
        if m:
            found[key] = int(m[-1])

    # pytest: "==== 3 failed, 120 passed, 2 skipped in 4.20s ====" or "-q" style "120 passed in 1.2s"
    py = re.findall(
        r"^[= ]*((?:\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)(?:, )?)+)(?: in [\d.]+s)",
        tail,
        re.M,
    )
    if py:
        line = py[-1]
        for key, word in (
            ("passed", "passed"),
            ("failed", "failed"),
            ("errors", r"errors?"),
            ("skipped", "skipped"),
        ):
            grab(key, _COUNT.format(word), line)
        return found
    # cargo: "test result: FAILED. 10 passed; 2 failed; 0 ignored"
    m = re.findall(r"test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored", tail)
    if m:
        p = sum(int(x[0]) for x in m)
        f = sum(int(x[1]) for x in m)
        s = sum(int(x[2]) for x in m)
        return {"passed": p, "failed": f, "skipped": s}
    # jest: "Tests:       2 failed, 1 skipped, 40 passed, 43 total"
    m2 = re.findall(r"^Tests:\s+(.*\d+ total)", tail, re.M)
    if m2:
        line = m2[-1]
        for key, word in (("passed", "passed"), ("failed", "failed"), ("skipped", "(?:skipped|todo)")):
            grab(key, _COUNT.format(word), line)
        return found
    # vitest: "Tests  2 failed | 40 passed (42)"
    m3 = re.findall(r"^\s*Tests\s+(.*\(\d+\))", tail, re.M)
    if m3:
        line = m3[-1]
        for key, word in (("passed", "passed"), ("failed", "failed"), ("skipped", "skipped")):
            grab(key, _COUNT.format(word), line)
        return found
    # mocha: "40 passing", "2 failing"
    if re.search(r"^\s*\d+ passing", tail, re.M):
        grab("passed", r"^\s*(\d+) passing", tail)
        grab("failed", r"^\s*(\d+) failing", tail)
        grab("skipped", r"^\s*(\d+) pending", tail)
        return found
    # unittest: "Ran 12 tests in 0.1s" + "OK" / "FAILED (failures=1, errors=2)"
    m4 = re.search(r"^Ran (\d+) tests? in", tail, re.M)
    if m4:
        total = int(m4.group(1))
        fails = sum(int(x) for x in re.findall(r"(?:failures|errors)=(\d+)", tail))
        skipped = sum(int(x) for x in re.findall(r"skipped=(\d+)", tail))
        return {"passed": total - fails - skipped, "failed": fails, "skipped": skipped}
    # go: "--- FAIL:" / "FAIL\tpkg" / "ok  \tpkg"
    if re.search(r"^(?:ok|FAIL|---)\s", tail, re.M):
        fails = len(re.findall(r"^--- FAIL", tail, re.M)) or len(re.findall(r"^FAIL\s", tail, re.M))
        oks = len(re.findall(r"^(?:ok\s|--- PASS)", tail, re.M))
        return {"passed": oks, "failed": fails}
    return None


# --- loaders --------------------------------------------------------------------------------


def _read_lines(path: Path) -> list[tuple[int, Any]]:
    if path.stat().st_size > MAX_TRACE_BYTES:
        raise TraceError("trace is too large")
    rows = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append((n, json.loads(line)))
            except ValueError:
                continue
    return rows


def _command_event(index: int, source: str, command: str, exit_code: int | None, output: str, time: str | None = None,
                   revision: str | None = None) -> Event:  # fmt: skip
    cats, flags = classify_command(command)
    return Event(
        index,
        "command",
        source,
        time,
        redact(command),
        exit_code,
        snippet(output),
        None,
        None,
        revision,
        cats,
        flags,
    )


def _load_groundclaim(rows: list[tuple[int, Any]], name: str) -> list[Event]:
    events: list[Event] = []
    for n, row in rows:
        if not isinstance(row, dict):
            continue
        kind = row.get("type")
        src = f"{name}#{n}"
        if kind == "command" and isinstance(row.get("command"), str):
            code = row.get("exit_code")
            events.append(_command_event(len(events), src, row["command"], code if isinstance(code, int) else None,
                                         str(row.get("output", "")), row.get("time"), row.get("revision")))  # fmt: skip
        elif kind == "file_write" and isinstance(row.get("path"), str):
            events.append(Event(len(events), "file_write", src, row.get("time"), path=row["path"]))
        elif (
            kind == "message"
            and row.get("role", "assistant") == "assistant"
            and isinstance(row.get("text"), str)
        ):
            events.append(Event(len(events), "message", src, row.get("time"), text=row["text"]))
    return events


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            _text_of(c.get("text", c.get("content", ""))) if isinstance(c, dict) else str(c) for c in content
        )
    return ""


def _load_claude_code(rows: list[tuple[int, Any]], name: str) -> list[Event]:
    events: list[Event] = []
    pending: dict[str, Event] = {}
    edit_tools = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
    for n, row in rows:
        if not isinstance(row, dict) or row.get("isSidechain"):
            continue
        msg = row.get("message") or {}
        content = msg.get("content")
        src = f"{name}#{n}"
        time = row.get("timestamp")
        if row.get("type") == "assistant" and isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text" and part.get("text", "").strip():
                    events.append(Event(len(events), "message", src, time, text=part["text"]))
                elif part.get("type") == "tool_use":
                    tool, args = part.get("name"), part.get("input") or {}
                    if tool == "Bash" and isinstance(args.get("command"), str):
                        ev = _command_event(len(events), src, args["command"], None, "", time)
                        if args.get("run_in_background"):
                            ev.flags.add("background")
                        events.append(ev)
                        pending[part.get("id", "")] = ev
                    elif tool in edit_tools and isinstance(
                        args.get("file_path") or args.get("notebook_path"), str
                    ):
                        events.append(
                            Event(
                                len(events),
                                "file_write",
                                src,
                                time,
                                path=args.get("file_path") or args.get("notebook_path"),
                            )
                        )
        elif row.get("type") == "user" and isinstance(content, list):
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") == "tool_result"
                    and part.get("tool_use_id") in pending
                ):
                    ev = pending.pop(part["tool_use_id"])
                    out = _text_of(part.get("content"))
                    raw = row.get("toolUseResult")
                    result: dict[str, Any] = raw if isinstance(raw, dict) else {}
                    if result.get("stdout") or result.get("stderr"):
                        out = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
                    ev.output = snippet(out)
                    if (
                        "background" in ev.flags
                        or result.get("interrupted")
                        or result.get("backgroundTaskId")
                    ):
                        ev.exit_code = None
                        continue
                    m = re.match(r"\s*Exit code (\d+)", _text_of(part.get("content")))
                    ev.exit_code = int(m.group(1)) if m else (1 if part.get("is_error") else 0)
    return events


def _attrs(span: dict[str, Any]) -> dict[str, Any]:
    raw = span.get("attributes") or {}
    if isinstance(raw, dict):
        return raw
    out = {}
    for item in raw:  # OTLP: [{"key": ..., "value": {"stringValue": ...}}]
        if isinstance(item, dict) and "key" in item:
            val = item.get("value") or {}
            out[item["key"]] = next(iter(val.values()), None) if isinstance(val, dict) and val else val
    return out


def _spans(rows: list[tuple[int, Any]]) -> list[tuple[int, dict[str, Any]]]:
    spans: list[tuple[int, dict[str, Any]]] = []
    for n, row in rows:
        if isinstance(row, dict) and "resourceSpans" in row:
            for rs in row["resourceSpans"]:
                for ss in rs.get("scopeSpans", rs.get("instrumentationLibrarySpans", [])):
                    spans.extend((n, s) for s in ss.get("spans", []))
        elif isinstance(row, dict) and (
            "attributes" in row and ("name" in row or "span_id" in row or "spanId" in row)
        ):
            spans.append((n, row))
    return spans


def _start(span: dict[str, Any]) -> str:
    return str(span.get("startTimeUnixNano") or span.get("start_time") or span.get("startTime") or "")


def _load_spans(rows: list[tuple[int, Any]], name: str) -> list[Event]:
    events: list[Event] = []
    spans = sorted(_spans(rows), key=lambda x: (len(_start(x[1])), _start(x[1])))
    for n, span in spans:
        a = _attrs(span)
        src = f"{name}#{n}"
        if a.get("gen_ai.operation.name") == "execute_tool" or "gen_ai.tool.name" in a:
            args_raw, result_raw = a.get("gen_ai.tool.call.arguments"), a.get("gen_ai.tool.call.result")
        elif str(a.get("openinference.span.kind", "")).upper() == "TOOL":
            args_raw, result_raw = a.get("input.value", a.get("tool.parameters")), a.get("output.value")
        else:
            continue
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
        except ValueError:
            args = {"command": args_raw}
        command = (
            args.get("command") or args.get("cmd") or args.get("script") if isinstance(args, dict) else None
        )
        if isinstance(command, list):
            command = " ".join(map(str, command))
        if isinstance(command, str):
            exit_code = None
            output = result_raw if isinstance(result_raw, str) else json.dumps(result_raw or "")
            try:
                res = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
            except ValueError:
                res = None
            if isinstance(res, dict):
                for key in ("exit_code", "exitCode", "returncode", "return_code", "status_code"):
                    if isinstance(res.get(key), int):
                        exit_code = res[key]
                        break
                output = str(res.get("stdout", "")) + "\n" + str(res.get("stderr", res.get("output", "")))
            status = span.get("status") or {}
            if exit_code is None and (status.get("code") in (2, "STATUS_CODE_ERROR", "ERROR")):
                exit_code = 1  # the tool call itself failed
            events.append(_command_event(len(events), src, command, exit_code, output))
        elif isinstance(args, dict) and isinstance(args.get("path") or args.get("file_path"), str):
            tool = str(a.get("gen_ai.tool.name") or a.get("tool.name") or "").lower()
            if re.search(r"write|edit|create|save|patch|replace", tool):
                events.append(
                    Event(len(events), "file_write", src, path=args.get("path") or args.get("file_path"))
                )
    return events


def load_trace(path: Path) -> tuple[str, list[Event]]:
    """(format name, events in order)."""
    if path.stat().st_size > MAX_TRACE_BYTES:
        raise TraceError("trace is too large")
    text_start = path.read_bytes()[:1].lstrip()
    rows: list[tuple[int, Any]]
    if text_start == b"{" and path.suffix == ".json":
        try:
            rows = [(1, json.loads(path.read_text(encoding="utf-8")))]
        except ValueError:
            rows = _read_lines(path)
    else:
        rows = _read_lines(path)
    if not rows:
        raise TraceError("no JSON records found in the trace")
    name = path.name
    first = [r for _, r in rows[:50] if isinstance(r, dict)]
    if any(
        (r.get("type") in ("command", "file_write", "message") and "message" not in r) or r.get("groundclaim")
        for r in first
    ):
        return "groundclaim", _load_groundclaim(rows, name)
    if any(
        "sessionId" in r or (r.get("type") in ("assistant", "user") and isinstance(r.get("message"), dict))
        for r in first
    ):
        return "claude-code", _load_claude_code(rows, name)
    if _spans(rows[:50]):
        return "spans", _load_spans(rows, name)
    raise TraceError("unknown trace format")


def final_message(events: list[Event]) -> str | None:
    """The agent's last message in the run: the text it ended with."""
    for ev in reversed(events):
        if ev.kind == "message" and ev.text:
            return ev.text
    return None
