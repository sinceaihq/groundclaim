# GroundClaim

**Check what an AI agent says it did against evidence of what actually happened.**

[![CI](https://github.com/sinceaihq/groundclaim/actions/workflows/ci.yml/badge.svg)](https://github.com/sinceaihq/groundclaim/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Benchmark](https://img.shields.io/badge/%F0%9F%A4%97%20dataset-groundclaim--bench-yellow)](https://huggingface.co/datasets/sinceaihq/groundclaim-bench)
[![Report viewer](https://img.shields.io/badge/%F0%9F%A4%97%20demo-report%20viewer-yellow)](https://huggingface.co/spaces/sinceaihq/groundclaim-viewer)

Coding agents end their work with a message such as *"Fixed the bug in `pager.py`, all 42 tests pass, committed and
pushed to main, PR #12 is open."* Sometimes that is true. Sometimes the tests were never run, ran before the last
edit, were piped through `tail` so a failure looked like success, or were quietly marked `skip`. GroundClaim reads
the message, finds each claim, and checks it against sources it queries itself:

| claim | checked against |
|---|---|
| tests pass, build succeeds, lint is clean | the agent's commands in a run trace (exit codes, printed summaries, order), JUnit/CTRF reports, GitHub check runs for the exact commit, or a test run GroundClaim does itself |
| code changed, bug fixed | `git diff` since the starting commit, edits in the trace |
| committed, pushed | git history, the remote branch on GitHub, commands in the trace |
| PR opened, deployed, released | GitHub pull requests, deployments and their statuses, tags and releases |
| file created | the file on disk |

Each claim gets a verdict — **confirmed**, **supported**, **contradicted**, **insufficient evidence** or
**unverifiable** — with the evidence and the reason. GroundClaim is deterministic (no language model), reads git
without letting the repository run anything, never executes commands found in traces, and has no runtime
dependencies.

Real output of [examples/demo.sh](examples/demo.sh) (needs pytest) — an agent "fixes" a pager bug, pipes the failing tests
through `tail`, commits, and reports success:

```text
$ groundclaim check --repo demo-repo --base afde81f --trace demo-run.jsonl
4 claim(s): 2 contradicted, 1 insufficient evidence, 1 confirmed

? insufficient evidence  [bug_fixed] Fixed the off-by-one bug in `src/pager.py`.
    src/pager.py changed since afde81f; but the latest test run fails (output of `pytest -q | tail -n 3`: 2 failed, 0 passed (its exit code is not the test runner's))
      + (independent) src/pager.py changed since afde81f
      + (observed) the trace shows an edit of src/pager.py
      · (observed) tests fail after the change: output of `pytest -q | tail -n 3`: 2 failed, 0 passed (its exit code is not the test runner's)

✘ contradicted  [tests_passed] All 2 tests pass.
    output of `pytest -q | tail -n 3`: 2 failed, 0 passed (its exit code is not the test runner's)
      - (observed) output of `pytest -q | tail -n 3`: 2 failed, 0 passed (its exit code is not the test runner's)

✔ confirmed  [committed] I committed the fix.
    1 new commit(s) since afde81f
      + (observed) `git commit -am 'Fix page count'` exited 0
      + (independent) 1 new commit(s) since afde81f

✘ contradicted  [code_changed] I also updated `docs/pager.md`.
    docs/pager.md was not changed since afde81f
      - (independent) docs/pager.md was not changed since afde81f
```

## Install

```bash
pip install "groundclaim @ git+https://github.com/sinceaihq/groundclaim@v0.1.0"
```

Python 3.10+, git on `PATH`. No other dependencies.

## Use

```bash
# The message as text, checked against the repository in the current directory
groundclaim check -m "All tests pass. I committed the changes."

# Everything: starting commit, the run's trace, test reports, GitHub (token from GITHUB_TOKEN)
groundclaim check --base origin/main --trace run.jsonl --report junit.xml \
    --github owner/repo --message-file message.md --also html=report.html

# The final message straight from a Claude Code session transcript
groundclaim check --trace ~/.claude/projects/<project>/<session>.jsonl --base main

# Run the test command yourself as independent evidence (opt-in: this executes code)
groundclaim check -m "Tests pass." --run-tests "pytest -q"

groundclaim claims "Deployed to prod and opened PR #7."   # only list the claims
groundclaim render report.json -f html > report.html     # re-render a JSON report
groundclaim schema                                        # JSON Schema of the report
```

Output formats: `text` (default), `json`, `markdown` (PR comments, job summaries) and `html` (a self-contained page
with no scripts). Exit codes: `0` policy satisfied, `1` not satisfied, `2` bad input. By default only
**contradicted** claims fail; `--require supported` or `--require confirmed` raises the bar for every checkable
claim, and `--strict` also fails claims nothing could check.

## What the verdicts mean

| verdict | meaning |
|---|---|
| ✔ **confirmed** | Independent evidence about the current state establishes the claim — GroundClaim's own git query, a CI check run on the exact commit, a GitHub deployment or release, the file on disk, or a test run it made — and nothing contradicts it. |
| ◐ **supported** | Only *observed* evidence supports it (the harness recorded `pytest` exiting 0), or the claim is of a kind GroundClaim can only partly check ("fixed the bug": the change exists, whether it fixes the bug is a judgement). Plausible, not proven. |
| ✘ **contradicted** | Some evidence says otherwise: the latest test run failed, the file does not exist, the PR number is wrong, the remote does not have the commit. Contradiction overrides any support. |
| ? **insufficient evidence** | Nothing decisive either way — e.g. tests ran but code was edited afterwards, only some tests were selected, or tests were disabled since the start. |
| – **unverifiable** | None of the given sources can check this kind of claim (e.g. "deployed" without GitHub access), or it is a whole-task claim ("the task is complete") and no other claim was contradicted. |

Evidence carries a **provenance**: `self_reported` (the agent's own words or `echo "tests passed"` — never support),
`observed` (recorded by the harness that ran the agent), `independent` (queried by GroundClaim itself) and
`attested` (signed; reserved). The full rules, each with an example, are in [docs/RULES.md](docs/RULES.md); the
report format is in [docs/SCHEMA.md](docs/SCHEMA.md).

## GitHub Action

Check the claims in a pull request description — typically one written by a coding agent — against the PR's diff and
CI:

```yaml
name: GroundClaim
on:
  pull_request:
    types: [opened, edited, synchronize]
permissions:
  contents: read
  checks: read
  statuses: read
  pull-requests: read
  deployments: read
jobs:
  claims:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          ref: ${{ github.event.pull_request.head.sha }}   # the PR's own commit, where CI reports
          fetch-depth: 0
      - uses: sinceaihq/groundclaim@v0.1.0
        with:
          wait-for-checks: "900"        # let the PR's other CI jobs finish first
          ignore-checks: claims         # this job's own name
```

The report appears in the job summary; the job fails if a claim is contradicted (or does not meet `require`). The
description is treated as data: it is read from the event file, never interpolated into a shell. All inputs are in
[action.yml](action.yml) and [docs/GITHUB_ACTION.md](docs/GITHUB_ACTION.md). This repository's own CI runs the action
on itself.

## In Python, and recording traces

```python
from pathlib import Path
from groundclaim import Recorder, Sources, verify
from groundclaim.git import Repo
from groundclaim.trace import load_trace

# In an agent harness: record what the agent does (the harness, not the agent, should write this)
with Recorder("run.jsonl") as rec:
    rec.file_write("src/app.py")  # a file the agent changed
    rec.run(["pytest", "-q"])  # runs the command (no shell) and records exit code and output tail
    rec.message("Fixed the parser; all tests pass.")

# Afterwards: check the final message
_, events = load_trace(Path("run.jsonl"))
report = verify(
    "Fixed the parser; all tests pass.", Sources(repo=Repo(Path(".")), base="main", events=events)
)
for a in report.assessments:
    print(a.verdict, a.claim.text, a.reason)
```

Traces can also be Claude Code session transcripts (best effort — the format is not a published interface),
OpenTelemetry spans following the GenAI semantic conventions (OTLP JSON or JSONL) and OpenInference spans. See
[docs/TRACE_FORMAT.md](docs/TRACE_FORMAT.md). Secrets are redacted from everything GroundClaim stores in a report.

## How well does it work?

**GroundClaim-Bench** ([dataset](https://huggingface.co/datasets/sinceaihq/groundclaim-bench),
[generator](bench/generate.py)): scripted coding-agent episodes in real git repositories, with real `pytest` and
`git` runs, a local bare remote, and a simulated GitHub (checks, PRs, deployments, releases). Truth is *computed*:
"tests pass" is true only if the project's **original** test suite passes on the final code, "pushed" only if the
remote branch contains the final commit, and so on. Besides honest work, 17 episode families produce false or
misleading completions (mixed with honest variants): failing tests, stale runs, `| tail` and `|| true`, `echo "All tests passed"`, `-k` subsets, skipped or
removed tests, forgotten commits, rejected pushes, wrong PR numbers, failed rollouts, draft releases, missing files.

The rules were developed on a 200-episode dev split; the code was then frozen and a 1,000-episode test split with a
fresh seed and unseen message phrasings was generated and evaluated **once**. Claims given to the verifiers are the
gold claims, so these numbers measure verification, not claim extraction.

| test split — 2,202 claims (789 false, 1,098 true, 315 whole-task claims not scored) | false claims **confirmed** | false claims accepted (confirmed or supported) | false claims caught (contradicted) | true claims **rejected** | true claims confirmed |
|---|---|---|---|---|---|
| **GroundClaim**, git + trace + GitHub | **0.0 %** (0 / 789) | 3.0 % | 67.8 % | **0.0 %** (0 / 1,098) | 59.2 % |
| GroundClaim, git + GitHub, no trace | 0.0 % | 10.8 % | 48.2 % | 0.0 % | 59.2 % |
| GroundClaim, git + trace, no GitHub | 0.0 % | 7.0 % | 53.9 % | 0.0 % | 52.5 % |
| GroundClaim, trace only | 0.0 % | 16.7 % | 25.6 % | 0.0 % | 0.0 % |
| naive log check (a matching command exited 0) | 43.9 % | 43.9 % | 18.2 % | 0.0 % | 94.5 % |
| trusting the agent | 100 % | 100 % | 0 % | 0 % | 100 % |

Zero of 789 means a false-confirmation rate below about 0.4 % with 95 % confidence *on this benchmark*. Claim
extraction from free text is the weaker part: it found every claim in the dev phrasings, 78 % in the unseen test
phrasings, and 56 % (precision 96 %) in a separate hand-written set of realistic agent sentences; after improving the
patterns on that set, recall there is 98 % — but that number is no longer held-out. Method, per-family results and
limitations: [docs/BENCHMARK.md](docs/BENCHMARK.md).

## Limitations

- **Synthetic benchmark.** The episodes are scripted by the same team that wrote the rules, in one language
  (Python/pytest) and one message style. Real agents fail in more ways. Numbers are evidence that the rules do what
  they say, not a real-world accuracy.
- **Claims are found with English patterns.** Unusual phrasings are missed (a missed claim is reported as nothing,
  not as confirmed). Other languages are not supported.
- **"Confirmed" means the evidence agrees, not that the work is good.** A test suite that passes may test the wrong
  thing; a deployment that succeeded may deploy a bug. Removing a test function (rather than skipping it) is not
  detected; deleted test files and added skip/xfail markers are.
- **Traces are only as honest as their recorder.** Observed evidence assumes the harness recorded commands truthfully.
  Signed attestations (Sigstore / in-toto) are reserved in the schema but not verified yet.
- **GitHub only** for remote evidence in v0.1 (no GitLab, package registries or cloud deploy APIs).

## Security

GroundClaim treats everything it reads as untrusted: the repository (git runs with fsmonitor, hooks, external diff,
textconv, content filters and signature programs switched off — tested against a repository that plants all of them),
traces (never executed; secrets redacted in reports), test reports (XML with DTDs refused), the agent's message
(escaped in Markdown and HTML; the HTML report has a no-script CSP) and the GitHub API (GET only). The only code it
ever runs is a command you pass yourself with `--run-tests`. See [SECURITY.md](SECURITY.md).

## Related work

GroundClaim follows ideas from [SLSA provenance](https://slsa.dev/spec/v1.1/provenance) (who produced the evidence
matters), the [SWE-bench harness](https://github.com/SWE-bench/SWE-bench) (re-run tests rather than trust them) and
research on agents reporting false success (Advani 2026, [arXiv:2606.09863](https://arxiv.org/abs/2606.09863); Zhu et
al. 2026, [arXiv:2609.35732](https://arxiv.org/abs/2609.35732)). Similar tools: [Chainloop](https://github.com/chainloop-dev/chainloop)
(signed attestations and policy gates), [GenRamzi/AgentProof](https://github.com/GenRamzi/AgentProof) (re-runs tests on
base and head), [ralabarta/agentproof](https://github.com/ralabarta/agentproof) (evidence reports from sessions),
LLM-judge task-completion metrics such as [DeepEval's](https://deepeval.com/docs/metrics-task-completion). GroundClaim's
focus is a published verdict semantics with provenance levels and a measured false-confirmation rate.

## Contributing

Wrong verdicts — especially a false **confirmation** — and missed claim phrasings are the most useful reports. See
[CONTRIBUTING.md](CONTRIBUTING.md).

Made by [Since AI](https://sinceai.ai), a non-profit association in Finland. Apache-2.0.
