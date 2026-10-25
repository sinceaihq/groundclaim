# Security Policy

## Reporting a vulnerability

**Use GitHub's private vulnerability reporting:**
**[Report a vulnerability](https://github.com/sinceaihq/groundclaim/security/advisories/new)**

If that is unavailable to you, email **builders@sinceai.fi**. Please do not open a public issue for a suspected
vulnerability, and never paste secrets, private code or personal data into an issue.

We aim to acknowledge reports within a few working days. GroundClaim is maintained by a small team and we do not
promise a fixed remediation deadline.

## Threat model

GroundClaim is run on the output of an AI agent that may be mistaken, manipulated or adversarial. Everything it reads
is untrusted:

| input | risk | how it is handled |
|---|---|---|
| the git repository | repository-local config can make read commands run programs (fsmonitor, hooks, external diff, textconv, content filters, signature programs) | every git call overrides those settings, including each configured `filter.<name>.*`; system config is ignored; tested against a repository that plants all of them |
| the agent's message, PR description | injection into shells, Markdown, HTML | never executed or interpolated into a shell; escaped in Markdown; the HTML report has a no-script Content Security Policy; the GitHub Action reads it from the event file in Python |
| traces | commands to run, secrets in output, huge or malformed files | commands are classified as text and never executed; command lines and output tails are redacted before they are stored; size limits; bounded regular expressions (tested on adversarial input) |
| test reports | XML entity expansion, huge files | XML with a DTD is refused; size limit |
| revision and branch names from claims | option injection into git | validated against a strict pattern; never start with `-`; no `..` |
| claimed file paths | reading outside the workspace | resolved and confined to the workspace; symbolic links are not followed |
| the GitHub API | — | GET requests only; the token is read from the environment and never written to reports |

The only code GroundClaim runs is a command you give it yourself with `--run-tests` (split without a shell).

## Scope

In scope: any way for the checked material to make GroundClaim execute code, read files outside the workspace, write
anywhere other than the requested output, leak a token or a secret into a report, or crash or hang on a small input.
**False confirmations** (a verdict of `confirmed` for something that did not happen, given the documented sources) are
treated as serious bugs; please report them with a minimal reproduction.

Out of scope: wrong verdicts caused by a dishonest trace recorder (traces are only *observed* evidence by design), and
the documented limitations in the README.
