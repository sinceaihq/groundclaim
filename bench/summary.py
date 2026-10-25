"""Print a compact table of a metrics.json (and extraction.json) result directory."""

import json
import sys
from pathlib import Path

d = Path(sys.argv[1])
e = json.loads((d / "extraction.json").read_text())["overall"]
print(
    f"claim extraction: precision {e['precision']}, recall {e['recall']} (tp {e['tp']}, fp {e['fp']}, fn {e['fn']})"
)
m = json.loads((d / "metrics.json").read_text())
print(
    f"{'method | condition':34} {'nF':>4} {'nT':>4} {'FCR':>6} {'FAR':>6} {'catch':>6} {'FRR':>6} {'conf':>6} {'acc':>6}"
)
for k, v in m["summary"].items():
    f = lambda x: "  —  " if x is None else f"{100 * x:5.1f}"  # noqa: E731
    print(
        f"{k:34} {v['n_false']:4} {v['n_true']:4} {f(v['false_confirmation_rate']):>6} {f(v['false_acceptance_rate']):>6} "
        f"{f(v['catch_rate']):>6} {f(v['false_rejection_rate']):>6} {f(v['confirmation_rate']):>6} {f(v['acceptance_rate']):>6}"
    )
