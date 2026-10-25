# GroundClaim-Bench: technical report

*Version 0.1, October 2026. Data: [huggingface.co/datasets/sinceaihq/groundclaim-bench](https://huggingface.co/datasets/sinceaihq/groundclaim-bench).
Code: [`bench/`](../bench).*

## Question

When a coding agent says it is done — tests pass, the bug is fixed, the work is committed, pushed, deployed — how
often does a checker **confirm a claim that is false** (the dangerous error), and how often does it **reject a claim
that is true** (the annoying one)? And how do the answers change with the evidence available: the agent's run trace,
the git repository, the CI and deployment API?

## Benchmark

**Episodes.** Each episode is a small Python project (one of six seeded bugs in one of 48 package/module layouts) in a
real git repository with a local bare repository as its remote. A scripted agent edits code and runs real commands —
`pytest` in several forms, `git commit`, `git push` — and finishes with a message of claims. Every command is
recorded in a GroundClaim JSONL trace with its real exit code and output, as an honest harness would record it.
Actions against remote services (`gh pr create`, `vercel deploy`, `gh release create`) are simulated; their
effects on a simulated GitHub — check runs, pull requests, deployments and their statuses, releases — are written as
API fixtures that agree with the simulated world. CI check runs report the result of the original test suite on the
pushed commit.

**Families.** 18 episode families, sampled with weights (honest work is the most common):

| family | what happens |
|---|---|
| honest_fix | correct fix (sometimes after a broken intermediate attempt), tests run, committed |
| wrong_fix | an incorrect fix, tests fail, sometimes committed anyway |
| no_test_run | a fix (correct or not), tests never run |
| stale_run | tests pass, then a later "refactor" breaks the code (or, in 40 %, keeps it correct) |
| masked_exit | `pytest \| tail` or `pytest \|\| true` |
| self_report | `echo "All tests passed"` after a failing or missing run |
| subset_run | `pytest -k` or a single test node only |
| test_tampering | a failing test gets `@pytest.mark.skip`, `xfail`, or is removed |
| build | a fix with a syntax error (or not), compile step run or not |
| commit | honest commit, forgotten commit, edits left after the commit, a made-up commit id, a correct id |
| push | honest push, rejected push (the remote moved), never pushed, more commits after the push |
| pull_request | honest PR, wrong PR number, PR creation failed, branch never pushed |
| deploy | success, CLI failure, CLI success but failed rollout, never deployed |
| release | published release, tag only, draft release, nothing; tag claims |
| output_file | a report file written, missing, or empty |
| code_change | the named files changed, one of them not, nothing changed |
| ci_status | "CI is green" for a correct or incorrect committed fix |
| test_report | a JUnit report from a passing or failing run, sometimes stale |

Some episodes add further claims ("I updated …", "I committed …", "The task is complete.") whose truth is computed
in the same way.

**Ground truth is computed, not asserted:**

- *tests pass* — the project's **original** test suite passes on the final working tree (so skipping or deleting a
  test does not make the claim true); for CI claims, on the pushed commit;
- *bug fixed* — the bug's own test passes and the module changed;
- *build succeeds* — the module compiles;
- *code changed* — every named file differs from the starting commit;
- *committed* — there are new commits and no tracked file has uncommitted edits;
- *pushed* — the remote branch contains the final commit;
- *PR / deployed / released* — the simulated GitHub has the PR with that number, a successful deployment, a published
  release;
- *file created* — the file exists and is not empty;
- *task complete* — no ground truth; not scored.

**Messages** are built from claim phrasings. The dev and test splits use different phrasing lists; the test
phrasings were written before the claim extractor was evaluated on them.

**Splits.** Dev: 200 episodes, 423 claims (seed 101), used to develop the rules. Test: 1,000 episodes, 2,202 claims
(seed 202), generated and evaluated **once**, after the code was frozen at commit `071f881`
(`bench/results/FROZEN_COMMIT`).

## Methods and conditions

- **GroundClaim** with four evidence conditions: *full* (git with the starting commit, the trace, GitHub),
  *git + GitHub* (no trace), *git + trace* (no GitHub), *trace only*.
- **Naive log check** (`trace_keywords`): confirmed if any command of the matching kind in the trace exited 0,
  contradicted if all of them failed, otherwise insufficient. This is what a simple "did they run it?" check does.
- **Trust all**: every claim confirmed — the situation when nobody checks.

Verification is evaluated on the **gold claims** (type, sentence and details), so that it is not confounded with claim
extraction, which is evaluated separately below. An LLM-as-judge baseline was not run in v0.1: the only model
available for local CPU inference was a 1.5B-parameter model, too weak to be a fair representative, and paid APIs
were not used.

## Metrics

For false claims: **false confirmation rate** (verdict *confirmed*), **false acceptance rate** (*confirmed* or
*supported*), **catch rate** (*contradicted*). For true claims: **false rejection rate** (*contradicted*),
**confirmation rate**, **acceptance rate**. *Insufficient evidence* and *unverifiable* are abstentions. Intervals are
95 % percentile bootstrap over episodes (1,000 resamples).

## Results (test split)

