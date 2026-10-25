"""Write the viewer's example reports from real GroundClaim runs.

python viewer/make_examples.py bench/out   # after generating the test split; also runs examples/demo.sh
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "viewer" / "examples"
# (file name, family, scenario note) — the first test episode matching each is used
PICKS = [
    ("masked-exit.json", "masked_exit", None),
    ("tampering.json", "test_tampering", "tests tampered (skip)"),
    ("push.json", "push", "rejected"),
    ("pull-request.json", "pull_request", "the PR number in the message is wrong"),
    ("deploy.json", "deploy", "rollout_failed"),
]


def check(args: list[str], cwd: Path) -> dict[str, object]:
    proc = subprocess.run([sys.executable, "-m", "groundclaim.cli", "check", "-f", "json", *args], cwd=cwd,
                          capture_output=True, text=True, check=False)  # fmt: skip
    if proc.returncode not in (0, 1):
        raise SystemExit(proc.stderr)
    report: dict[str, object] = json.loads(proc.stdout)
    subject = report["subject"]
    assert isinstance(subject, dict)
    subject["repository"] = Path(
        str(subject.get("repository", ""))
    ).name  # no local paths in published examples
    return report


def main(data: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["bash", str(ROOT / "examples" / "demo.sh")], cwd=tmp, capture_output=True, check=True,
                       env={**os.environ, "PATH": f"{Path(sys.executable).parent}:{os.environ['PATH']}"})  # fmt: skip
        base = subprocess.run(["git", "-C", "demo-repo", "rev-list", "--max-parents=0", "HEAD"], cwd=tmp,
                              capture_output=True, text=True, check=True).stdout.strip()[:7]  # fmt: skip
        report = check(["--repo", "demo-repo", "--base", base, "--trace", "demo-run.jsonl"], Path(tmp))
        (OUT / "demo.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    scenarios = [json.loads(line) for line in (data / "test.jsonl").read_text().splitlines()]
    for name, family, note in PICKS:
        scn = next(
            s
            for s in scenarios
            if s["family"] == family and (note is None or any(c["note"] == note for c in s["claims"]))
        )
        root = data / "test" / scn["id"]
        args = ["--repo", str(root / "repo"), "--base", scn["base"], "--trace", str(root / "trace.jsonl"),
                "--github", scn["github_repo"], "--github-fixture", str(root / "github.json")]  # fmt: skip
        for r in scn.get("reports", []):
            args += ["--report", str(root / "repo" / r)]
        report = check(args, ROOT)
        report["subject"]["benchmark_episode"] = scn["id"]  # type: ignore[index]
        (OUT / name).write_text(json.dumps(report, indent=1, ensure_ascii=False))
        print(name, scn["id"], [a["verdict"] for a in report["assessments"]])  # type: ignore[union-attr]


if __name__ == "__main__":
    main(Path(sys.argv[1]))
