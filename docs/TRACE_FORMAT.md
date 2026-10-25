# Traces

A trace is a record of what the agent did while it worked. GroundClaim reads it as **observed** evidence: commands with
their exit codes and output, files written, and the agent's messages (the last one is the default message to check).
Commands in a trace are classified by their text and **never executed**.

The format is detected automatically.

## GroundClaim JSONL

One JSON object per line. Unknown fields are ignored; lines that are not JSON are skipped.

```json
{"type": "file_write", "path": "src/pager.py", "time": "2026-10-20T09:12:40Z"}
{"type": "command", "command": "pytest -q", "exit_code": 1, "output": "…2 failed, 40 passed in 1.31s", "time": "2026-10-20T09:13:02Z", "revision": "8c2e41d"}
{"type": "message", "role": "assistant", "text": "Fixed the bug; all tests pass.", "time": "2026-10-20T09:14:00Z"}
```

| field | type | notes |
|---|---|---|
| `type` | `command`, `file_write`, `message` | |
| `command` | string | the command line as run |
| `exit_code` | integer or null | null = unknown (still running, interrupted) |
| `output` | string | stdout and stderr; only the end (where test summaries are) is used and stored, redacted |
| `path` | string | for `file_write` |
| `text`, `role` | string | for `message`; only `assistant` messages are used |
| `time` | ISO 8601 | optional; used to tell whether a test report predates the last edit |
| `revision` | string | optional git commit at the time |

Write it from a harness with `groundclaim.Recorder` (see the README). The harness — not the agent — should write the
trace: an agent that can edit its own trace can write anything into it.

## Claude Code session transcripts

The JSONL files Claude Code keeps for each session (`~/.claude/projects/<project>/<session>.jsonl`). GroundClaim reads
`Bash` tool calls and their results (exit code from the `Exit code N` prefix or the error flag; background commands
have no exit code), `Edit`/`Write`/`MultiEdit`/`NotebookEdit` calls as file writes, and assistant text. Sub-agent
(sidechain) entries are skipped. This format is not a published interface and may change; the adapter is best-effort.

## OpenTelemetry GenAI spans

OTLP JSON (`{"resourceSpans": …}`) or one span per line, following the
[GenAI semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai) (still in development):
spans with `gen_ai.operation.name = execute_tool` or a `gen_ai.tool.name`. The command is taken from the JSON
`gen_ai.tool.call.arguments` (`command`, `cmd` or `script`); the exit code from the JSON `gen_ai.tool.call.result`
(`exit_code`, `exitCode`, `returncode`, …). Without one, an error span status counts as a failure and anything else
as unknown. Tool calls with a `path`/`file_path` argument and a write-like tool name are file writes.

## OpenInference spans

Spans with `openinference.span.kind = TOOL`: arguments from `input.value` (or `tool.parameters`), result from
`output.value`, mapped as above.

## What a command is

| category | examples |
|---|---|
| test | `pytest`, `python -m pytest`, `npm test`, `jest`, `vitest`, `mocha`, `go test`, `cargo test`, `mvn test`, `gradle test`, `dotnet test`, `rspec`, `phpunit`, `tox`, `make test`, `playwright test`, … (also behind `uv run`, `npx`, `poetry run`, `timeout`, `VAR=value`) |
| build | `npm run build`, `tsc`, `cargo build`, `go build`, `python -m build`, `docker build`, `make`, … |
| lint | `ruff`, `flake8`, `mypy`, `pyright`, `eslint`, `tsc --noEmit`, `prettier --check`, `cargo clippy`, `golangci-lint`, … |
| commit, push, pr | `git commit`, `git push`, `gh pr create` |
| deploy | `vercel`, `netlify deploy`, `fly deploy`, `kubectl apply`, `helm upgrade`, `terraform apply`, `wrangler deploy`, … |
| release | `gh release create`, `npm publish`, `twine upload`, `cargo publish`, `git tag` |
| self-report | `echo`/`printf` that print success words |

Flags: `exit_masked` (`| tail`, `|| true`, `set +e`), `subset` (`-k`, `::test`, `--grep`, …), `background` (`&`,
`nohup`).
