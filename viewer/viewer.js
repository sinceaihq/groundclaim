// GroundClaim report viewer. Reports are untrusted: everything is rendered as text nodes, never as HTML.
"use strict";

const ICON = { confirmed: "✔", supported: "◐", contradicted: "✘", insufficient_evidence: "?", unverifiable: "–" };
const LABEL = { confirmed: "confirmed", supported: "supported", contradicted: "contradicted",
  insufficient_evidence: "insufficient evidence", unverifiable: "unverifiable" };
const ORDER = ["contradicted", "insufficient_evidence", "supported", "confirmed", "unverifiable"];
const EXAMPLES = [
  ["Pager fix (demo.sh)", "examples/demo.json"],
  ["Piped test run", "examples/masked-exit.json"],
  ["Tests disabled", "examples/tampering.json"],
  ["Rejected push", "examples/push.json"],
  ["Pull request", "examples/pull-request.json"],
  ["Failed rollout", "examples/deploy.json"],
];

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
  for (const c of children) if (c !== null && c !== undefined) node.append(typeof c === "string" ? document.createTextNode(c) : c);
  return node;
}

function str(v) { return typeof v === "string" ? v : v === null || v === undefined ? "" : String(v); }

function validate(data) {
  if (!data || typeof data !== "object" || !Array.isArray(data.assessments) || !Array.isArray(data.evidence)) {
    throw new Error("This is not a GroundClaim report (expected the JSON from `groundclaim check -f json`).");
  }
  return data;
}

function render(data, name) {
  const root = document.getElementById("report");
  root.replaceChildren();
  const counts = {};
  for (const a of data.assessments) counts[a.verdict] = (counts[a.verdict] || 0) + 1;
  const parts = ORDER.filter((v) => counts[v]).map((v) => `${counts[v]} ${LABEL[v]}`);
  root.append(el("h2", { class: "summary" }, `${data.assessments.length} claim(s)${parts.length ? ": " + parts.join(", ") : ""}`));
  const subject = data.subject && typeof data.subject === "object" ? data.subject : {};
  const meta = Object.entries(subject).filter(([, v]) => v !== null && v !== "").map(([k, v]) => `${k}: ${str(v)}`);
  root.append(el("p", { class: "meta" }, [name, ...meta, `schema ${str(data.schema_version)}`].filter(Boolean).join(" · ")));
  for (const w of Array.isArray(data.warnings) ? data.warnings : []) {
    root.append(el("div", { class: "card warning" }, el("span", { class: "verdict insufficient_evidence" }, "warning "), str(w)));
  }
  const evidence = new Map(data.evidence.map((e) => [e.id, e]));
  for (const a of data.assessments) {
    const v = ICON[a.verdict] ? a.verdict : "unverifiable";
    const card = el("section", { class: "card" },
      el("div", {}, el("span", { class: `verdict ${v}` }, `${ICON[v]} ${LABEL[v]}`), el("span", { class: "tag" }, str(a.claim && a.claim.type))),
      el("blockquote", {}, str(a.claim && a.claim.text)),
      el("div", {}, str(a.reason)));
    const links = Array.isArray(a.links) ? a.links : [];
    if (links.length) {
      const list = el("ul", { class: "links" });
      for (const l of links) {
        const e = evidence.get(l.evidence) || {};
        list.append(el("li", {}, el("strong", {}, str(l.stance)), el("span", { class: "tag" }, str(e.provenance)), " ", str(l.reason),
          el("div", { class: "small" }, [str(e.kind), str(e.source), l.decisive ? "decisive" : ""].filter(Boolean).join(" · "))));
      }
      card.append(el("details", {}, el("summary", {}, `evidence (${links.length})`), list));
    }
    root.append(card);
  }
}

function showError(message) {
  const error = document.getElementById("error");
  error.textContent = message;
  error.hidden = false;
  document.getElementById("report").replaceChildren();
}

function show(text, name) {
  try {
    render(validate(JSON.parse(text)), name);
    document.getElementById("error").hidden = true;
  } catch (err) {
    showError(err instanceof SyntaxError ? "The file is not valid JSON." : err.message);
  }
}

async function loadExample(url, button) {
  for (const b of document.querySelectorAll("#examples button")) b.setAttribute("aria-pressed", String(b === button));
  document.getElementById("report").replaceChildren(el("p", { class: "muted" }, "Loading…"));
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Could not load the example (${res.status}).`);
  show(await res.text(), button.textContent);
}

const file = document.getElementById("file");
const drop = document.getElementById("drop");
file.addEventListener("change", async () => {
  const f = file.files[0];
  file.value = ""; // so that choosing the same file again reloads it
  if (f) show(await f.text(), f.name);
});
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", async (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  const f = e.dataTransfer.files[0];
  if (f) show(await f.text(), f.name);
});
const box = document.getElementById("examples");
for (const [label, url] of EXAMPLES) {
  const b = el("button", { type: "button", "aria-pressed": "false" }, label);
  b.addEventListener("click", () => void loadExample(url, b).catch((err) => showError(err.message)));
  box.append(b);
}
const first = box.querySelector("button");
if (first) void loadExample(EXAMPLES[0][1], first);
