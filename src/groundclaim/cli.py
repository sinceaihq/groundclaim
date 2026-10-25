"""groundclaim command line.

Exit codes: 0 = policy satisfied, 1 = policy not satisfied, 2 = bad input or usage.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .claims import extract_claims
from .git import Repo
from .github import GitHub, GitHubError, fixture_transport, http_transport
from .model import Report
from .render import render, report_from_dict
from .reports import ReportError, load_report
from .trace import TraceError, final_message, load_trace
from .verify import CommandRun, Sources, verify

LEVELS = {"confirmed": 3, "supported": 2, "insufficient_evidence": 1, "contradicted": 0}


def policy_failures(report: Report, require: str, strict: bool) -> list[str]:
    """Claims that do not meet the policy. ``require``: none | supported | confirmed."""
    bad = []
    for a in report.assessments:
        if a.verdict == "contradicted":
            bad.append(f"{a.claim.id} contradicted: {a.claim.text}")
        elif a.verdict == "unverifiable":
            if strict:
                bad.append(f"{a.claim.id} unverifiable: {a.claim.text}")
        elif require != "none" and LEVELS[a.verdict] < LEVELS[require]:
            bad.append(f"{a.claim.id} {a.verdict} (needs {require}): {a.claim.text}")
    return bad


def _run_tests(command: str, repo: Repo | None, cwd: Path, timeout: int) -> CommandRun:
    # Only ever a command the user typed on this command line, never one taken from a trace or message.
    args = shlex.split(command)
    try:
        proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        code, out = proc.returncode, proc.stdout + "\n" + proc.stderr
    except subprocess.TimeoutExpired:
        code, out = 124, f"timed out after {timeout}s"
    except OSError as exc:
        code, out = 127, str(exc)
    head = repo.head() if repo else None
    return CommandRun(command, code, out[-20000:], head)


def _wait_for_checks(github: GitHub, sha: str, ignore: set[str], timeout: int, interval: float = 15) -> None:
    """Wait until every CI check run on ``sha`` (except ``ignore``) has finished, or ``timeout`` seconds pass."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            github.refresh()
            pending = [r.get("name", "?") for r in github.check_runs(sha)
                       if r.get("name") not in ignore and r.get("status") != "completed"]  # fmt: skip
        except GitHubError as exc:
            print(f"groundclaim: cannot read check runs: {exc}", file=sys.stderr)
            return
        if not pending:
            return
        if time.monotonic() >= deadline:
            print(f"groundclaim: still running after {timeout}s: {', '.join(pending[:5])}", file=sys.stderr)
            return
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))