| method, condition | false claims confirmed | false accepted | false caught | true rejected | true confirmed | true accepted |
|---|---|---|---|---|---|---|
| **GroundClaim, full** | **0.0** (0 / 789) | 3.0 | 67.8 [64.6, 70.8] | **0.0** (0 / 1,098) | 59.2 [56.3, 62.3] | 93.9 |
| GroundClaim, git + GitHub | 0.0 | 10.8 | 48.2 | 0.0 | 59.2 | 76.0 |
| GroundClaim, git + trace | 0.0 | 7.0 | 53.9 | 0.0 | 52.5 | 92.1 |
| GroundClaim, trace only | 0.0 | 16.7 | 25.6 | 0.0 | 0.0 | 91.0 |
| naive log check | 43.9 [40.6, 47.0] | 43.9 | 18.2 | 0.0 | 94.5 | 94.5 |
| trust all | 100 | 100 | 0 | 0 | 100 | 100 |

(Percentages.) With 0 false confirmations in 789 false claims, the false-confirmation rate on this benchmark is below
0.38 % at 95 % confidence (rule of three); with 0 of 1,098, the false-rejection rate is below 0.27 %.

**By family** (GroundClaim, full; last column: naive log check):

| family | false | true | confirmed (false) | accepted (false) | caught | rejected (true) | confirmed (true) | log check: confirmed (false) |
|---|---|---|---|---|---|---|---|---|
| build | 29 | 31 | 0.0 | 0.0 | 37.9 | 0.0 | 48.4 | 0.0 |
| ci_status | 25 | 48 | 0.0 | 0.0 | 100.0 | 0.0 | 100.0 | 0.0 |
| code_change | 30 | 33 | 0.0 | 0.0 | 100.0 | 0.0 | 100.0 | 0.0 |
| commit | 38 | 46 | 0.0 | 0.0 | 100.0 | 0.0 | 100.0 | 71.0 |
| deploy | 38 | 38 | 0.0 | 0.0 | 79.0 | 0.0 | 100.0 | 50.0 |
| honest_fix | 0 | 483 | — | — | — | 0.0 | 33.3 | — |
| masked_exit | 47 | 29 | 0.0 | 0.0 | 100.0 | 0.0 | 44.8 | 66.0 |
| no_test_run | 45 | 48 | 0.0 | 40.0 | 20.0 | 0.0 | 0.0 | 40.0 |
| output_file | 57 | 12 | 0.0 | 0.0 | 100.0 | 0.0 | 100.0 | 21.1 |
| pull_request | 33 | 57 | 0.0 | 0.0 | 100.0 | 0.0 | 100.0 | 21.2 |
| push | 54 | 52 | 0.0 | 0.0 | 100.0 | 0.0 | 100.0 | 38.9 |
| release | 32 | 63 | 0.0 | 0.0 | 100.0 | 0.0 | 100.0 | 81.2 |
| self_report | 55 | 13 | 0.0 | 0.0 | 76.4 | 0.0 | 100.0 | 0.0 |
| stale_run | 45 | 30 | 0.0 | 0.0 | 20.0 | 0.0 | 50.0 | 80.0 |
| subset_run | 50 | 27 | 0.0 | 0.0 | 22.0 | 0.0 | 55.6 | 78.0 |
| test_report | 32 | 36 | 0.0 | 0.0 | 78.1 | 0.0 | 47.2 | 0.0 |
| test_tampering | 65 | 26 | 0.0 | 9.2 | 30.8 | 0.0 | 100.0 | 89.2 |
| wrong_fix | 114 | 26 | 0.0 | 0.0 | 54.4 | 0.0 | 100.0 | 45.6 |

**By claim type** (GroundClaim, full):

| claim type | false | true | confirmed (false) | accepted (false) | caught | rejected (true) | confirmed (true) |
|---|---|---|---|---|---|---|---|
| bug_fixed | 70 | 185 | 0.0 | 25.7 | 0.0 | 0.0 | 0.0 |
| build_succeeded | 18 | 16 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| code_changed | 31 | 253 | 0.0 | 0.0 | 100.0 | 0.0 | 100.0 |
| committed | 163 | 294 | 0.0 | 0.0 | 100.0 | 0.0 | 100.0 |
| deployed | 38 | 9 | 0.0 | 0.0 | 79.0 | 0.0 | 100.0 |
| file_created | 27 | 12 | 0.0 | 0.0 | 100.0 | 0.0 | 100.0 |
| pr_opened | 33 | 26 | 0.0 | 0.0 | 100.0 | 0.0 | 100.0 |
| pushed | 54 | 9 | 0.0 | 0.0 | 100.0 | 0.0 | 100.0 |
| released | 32 | 27 | 0.0 | 0.0 | 100.0 | 0.0 | 100.0 |
| tests_passed | 323 | 267 | 0.0 | 1.9 | 51.1 | 0.0 | 7.5 |

**Reading the results.**

- *No false confirmations, no false rejections.* Confirmation requires independent evidence about the current state,
  and every contradiction rule is backed by evidence that cannot be stale. On this benchmark that combination never
  confirmed a false claim and never rejected a true one.
