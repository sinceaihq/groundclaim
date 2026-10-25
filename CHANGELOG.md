# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-25

First public release.

### Added

- Claim extraction for 12 claim types (tests, build, lint, code changes, bug fixes, commits, pushes, pull requests,
  deployments, releases, files, whole-task) with negation, hedging, plan and question handling.
- Evidence from git (read-only, hardened against repository-local configuration), traces (GroundClaim JSONL, Claude
  Code transcripts, OpenTelemetry GenAI and OpenInference spans), JUnit and CTRF test reports, the GitHub API
  (check runs, commit statuses, branches, pull requests, deployments, releases), the filesystem, and an opt-in test
  re-run.
- Verdicts with provenance levels (self-reported, observed, independent, attested) and documented rules.
- Command line (`check`, `claims`, `render`, `schema`), Python API, trace `Recorder`, GitHub Action.
- JSON report with JSON Schema; text, Markdown and self-contained HTML output.
- GroundClaim-Bench: scripted agent episodes with computed ground truth, baselines and metrics; a hand-labelled set of
  realistic claim sentences.