def cmd_check(args: argparse.Namespace) -> int:
    events = None
    trace_name = None
    if args.trace:
        try:
            fmt, events = load_trace(Path(args.trace))
        except (OSError, TraceError) as exc:
            print(f"groundclaim: cannot read trace: {exc}", file=sys.stderr)
            return 2
        trace_name = f"{Path(args.trace).name} ({fmt})"
    if args.message is not None:
        message = args.message
    elif args.message_file:
        message = (
            sys.stdin.read()
            if args.message_file == "-"
            else Path(args.message_file).read_text(encoding="utf-8")
        )
    elif events is not None:
        message = final_message(events) or ""
        if not message:
            print("groundclaim: the trace has no final assistant message; pass --message", file=sys.stderr)
            return 2
    else:
        print(
            "groundclaim: give the agent's message (--message, --message-file) or a --trace", file=sys.stderr
        )
        return 2

    repo = None
    repo_dir = Path(args.repo).resolve()
    if not args.no_git:
        candidate = Repo(repo_dir)
        if candidate.is_repo():
            repo = candidate
        elif args.repo != ".":
            print(f"groundclaim: {repo_dir} is not a git repository", file=sys.stderr)
            return 2

    reports = []
    for path in args.report or []:
        try:
            reports.append(load_report(Path(path)))
        except (OSError, ReportError) as exc:
            print(f"groundclaim: cannot read report {path}: {exc}", file=sys.stderr)
            return 2

    github = None
    if args.github:
        try:
            transport = (fixture_transport(Path(args.github_fixture)) if args.github_fixture
                         else http_transport(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")))  # fmt: skip
            github = GitHub(args.github, transport)
        except (OSError, ValueError, GitHubError) as exc:
            print(f"groundclaim: {exc}", file=sys.stderr)
            return 2

    ignore = set(args.ignore_check or [])
    if github and repo and args.wait_for_checks > 0:
        _wait_for_checks(github, repo.head(), ignore, args.wait_for_checks)
    runs = [_run_tests(c, repo, repo_dir, args.run_timeout) for c in args.run_tests or []]
    sources = Sources(
        repo=repo, base=args.base, reports=reports, reports_trusted=args.trusted_reports, events=events,
        trace_name=trace_name, github=github, workspace=Path(args.workspace) if args.workspace else None, runs=runs,
        ignore_checks=ignore,
    )  # fmt: skip
    report = verify(message, sources, {"tool": f"groundclaim {__version__}"})
    out = render(
        report,
        args.format,
        color=args.format == "text" and sys.stdout.isatty() and not os.environ.get("NO_COLOR"),
    )
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
    for extra in args.also or []:
        fmt, _, path = extra.partition("=")
        if fmt not in ("json", "markdown", "html", "text") or not path:
            print(f"groundclaim: --also expects FORMAT=PATH, got {extra!r}", file=sys.stderr)
            return 2
        Path(path).write_text(render(report, fmt), encoding="utf-8")
    failures = policy_failures(report, args.require, args.strict)
    if failures:
        print(f"groundclaim: {len(failures)} claim(s) do not meet the policy:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    return 0


def cmd_claims(args: argparse.Namespace) -> int:
    text = args.message if args.message is not None else sys.stdin.read()
    print(json.dumps([c.__dict__ for c in extract_claims(text)], indent=2, ensure_ascii=False))
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    try:
        report = report_from_dict(json.loads(Path(args.report).read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"groundclaim: cannot read report: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(render(report, args.format))
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    from importlib.resources import files

    sys.stdout.write(files("groundclaim").joinpath("report.schema.json").read_text(encoding="utf-8"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="groundclaim", description="Check an AI agent's completion claims against evidence."
    )
    p.add_argument("--version", action="version", version=f"groundclaim {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="verify the claims in an agent's final message")
    src = c.add_argument_group("the agent's message")
    src.add_argument("-m", "--message", help="the message text")
    src.add_argument("--message-file", help="file with the message ('-' for stdin)")
    ev = c.add_argument_group("evidence sources")
    ev.add_argument("--repo", default=".", help="git repository to inspect (default: current directory)")
    ev.add_argument("--no-git", action="store_true", help="do not look at a git repository")
    ev.add_argument("--base", help="revision the agent started from (enables change and commit checks)")
    ev.add_argument(
        "--trace",
        help="agent run trace (GroundClaim JSONL, Claude Code transcript, OTel/OpenInference spans)",
    )
    ev.add_argument("--report", action="append", help="test report (JUnit XML or CTRF JSON); repeatable")
    ev.add_argument(
        "--trusted-reports",
        action="store_true",
        help="the reports were produced outside the agent's control (e.g. by CI), so they count as independent",
    )
    ev.add_argument(
        "--github",
        metavar="OWNER/REPO",
        help="query GitHub (checks, PRs, deployments, releases); token from GITHUB_TOKEN",
    )
    ev.add_argument("--github-fixture", help=argparse.SUPPRESS)
    ev.add_argument(
        "--wait-for-checks",
        type=int,
        default=0,
        metavar="SECONDS",
        help="wait up to this long for running CI checks on the commit to finish",
    )
    ev.add_argument(
        "--ignore-check",
        action="append",
        metavar="NAME",
        help="leave this CI check out (e.g. the job running GroundClaim); repeatable",
    )
    ev.add_argument(
        "--workspace", help="directory where claimed output files are looked up (default: the repository)"
    )
    ev.add_argument(
        "--run-tests",
        action="append",
        metavar="COMMAND",
        help="run this test command yourself and use the result as independent evidence (opt-in; runs code)",
    )
    ev.add_argument("--run-timeout", type=int, default=1800)
    out = c.add_argument_group("output and policy")
    out.add_argument("-f", "--format", choices=["text", "json", "markdown", "html"], default="text")
    out.add_argument("-o", "--output", help="write the report here instead of stdout")
    out.add_argument(
        "--also",
        action="append",
        metavar="FORMAT=PATH",
        help="also write another format, e.g. html=report.html",
    )
    out.add_argument(
        "--require",
        choices=["none", "supported", "confirmed"],
        default="none",
        help="minimum verdict for every checkable claim (contradicted claims always fail)",
    )
    out.add_argument("--strict", action="store_true", help="unverifiable claims also fail the policy")
    c.set_defaults(func=cmd_check)

    cl = sub.add_parser("claims", help="list the claims found in a message (no verification)")
    cl.add_argument("message", nargs="?", help="message text (default: stdin)")
    cl.set_defaults(func=cmd_claims)

    r = sub.add_parser("render", help="render a JSON report as text, Markdown or HTML")
    r.add_argument("report")
    r.add_argument("-f", "--format", choices=["text", "json", "markdown", "html"], default="text")
    r.set_defaults(func=cmd_render)

    s = sub.add_parser("schema", help="print the JSON Schema of the report format")
    s.set_defaults(func=cmd_schema)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