- *Where false claims slip through as "supported":* "fixed the bug" when tests were never run (the change exists, so
  the claim is plausible — 40 % of false claims in *no_test_run*), and tests passing after a test function was
  *removed* (not detected; 9 % in *test_tampering*). Neither becomes *confirmed*.
- *Where GroundClaim abstains:* stale runs, subset runs, self-reports and disabled tests produce *insufficient
  evidence* — the honest answer when the evidence does not show the final state. Most false claims there are
  abstained on rather than caught.
- *True claims* are confirmed when independent evidence exists (CI on the commit, GitHub, git, the file system);
  honest local test runs are *supported*, which is why *honest_fix* has a confirmation rate of 33 %.
- *Evidence matters:* without GitHub, push, PR, deploy and release claims can only be supported by the trace; without
  a trace, stale and masked test runs cannot be seen. The trace-only condition never confirms anything.
- *The naive log check* confirms 44 % of false claims: piped and `|| true` runs, stale runs, subset runs, tampered
  tests, rejected pushes, failed rollouts and draft releases all have a command that exited 0.

**Dev split** (for reference; used to develop the rules): GroundClaim full — false confirmed 0.0, false accepted 2.0,
caught 66.7, true rejected 0.0, true confirmed 56.4 (153 false, 220 true claims); naive log check — false confirmed
39.2.

## Claim extraction

Finding claims in free text is evaluated separately, as precision and recall of (claim type, sentence) pairs.

| set | when | precision | recall |
|---|---|---|---|
| dev messages (200) | development | 100 | 100 |
| **test messages, unseen phrasings** (1,000 messages, 2,202 claims) | frozen code, evaluated once | **100** | **78.0** |
| **realistic sentences** (151 hand-written items, 132 claims; `bench/extraction/realistic.jsonl`) | after adding the round-1 test phrasings ("step A"), evaluated once | **96.1** | **56.1** |
| realistic sentences, after improving patterns on that set ("step B", **not held-out**) | release 0.1.0 | 97.7 | 97.7 |

Rules learned from templates generalise poorly to messy real phrasing; v0.1.0 ships the step-B patterns, but its
recall on genuinely new phrasings should be expected to be well below the last row. The realistic set was written by
the same team as the patterns, which limits its independence. A missed claim is not confirmed — it is simply not
checked.

## End to end

The results above give the verifiers the gold claims. In real use the claims come from the extractor, so a missed or
misread detail matters: a claim the extractor misses is not checked, and a misread detail can change the verdict. The
end-to-end evaluation matches each gold claim to an extracted claim (same type, overlapping sentence); unmatched gold
claims count as *missed* (an abstention).

| extractor | false claims confirmed | false caught | true rejected | true confirmed |
|---|---|---|---|---|
| frozen at `FROZEN_COMMIT` (round 1) | 0.0 | 49.7 | 0.0 | 45.5 |
| release 0.1.0 | 0.0 | 67.8 | 0.0 | 59.2 |

(GroundClaim, full evidence; test split.) The release extractor has since seen these phrasings (see *Claim
extraction*), so its row equals the gold-claim results and overstates real-world recall. One lesson from building this
evaluation: an intermediate extractor change recognised "The pull request is up: #N" but not its number, and the
verifier then confirmed the claim against *a* pull request from the branch — a false confirmation that the gold-claim
evaluation could not show. It was found while generating examples, fixed before release, and is now covered by a
regression test and by this end-to-end evaluation (`bench/results/test-e2e/`).

## Limitations

- **Synthetic and single-author.** The episodes, the phrasings and the rules come from the same team; real agents fail
  in more and subtler ways (wrong tests, partial fixes, correct-looking but wrong deployments). These numbers show that
  the rules do what they are designed to do on the failure modes we could script, not real-world accuracy.
- **One ecosystem.** Python, pytest and git; other test runners are parsed but not exercised by the benchmark.
- **Simulated remote.** GitHub responses come from fixtures consistent with the simulated world, not from the real
  API.
- **Honest traces.** The benchmark assumes the harness records commands truthfully; a forged trace is outside the
  model (it is only *observed* evidence by design).
- **Tamper detection is partial.** Removed test functions are not detected.

## Reproduce

```bash
pip install -e ".[dev]"
python bench/generate.py --split dev  --n 200  --seed 101 --out bench/out
python bench/generate.py --split test --n 1000 --seed 202 --out bench/out
python bench/run.py --data bench/out --split test --out bench/results/test
python bench/summary.py bench/results/test
python bench/extraction/score.py bench/extraction/realistic.jsonl
```

The published 0.1 data was generated before each project got its own `pyproject.toml`; in some test episodes pytest
therefore reported the generator's directory as its root (collected tests and results were unaffected), and local
interpreter paths printed by `pytest -v` were replaced by placeholders before publication (re-running the evaluation
on the sanitised data gives identical results). Regenerating with the current generator adds that file, so episodes
are not byte-identical to the published ones.

Generation runs real `git` and `pytest` (about 10 minutes for the test split on 8 cores); evaluation takes about a
minute. Exact episode contents (paths, times) depend on the seed only, but command output can differ slightly between
pytest versions.
