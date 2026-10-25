# Contributing to GroundClaim

Contributions are very welcome — especially **wrong verdicts** (a false *confirmation* above all), **claim phrasings it
misses**, and **trace formats** of other agents and harnesses.

```bash
git clone https://github.com/sinceaihq/groundclaim.git
cd groundclaim
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest && ruff check . && ruff format --check . && mypy
```

## Where things are

| path | what |
|---|---|
| `src/groundclaim/claims.py` | finding claims in a message |
| `src/groundclaim/trace.py`, `reports.py`, `git.py`, `github.py` | evidence sources |
| `src/groundclaim/verify.py` | the verdict rules ([docs/RULES.md](docs/RULES.md)) |
| `src/groundclaim/render.py`, `cli.py`, `recorder.py` | output, command line, trace recorder |
| `action.yml`, `scripts/action_check.py` | the GitHub Action |
| `bench/` | GroundClaim-Bench generator, baselines, metrics, results; `bench/extraction/` claim-extraction sets |
| `tests/` | pytest suite, including a hostile-repository test and the Action |

## Typical changes

- **A wrong verdict.** Reproduce it as a test in `tests/test_verify.py` (the `Workspace` fixture scripts a repository
  and a trace), fix the rule in `verify.py`, and describe the rule in `docs/RULES.md`.
- **A missed claim.** Add the sentence to `tests/test_claims.py` (and a sentence that must *not* match), then extend
  the pattern. Run `python bench/extraction/score.py` on the dev and realistic sets to see that precision holds.
- **A new trace format.** Add a loader to `trace.py` with a small synthetic sample in `tests/test_trace.py`.
- **Benchmark.** The test split was evaluated once at the commit in `bench/results/FROZEN_COMMIT`. Do not tune rules
  on it; add new episode families to the generator and report new results as a new round in
  `docs/BENCHMARK.md`.

## Rules

- No secrets, private code or personal data in tests, fixtures, traces or issues — use made-up content.
- No runtime dependencies, no network requests other than read-only GitHub API calls, no code execution other than
  `--run-tests`.
- Commit messages in the imperative; one topic per pull request.
