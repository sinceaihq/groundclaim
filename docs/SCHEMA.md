# Report format (schema 0.1)

`groundclaim check -f json` writes a report; `groundclaim schema` prints its
[JSON Schema](../src/groundclaim/report.schema.json) (draft 2020-12). Reports are validated against it in the tests.

```json
{
  "schema_version": "0.1",
  "subject": {"tool": "groundclaim 0.1.0", "repository": "/work/app", "head": "8c2e41d…", "branch": "main",
              "base": "3f9a1c2", "uncommitted_files": 0, "trace": "run.jsonl (groundclaim)", "github": "owner/app"},
  "assessments": [
    {
      "claim": {"id": "c1", "type": "tests_passed", "text": "All 42 tests pass.", "span": [41, 59],
                "details": {"count": 42}},
      "verdict": "contradicted",
      "reason": "`pytest -q` exited 1: 2 failed, 40 passed",
      "links": [{"evidence": "e1", "stance": "contradicts", "reason": "`pytest -q` exited 1: 2 failed, 40 passed",
                 "decisive": false}]
    }
  ],
  "evidence": [
    {"id": "e1", "kind": "command", "provenance": "observed", "source": "run.jsonl#7", "summary": "pytest -q → exit 1",
     "revision": null, "time": "2026-10-20T09:14:03Z",
     "data": {"command": "pytest -q", "exit_code": 1, "output_tail": "…", "counts": {"passed": 40, "failed": 2},
              "flags": []}}
  ],
  "warnings": []
}
```

## Fields

**claim**

| field | meaning |
|---|---|
| `id` | `c1`, `c2`, … in message order |
| `type` | `tests_passed`, `build_succeeded`, `lint_clean`, `code_changed`, `bug_fixed`, `committed`, `pushed`, `pr_opened`, `deployed`, `released`, `file_created`, `task_completed` |
| `text`, `span` | the sentence the claim was found in, and its `[start, end)` character offsets in the message |
| `details` | specifics from the sentence: `files`, `path`, `commit`, `branch`, `pr`, `environment`, `version`, `count`, `hedged` ("should pass") |

**assessment**: `verdict` (`confirmed`, `supported`, `contradicted`, `insufficient_evidence`, `unverifiable`), a
one-line `reason`, and `links` to evidence with `stance` (`supports`, `contradicts`, `neutral`) and `decisive`.

**evidence**: `kind` (`command`, `test_report`, `git_diff`, `git_commit`, `git_status`, `git_ref`, `git_tag`,
`ci_check`, `commit_status`, `github_branch`, `github_pr`, `deployment`, `github_release`, `file`, `file_write`),
`provenance` (`self_reported`, `observed`, `independent`, `attested`), `source` (a file and line, `git`,
`github:owner/repo`, `filesystem`, `groundclaim --run-tests`), a human `summary`, the `revision` and `time` it is about
when known, and kind-specific `data`. Command output is stored as a redacted tail (secrets removed), never in full.

## Compatibility

The schema version changes when a field is removed or its meaning changes. New optional fields, claim types or
evidence kinds may be added within `0.x`; consumers should ignore what they do not know.
