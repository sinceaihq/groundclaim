"""GroundClaim-Bench metrics.

For claims that are false (the claimed thing did not happen):
  * false confirmation rate (FCR) — verdict ``confirmed``. The headline error.
  * false acceptance rate (FAR) — verdict ``confirmed`` or ``supported``.
  * catch rate — verdict ``contradicted``.
For claims that are true:
  * false rejection rate (FRR) — verdict ``contradicted``. The other headline error.
  * confirmation rate — verdict ``confirmed`` (how often a true claim is fully proven).
  * acceptance rate — ``confirmed`` or ``supported``.
``insufficient_evidence`` and ``unverifiable`` are abstentions: neither error. In the end-to-end evaluation a gold
claim the extractor did not find has the verdict ``missed``, also an abstention.

95 % intervals are percentile bootstrap over scenarios (1000 resamples, fixed seed).
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

ACCEPT = {"confirmed", "supported"}


def _rates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    false = [r for r in rows if r["truth"] is False]
    true = [r for r in rows if r["truth"] is True]

    def frac(xs: list[dict[str, Any]], verdicts: set[str]) -> float | None:
        return round(sum(r["verdict"] in verdicts for r in xs) / len(xs), 4) if xs else None

    return {
        "n_false": len(false),
        "n_true": len(true),
        "false_confirmation_rate": frac(false, {"confirmed"}),
        "false_acceptance_rate": frac(false, ACCEPT),
        "catch_rate": frac(false, {"contradicted"}),
        "false_rejection_rate": frac(true, {"contradicted"}),
        "confirmation_rate": frac(true, {"confirmed"}),
        "acceptance_rate": frac(true, ACCEPT),
    }


def _bootstrap(
    rows: list[dict[str, Any]], keys: list[str], n: int = 1000, seed: int = 0
) -> dict[str, list[float]]:
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_id[r["id"]].append(r)
    ids = sorted(by_id)
    rng = random.Random(seed)
    samples: dict[str, list[float]] = {k: [] for k in keys}
    for _ in range(n):
        pick = [r for i in (rng.choice(ids) for _ in ids) for r in by_id[i]]
        rates = _rates(pick)
        for k in keys:
            if rates[k] is not None:
                samples[k].append(rates[k])
    out = {}
    for k, xs in samples.items():
        xs.sort()
        if xs:
            out[k] = [
                round(xs[int(0.025 * len(xs))], 4),
                round(xs[min(len(xs) - 1, int(0.975 * len(xs)))], 4),
            ]
    return out


def compute(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[(r["method"], r["condition"])].append(r)
    summary = {}
    detail: dict[str, Any] = {}
    for (method, cond), rs in sorted(groups.items()):
        key = f"{method} | {cond}"
        rates = _rates(rs)
        rates["ci95"] = _bootstrap(
            rs, ["false_confirmation_rate", "false_rejection_rate", "catch_rate", "confirmation_rate"]
        )
        summary[key] = rates
        fam: dict[str, list[dict[str, Any]]] = defaultdict(list)
        typ: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rs:
            fam[r["family"]].append(r)
            typ[r["type"]].append(r)
        verdicts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in rs:
            verdicts["true" if r["truth"] else "false"][r["verdict"]] += 1
        detail[key] = {
            "by_family": {k: _rates(v) for k, v in sorted(fam.items())},
            "by_claim_type": {k: _rates(v) for k, v in sorted(typ.items())},
            "verdicts": {k: dict(v) for k, v in verdicts.items()},
        }
    return {"summary": summary, "detail": detail}


def _overlap(a: list[int], b: list[int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def extraction_scores(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Claim detection: a predicted claim matches a gold claim of the same type with overlapping span."""
    tp = fp = fn = 0
    per_type: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    misses: list[dict[str, Any]] = []
    for it in items:
        used: set[int] = set()
        for g in it["gold"]:
            hit = next((j for j, p in enumerate(it["pred"]) if j not in used and p["type"] == g["type"]
                        and _overlap(p["span"], g["span"])), None)  # fmt: skip
            if hit is None:
                fn += 1
                per_type[g["type"]]["fn"] += 1
                misses.append({"id": it["id"], "type": g["type"], "span": g["span"]})
            else:
                used.add(hit)
                tp += 1
                per_type[g["type"]]["tp"] += 1
        for j, p in enumerate(it["pred"]):
            if j not in used:
                fp += 1
                per_type[p["type"]]["fp"] += 1

    def prf(t: int, f_p: int, f_n: int) -> dict[str, Any]:
        p = t / (t + f_p) if t + f_p else None
        r = t / (t + f_n) if t + f_n else None
        f1 = 2 * p * r / (p + r) if p and r else None
        return {
            "tp": t,
            "fp": f_p,
            "fn": f_n,
            "precision": p and round(p, 4),
            "recall": r and round(r, 4),
            "f1": f1 and round(f1, 4),
        }

    return {
        "overall": prf(tp, fp, fn),
        "per_type": {k: prf(v["tp"], v["fp"], v["fn"]) for k, v in sorted(per_type.items())},
        "misses": misses[:200],
    }
