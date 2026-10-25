"""Report output: plain text, Markdown (PR comments, job summaries) and a self-contained HTML page."""

from __future__ import annotations

import html
import json
from typing import Any

from .model import Report

ICON = {
    "confirmed": "✔",
    "supported": "◐",
    "contradicted": "✘",
    "insufficient_evidence": "?",
    "unverifiable": "–",
}
LABEL = {
    "confirmed": "confirmed",
    "supported": "supported",
    "contradicted": "contradicted",
    "insufficient_evidence": "insufficient evidence",
    "unverifiable": "unverifiable",
}
ORDER = ["contradicted", "insufficient_evidence", "supported", "confirmed", "unverifiable"]


def to_json(report: Report) -> str:
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)


def summary_line(report: Report) -> str:
    c = report.counts()
    parts = [f"{c[v]} {LABEL[v]}" for v in ORDER if c.get(v)]
    return f"{len(report.assessments)} claim(s): " + (", ".join(parts) if parts else "none")


def to_text(report: Report, color: bool = False) -> str:
    colors = {
        "confirmed": "32",
        "supported": "36",
        "contradicted": "31",
        "insufficient_evidence": "33",
        "unverifiable": "90",
    }
    ev = {e.id: e for e in report.evidence}
    lines = [summary_line(report), ""]
    for a in report.assessments:
        tag = f"{ICON[a.verdict]} {LABEL[a.verdict]}"
        if color:
            tag = f"\033[{colors[a.verdict]}m{tag}\033[0m"
        lines.append(f"{tag}  [{a.claim.type}] {a.claim.text}")
        lines.append(f"    {a.reason}")
        for link in a.links:
            e = ev.get(link.evidence)
            if e is None:
                continue
            mark = {"supports": "+", "contradicts": "-", "neutral": "·"}[link.stance]
            lines.append(f"      {mark} ({e.provenance}) {link.reason}")
        lines.append("")
    for w in report.warnings:
        lines.append(f"warning: {w}")
    return "\n".join(lines).rstrip() + "\n"


def _md(text: str) -> str:
    """Escape text for a Markdown table cell or list item (agent text is untrusted)."""
    out = html.escape(text, quote=False).replace("|", "\\|").replace("\n", " ")
    for ch in "`*_[]<>#!":
        out = out.replace(ch, "\\" + ch)
    return out[:500]


def to_markdown(report: Report) -> str:
    lines = [
        "### GroundClaim",
        "",
        summary_line(report),
        "",
        "| | claim | verdict | why |",
        "|---|---|---|---|",
    ]
    for a in report.assessments:
        lines.append(
            f"| {ICON[a.verdict]} | {_md(a.claim.text)} | **{LABEL[a.verdict]}** | {_md(a.reason)} |"
        )
    if report.warnings:
        lines += ["", "**Warnings**", ""] + [f"- {_md(w)}" for w in report.warnings]
    subj = report.subject
    if subj.get("head"):
        lines += ["", f"<sub>checked at {_md(str(subj['head'])[:12])}"
                  + (f" against base {_md(str(subj['base'])[:12])}" if subj.get("base") else "")
                  + f" · schema {report.schema_version}</sub>"]  # fmt: skip
    return "\n".join(lines) + "\n"


CSS = """
:root{--bg:#fbfbfa;--fg:#1d1d1b;--muted:#5d5d58;--line:#e2e1dc;--card:#fff;--ok:#1d7a3a;--sup:#1f6f8b;--bad:#b3261e;
--unk:#8a5a00;--na:#6b6b66;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe7;--muted:#a7a6a0;--line:#33332f;--card:#1f1f1d;--ok:#6fcf8a;
--sup:#79c0d9;--bad:#ff8a80;--unk:#f2c46d;--na:#9b9b95;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px 64px}h1{font-size:1.4rem;margin:0 0 4px}
.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}
.v{font-weight:600;white-space:nowrap}.confirmed{color:var(--ok)}.supported{color:var(--sup)}.contradicted{color:var(--bad)}
.insufficient_evidence{color:var(--unk)}.unverifiable{color:var(--na)}blockquote{margin:6px 0;padding-left:10px;border-left:3px solid var(--line)}
ul{margin:6px 0;padding-left:20px}li{margin:2px 0}code{font:13px ui-monospace,monospace;overflow-wrap:anywhere}
.tag{font-size:12px;border:1px solid var(--line);border-radius:6px;padding:0 6px;margin-right:6px;color:var(--muted)}
details{margin-top:8px}summary{cursor:pointer;color:var(--muted)}table{border-collapse:collapse;width:100%}
td,th{border-bottom:1px solid var(--line);padding:6px;text-align:left;vertical-align:top;font-size:14px}
"""


def to_html(report: Report) -> str:
    e = html.escape
    ev = {x.id: x for x in report.evidence}
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'\">",
        f"<title>GroundClaim report</title><style>{CSS}</style></head><body><main>",
        f"<h1>GroundClaim report</h1><p class='muted'>{e(summary_line(report))}</p>",
    ]
    subj = report.subject
    meta = [f"{e(k)}: <code>{e(str(v))}</code>" for k, v in subj.items() if v not in (None, "")]
    if meta:
        parts.append(f"<p class='muted'>{' · '.join(meta)}</p>")
    for w in report.warnings:
        parts.append(f"<div class='card'><span class='v unverifiable'>warning</span> {e(w)}</div>")
    for a in report.assessments:
        parts.append(
            f"<section class='card'><div><span class='v {a.verdict}'>{ICON[a.verdict]} {LABEL[a.verdict]}</span> "
            f"<span class='tag'>{e(a.claim.type)}</span></div><blockquote>{e(a.claim.text)}</blockquote>"
            f"<div>{e(a.reason)}</div>"
        )
        if a.links:
            parts.append("<details><summary>evidence</summary><ul>")
            for link in a.links:
                x = ev.get(link.evidence)
                if x is None:
                    continue
                parts.append(
                    f"<li><b>{e(link.stance)}</b> <span class='tag'>{e(x.provenance)}</span>{e(link.reason)}"
                    f"<br><span class='muted'>{e(x.kind)} · {e(x.source)}{' · decisive' if link.decisive else ''}</span></li>"
                )
            parts.append("</ul></details>")
        parts.append("</section>")
    parts.append("<p class='muted'>Generated by GroundClaim. Verdicts are only as good as the evidence sources given; "
                 "see the documentation for what each verdict means.</p></main></body></html>")  # fmt: skip
    return "\n".join(parts)


def render(report: Report, fmt: str, color: bool = False) -> str:
    if fmt == "json":
        return to_json(report)
    if fmt == "markdown":
        return to_markdown(report)
    if fmt == "html":
        return to_html(report)
    return to_text(report, color)


def report_from_dict(data: dict[str, Any]) -> Report:
    """Rebuild a Report from its JSON form (for re-rendering)."""
    from .model import Assessment, Claim, Evidence, Link

    assessments = []
    for a in data.get("assessments", []):
        c = a["claim"]
        claim = Claim(c["id"], c["type"], c["text"], tuple(c["span"]), c.get("details", {}))
        links = [Link(**lk) for lk in a.get("links", [])]
        assessments.append(Assessment(claim, a["verdict"], a["reason"], links))
    evidence = [Evidence(**x) for x in data.get("evidence", [])]
    return Report(
        data.get("schema_version", "?"),
        data.get("subject", {}),
        assessments,
        evidence,
        data.get("warnings", []),
    )
