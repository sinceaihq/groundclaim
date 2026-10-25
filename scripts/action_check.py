"""Entry point of the GroundClaim GitHub Action (action.yml).

Reads the inputs from GC_* environment variables and the event payload from
GITHUB_EVENT_PATH, runs ``groundclaim check``, writes the Markdown report to the
job summary and sets the step outputs. Exits with groundclaim's exit code.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from groundclaim.cli import main


def env(name: str) -> str:
    return os.environ.get(name, "").strip()


def lines(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").splitlines() if x.strip()]


def set_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def run() -> int:
    event: dict[str, object] = {}
    if env("GITHUB_EVENT_PATH") and Path(env("GITHUB_EVENT_PATH")).is_file():
        event = json.loads(Path(env("GITHUB_EVENT_PATH")).read_text(encoding="utf-8"))
    pr = event.get("pull_request") if isinstance(event.get("pull_request"), dict) else None

    out_dir = Path(env("RUNNER_TEMP") or tempfile.mkdtemp())
    # "--option=value" throughout: a value may start with "-" (a description that begins with a bullet list).
    args = ["check", "--format=markdown", f"--also=json={out_dir / 'groundclaim.json'}",
            f"--also=html={out_dir / 'groundclaim.html'}", f"--require={env('GC_REQUIRE') or 'none'}"]  # fmt: skip
    if env("GC_MESSAGE_FILE"):
        args.append(f"--message-file={env('GC_MESSAGE_FILE')}")
    elif os.environ.get("GC_MESSAGE", "").strip():
        args.append(f"--message={os.environ['GC_MESSAGE']}")
    elif pr is not None and isinstance(pr.get("body"), str) and pr["body"].strip():
        body = out_dir / "groundclaim-message.md"
        body.write_text(str(pr["body"]), encoding="utf-8")
        args.append(f"--message-file={body}")
    elif env("GC_TRACE"):
        pass  # the trace's final assistant message
    else:
        print("GroundClaim: nothing to check (no message, message-file, pull request description or trace).")
        set_output("contradicted", "0")
        return 0

    base = env("GC_BASE")
    if not base and pr is not None:
        base = str((pr.get("base") or {}).get("sha") or "")  # type: ignore[union-attr]
    if base:
        args.append(f"--base={base}")
    if env("GC_TRACE"):
        args.append(f"--trace={env('GC_TRACE')}")
    for report in lines("GC_REPORTS"):
        args.append(f"--report={report}")
    if env("GC_TRUSTED").lower() == "true":
        args.append("--trusted-reports")
    if env("GC_STRICT").lower() == "true":
        args.append("--strict")
    if env("GITHUB_REPOSITORY"):
        args.append(f"--github={env('GITHUB_REPOSITORY')}")
    if env("GC_WAIT") and env("GC_WAIT") != "0":
        args.append(f"--wait-for-checks={env('GC_WAIT')}")
    for name in lines("GC_IGNORE"):
        args.append(f"--ignore-check={name}")

    md = out_dir / "groundclaim.md"
    args.append(f"--output={md}")
    code = main(args)
    if md.is_file():
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(md.read_text(encoding="utf-8") + "\n")
        print(md.read_text(encoding="utf-8"))
    report = out_dir / "groundclaim.json"
    contradicted = 0
    if report.is_file():
        data = json.loads(report.read_text(encoding="utf-8"))
        contradicted = sum(1 for a in data["assessments"] if a["verdict"] == "contradicted")
        set_output("report", str(report))
    set_output("contradicted", str(contradicted))
    return code


if __name__ == "__main__":
    sys.exit(run())
