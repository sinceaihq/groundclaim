"""Claim-extraction scores on scenario messages (bench/out/<split>.jsonl) or on bench/extraction/realistic.jsonl.

python bench/extraction/score.py bench/out/test.jsonl
python bench/extraction/score.py bench/extraction/realistic.jsonl
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from groundclaim.claims import extract_claims


def main(path: str) -> dict[str, object]:
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    tp = fp = fn = 0
    per: dict[str, Counter[str]] = {}
    errors = []
    for r in rows:
        text = r.get("message", r.get("text"))
        gold = Counter(c["type"] if isinstance(c, dict) else c for c in r["claims"])
        pred = Counter(c.type for c in extract_claims(text))
        for t in set(gold) | set(pred):
            k = per.setdefault(t, Counter())
            hit = min(gold[t], pred[t])
            tp += hit
            fp += pred[t] - hit
            fn += gold[t] - hit
            k["tp"] += hit
            k["fp"] += pred[t] - hit
            k["fn"] += gold[t] - hit
        if gold != pred:
            errors.append(
                {
                    "id": r.get("id"),
                    "text": text[:200],
                    "gold": sorted(gold.elements()),
                    "pred": sorted(pred.elements()),
                }
            )
    p = tp / (tp + fp) if tp + fp else 1.0
    rec = tp / (tp + fn) if tp + fn else 1.0
    out = {"items": len(rows), "tp": tp, "fp": fp, "fn": fn, "precision": round(p, 4), "recall": round(rec, 4),
           "per_type": {t: dict(c) for t, c in sorted(per.items())}, "errors": errors}  # fmt: skip
    return out


if __name__ == "__main__":
    res = main(sys.argv[1])
    print(json.dumps({k: v for k, v in res.items() if k != "errors"}, indent=1))
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps(res, indent=1, ensure_ascii=False))
