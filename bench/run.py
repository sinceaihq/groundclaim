"""Run GroundClaim and baselines over GroundClaim-Bench scenarios.

    python bench/run.py --data bench/out --split dev --out bench/results/dev

Writes predictions.jsonl (one row per gold claim × method × condition),
extraction.json (claim extraction precision/recall on the messages) and
metrics.json (see metrics.py).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from baselines import BASELINES  # noqa: E402
from metrics import compute, extraction_scores  # noqa: E402

from groundclaim.claims import extract_claims  # noqa: E402
from groundclaim.git import Repo  # noqa: E402
from groundclaim.github import GitHub, fixture_transport  # noqa: E402
from groundclaim.model import Claim  # noqa: E402
from groundclaim.reports import load_report  # noqa: E402
from groundclaim.trace import load_trace  # noqa: E402
from groundclaim.verify import Sources, verify  # noqa: E402

# Which evidence sources each condition gives the verifier.
CONDITIONS = {
    "full": {"git": True, "trace": True, "github": True},
    "git+github": {"git": True, "trace": False, "github": True},
    "git+trace": {"git": True, "trace": True, "github": False},
    "trace only": {"git": False, "trace": True, "github": False},
}


def gold_claims(scn: dict[str, Any]) -> list[tuple[Claim, dict[str, Any]]]:
    out = []
    for i, g in enumerate(scn["claims"]):
        if g["truth"] is None:
            continue
        claim = Claim(f"c{i + 1}", g["type"], g["sentence"], tuple(g["span"]), dict(g["details"]))  # type: ignore[arg-type]
        out.append((claim, g))
    return out


def sources_for(root: Path, scn: dict[str, Any], cond: dict[str, bool]) -> Sources:
    events = load_trace(root / "trace.jsonl")[1] if cond["trace"] else None
    if events:
        events = [e for e in events if e.kind != "message"]
    repo = Repo(root / "repo") if cond["git"] else None
    github = GitHub(scn["github_repo"], fixture_transport(root / "github.json")) if cond["github"] else None
    reports = (
        [load_report(root / "repo" / r) for r in scn.get("reports", []) if (root / "repo" / r).exists()]
        if cond["trace"]
        else []
    )
    return Sources(repo=repo, base=scn["base"] if repo else None, reports=reports, events=events,
                   trace_name="trace.jsonl" if events is not None else None, github=github,
                   workspace=root / "repo" if cond["git"] else None)  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE / "out"))
    ap.add_argument("--split", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    data = Path(a.data)
    scenarios = [
        json.loads(line) for line in (data / f"{a.split}.jsonl").read_text().splitlines() if line.strip()
    ]
    if a.limit:
        scenarios = scenarios[: a.limit]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    extraction: list[dict[str, Any]] = []
    t0 = time.time()
    for scn in scenarios:
        root = data / a.split / scn["id"]
        claims = gold_claims(scn)
        extraction.append({"id": scn["id"], "gold": [{"type": g["type"], "span": g["span"]} for g in scn["claims"]],
                           "pred": [{"type": c.type, "span": list(c.span)} for c in extract_claims(scn["message"])]})  # fmt: skip
        for cname, cond in CONDITIONS.items():
            src = sources_for(root, scn, cond)
            report = verify(scn["message"], src, claims=[c for c, _ in claims])
            for (claim, g), a_ in zip(claims, report.assessments, strict=True):
                rows.append({"id": scn["id"], "family": scn["family"], "type": claim.type, "truth": g["truth"],
                             "note": g["note"], "method": "groundclaim", "condition": cname, "verdict": a_.verdict,
                             "reason": a_.reason})  # fmt: skip
            for bname, fn in BASELINES.items():
                src = sources_for(root, scn, cond)
                for claim, g in claims:
                    verdict = fn(claim, src)
                    rows.append({"id": scn["id"], "family": scn["family"], "type": claim.type, "truth": g["truth"],
                                 "note": g["note"], "method": bname, "condition": cname, "verdict": verdict, "reason": ""})  # fmt: skip
    elapsed = time.time() - t0
    (out / "predictions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    ext = extraction_scores(extraction)
    (out / "extraction.json").write_text(json.dumps(ext, indent=1))
    metrics = compute(rows)
    metrics["seconds_per_scenario_all_conditions"] = round(elapsed / max(1, len(scenarios)), 3)
    metrics["scenarios"] = len(scenarios)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1))
    print(json.dumps({"extraction": ext["overall"], "summary": metrics["summary"]}, indent=1))


if __name__ == "__main__":
    main()
