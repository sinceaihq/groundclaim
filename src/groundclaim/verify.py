"""Match claims against evidence and decide a verdict for each.

Rules (docs/RULES.md explains each with examples):

1. Contradicting evidence (observed or better) overrides any support.
2. ``confirmed`` needs a *decisive* link: independent or attested evidence about
   the current state (the checked-out revision, or the working tree) that by
   itself establishes the claim.
3. Evidence for another commit, a run that was followed by further code edits,
   or a run of only some tests never confirms; it is linked as neutral or as
   partial support.
4. Signs that tests were disabled or deleted (skip/xfail markers added, test
   files removed) leave a test claim at ``insufficient_evidence`` at best: the
   passing run no longer shows what the claim says.
5. ``bug_fixed`` is at most ``supported``: that a change fixes a bug is a
   judgement GroundClaim does not make. If the latest complete test run fails,
   it is at most ``insufficient_evidence``.
6. The agent's own output (``echo "tests passed"``) never counts as support.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .claims import extract_claims
from .git import GitError, Repo, find_test_tampering
from .github import GitHub, GitHubError
from .model import (
    PROVENANCE_ORDER,
    SCHEMA_VERSION,
    Assessment,
    Claim,
    Evidence,
    Link,
    Provenance,
    Report,
    Stance,
    Verdict,
)
from .reports import TestRun
from .trace import Event, parse_test_output

# What a printed success message must mention to count as a claim about tests, a build or lint.
SELF_REPORT_TOPIC = {
    "test": re.compile(r"\btests?\b|\bpass(?:ed|es|ing)?\b|\bgreen\b", re.IGNORECASE),
    "build": re.compile(r"\bbuil[dt]|\bcompil", re.IGNORECASE),
    "lint": re.compile(r"\blint|\btype ?check|\bmypy\b|\beslint\b|\bruff\b", re.IGNORECASE),
}
DOC_FILE_RE = re.compile(
    r"\.(?:md|rst|txt|adoc)$|(?:^|/)(?:CHANGELOG|README|LICENSE|NOTICE)[^/]*$", re.IGNORECASE
)
CHECK_NAME = {
    "test": re.compile(r"test|spec|pytest|jest|vitest|e2e|unit|integration|check|ci\b|verify", re.IGNORECASE),
    "build": re.compile(r"build|compile|package|bundle|ci\b", re.IGNORECASE),
    "lint": re.compile(r"lint|ruff|eslint|mypy|type|format|prettier|clippy|style|static", re.IGNORECASE),
}


@dataclass
class CommandRun:
    """A test command GroundClaim ran itself (opt-in, from the CLI's --run-tests)."""

    command: str
    exit_code: int
    output: str
    revision: str | None


@dataclass
class Sources:
    repo: Repo | None = None
    base: str | None = None  # the revision the agent started from
    reports: list[TestRun] = field(default_factory=list)
    reports_trusted: bool = False  # reports produced outside the agent's control (e.g. by CI)
    events: list[Event] | None = None
    trace_name: str | None = None
    github: GitHub | None = None
    workspace: Path | None = None  # where claimed files are looked up (defaults to the repository)
    runs: list[CommandRun] = field(default_factory=list)


class Verifier:
    def __init__(self, sources: Sources):
        self.s = sources
        self.evidence: list[Evidence] = []
        self._keys: dict[str, str] = {}
        self.warnings: list[str] = []
        self.head: str | None = None
        self.branch: str | None = None
        self.dirty_code: list[str] = []  # uncommitted changes to non-documentation files
        self.uncommitted: list[tuple[str, str]] = []
        self.changed: set[str] | None = None  # files changed since base, including the working tree
        self.tampering: list[str] = []
        base = sources.base or ""
        self.base_label = base[:12] if re.fullmatch(r"[0-9a-f]{13,40}", base) else base
        self._git_setup()

    # --- evidence bookkeeping ------------------------------------------------------------

    def add(self, key: str, kind: str, provenance: Provenance, source: str, summary: str, revision: str | None = None,
            time: str | None = None, **data: Any) -> str:  # fmt: skip
        if key in self._keys:
            return self._keys[key]
        eid = f"e{len(self.evidence) + 1}"
        self.evidence.append(Evidence(eid, kind, provenance, source, summary, revision, time, data))
        self._keys[key] = eid
        return eid

    def prov(self, eid: str) -> int:
        return PROVENANCE_ORDER[self.evidence[int(eid[1:]) - 1].provenance]

    def warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)

    # --- repository state ----------------------------------------------------------------

    def _git_setup(self) -> None:
        repo = self.s.repo
        if repo is None:
            return
        try:
            self.head = repo.head()
            self.branch = repo.branch()
            self.uncommitted = repo.uncommitted()
            # tracked files with uncommitted edits (untracked files are not part of any revision either way)
            self.dirty_code = [p for st, p in self.uncommitted if st != "??" and not DOC_FILE_RE.search(p)]
            if self.s.base:
                if repo.resolve(self.s.base) is None:
                    self.warn(f"base revision {self.s.base!r} not found; changes since base are not checked")
                    self.s.base = None
                else:
                    self.changed = {p for _, p in repo.changed_files(self.s.base, None)}
                    self.changed |= {p for st, p in self.uncommitted if st == "??"}
                    self.tampering = find_test_tampering(repo, self.s.base, None)
                    for t in self.tampering:
                        self.warn(f"possible test tampering: {t}")
        except GitError as exc:
            self.warn(f"git: {exc}")
            self.s.repo = None

    def same_revision(self, rev: str | None) -> bool:
        return bool(
            rev and self.head and (self.head.startswith(rev.lower()) or rev.lower().startswith(self.head))
        )

    # --- per-category runs: tests, build, lint -------------------------------------------

    def _code_written_after(self, index: int) -> Event | None:
        for ev in self.s.events or []:
            if ev.index > index and ev.kind == "file_write" and ev.path and not DOC_FILE_RE.search(ev.path):
                return ev
        return None

    def _code_written_since(self, when: str | None) -> Event | None:
        t = _parse_time(when)
        if t is None:
            return None
        for ev in self.s.events or []:
            et = _parse_time(ev.time)
            if (
                ev.kind == "file_write"
                and et is not None
                and et > t
                and ev.path
                and not DOC_FILE_RE.search(ev.path)
            ):
                return ev
        return None

    def tests_failing_now(self) -> Link | None:
        """The latest complete test run in the trace, if it failed and no code was edited after it."""
        probe = Claim("probe", "tests_passed", "", (0, 0), {})
        for link, _ in self.run_links("test", probe):
            if link.stance == "contradicts" and self.prov(link.evidence) >= 1:
                return link
        return None

    def run_links(self, category: str, claim: Claim) -> list[tuple[Link, bool]]:
        """Links for a tests/build/lint claim; the bool marks a decisive link."""
        links: list[tuple[Link, bool]] = []
        count = claim.details.get("count")

        def judge_counts(counts: dict[str, int] | None, subset: bool = False) -> tuple[str, str] | None:
            if not counts:
                return None
            failed = counts.get("failed", 0) + counts.get("errors", 0)
            passed = counts.get("passed", 0)
            if failed:
                return "contradicts", f"{failed} failed, {passed} passed"
            if passed == 0:
                return "contradicts", "no tests ran"
            if (
                count is not None
                and not subset
                and count != passed
                and count != passed + counts.get("skipped", 0)
            ):
                return "contradicts", f"the claim says {count}, the run shows {passed} passed"
            skipped = counts.get("skipped", 0)
            return "supports", f"{passed} passed" + (f", {skipped} skipped" if skipped else "")

        # 1. commands in the trace (observed): the latest complete run decides
        events = [e for e in (self.s.events or []) if e.kind == "command" and category in e.categories]
        for ev in [e for e in self.s.events or [] if e.kind == "command" and "fake_report" in e.categories]:
            if SELF_REPORT_TOPIC[category].search(ev.command or ""):
                eid = self.add(f"ev:{ev.source}", "command", "self_reported", ev.source,
                               f"the agent printed a success message itself: {ev.command}")  # fmt: skip
                links.append((Link(eid, "neutral", "printed by the agent, not produced by a tool"), False))
                self.warn(
                    f"{ev.source}: the agent printed its own success message ({(ev.command or '')[:60]})"
                )
        finished = [e for e in events if e.exit_code is not None and "background" not in e.flags]
        full = [e for e in finished if "subset" not in e.flags]
        chosen = (full or finished)[-1:] if finished else []
        for ev in chosen:
            subset = "subset" in ev.flags
            counts = parse_test_output(ev.output) if category == "test" else None
            judged = judge_counts(counts, subset)
            if "exit_masked" in ev.flags:
                if judged:
                    stance, reason = judged
                    reason = f"output of `{ev.command}`: {reason} (its exit code is not the test runner's)"
                else:
                    stance, reason = (
                        "neutral",
                        f"`{ev.command}` hides the tool's exit code and printed no summary",
                    )
            elif ev.exit_code == 0:
                stance, reason = judged if judged else ("supports", f"`{ev.command}` exited 0")
                if judged:
                    reason = f"`{ev.command}` exited 0: {reason}"
            else:
                stance, reason = (
                    "contradicts",
                    f"`{ev.command}` exited {ev.exit_code}" + (f": {judged[1]}" if judged else ""),
                )
            later = self._code_written_after(ev.index)
            if later is not None:
                stance, reason = (
                    "neutral",
                    f"{reason}; but code was edited afterwards ({later.path}, {later.source})",
                )
            if subset and stance == "supports":
                # a passing selection says nothing about the tests that were not selected
                stance, reason = "neutral", f"{reason}, but only some tests were selected"
            eid = self.add(f"ev:{ev.source}", "command", "observed", ev.source, f"{ev.command} → exit {ev.exit_code}",
                           ev.revision, ev.time, command=ev.command, exit_code=ev.exit_code, output_tail=ev.output,
                           counts=counts, flags=sorted(ev.flags))  # fmt: skip
            links.append((Link(eid, stance, reason), False))  # type: ignore[arg-type]

        # 2. test reports
        if category == "test":
            for run in self.s.reports:
                prov: Provenance = "independent" if self.s.reports_trusted else "observed"
                eid = self.add(f"report:{run.path}", "test_report", prov, run.path,
                               f"{run.format}: {run.passed} passed, {run.failed} failed, {run.errors} errors, {run.skipped} skipped",
                               run.revision, run.time, tests=run.tests, failing=run.failing, tool=run.tool)  # fmt: skip
                judged = judge_counts(
                    {"passed": run.passed, "failed": run.failed, "errors": run.errors, "skipped": run.skipped}
                )
                assert judged is not None
                stance, reason = judged
                if run.revision and self.head and not self.same_revision(run.revision):
                    links.append(
                        (
                            Link(
                                eid,
                                "neutral",
                                f"report is for commit {run.revision[:12]}, not {self.head[:12]}",
                            ),
                            False,
                        )
                    )
                    continue
                later = self._code_written_since(run.time or _mtime(run.path))
                if later is not None:
                    links.append((Link(eid, "neutral", f"report {Path(run.path).name}: {reason}; but code was edited after "
                                       f"it was written ({later.path}, {later.source})"), False))  # fmt: skip
                    continue
                decisive = (stance == "supports" and prov == "independent" and self.same_revision(run.revision)
                            and not self.dirty_code)  # fmt: skip
                if stance == "supports" and not run.revision:
                    reason += "; the report does not say which commit it tested"
                links.append((Link(eid, stance, f"report {Path(run.path).name}: {reason}"), decisive))  # type: ignore[arg-type]

        # 3. commands GroundClaim ran itself
        if category == "test":
            for i, own in enumerate(self.s.runs):
                counts = parse_test_output(own.output)
                judged = judge_counts(counts)
                eid = self.add(f"run:{i}", "command", "independent", "groundclaim --run-tests",
                               f"{own.command} → exit {own.exit_code}", own.revision, None, command=own.command,
                               exit_code=own.exit_code, counts=counts)  # fmt: skip
                if own.exit_code != 0:
                    links.append(
                        (Link(eid, "contradicts", f"re-run `{own.command}` exited {own.exit_code}"), False)
                    )
                elif judged and judged[0] == "contradicts":
                    links.append((Link(eid, "contradicts", f"re-run: {judged[1]}"), False))
                else:
                    links.append(
                        (
                            Link(
                                eid,
                                "supports",
                                f"re-run of `{own.command}` passed" + (f": {judged[1]}" if judged else ""),
                            ),
                            True,
                        )
                    )

        # 4. CI on GitHub for the checked-out commit
        if self.s.github and self.head:
            links += self._check_links(category)
        return links

    def _check_links(self, category: str) -> list[tuple[Link, bool]]:
        gh, head = self.s.github, self.head
        assert gh is not None and head is not None
        links: list[tuple[Link, bool]] = []
        try:
            runs = gh.check_runs(head)
            statuses = gh.statuses(head)
        except GitHubError as exc:
            self.warn(str(exc))
            return links
        named = [r for r in runs if CHECK_NAME[category].search(r.get("name", ""))]
        generic = not named and category != "lint"
        relevant = named or (runs if generic else [])
        uncovered = (
            f"; uncommitted changes to {len(self.dirty_code)} file(s) are not covered"
            if self.dirty_code
            else ""
        )
        for r in relevant:
            name, status, concl = r.get("name", "?"), r.get("status"), r.get("conclusion")
            eid = self.add(f"check:{r.get('id', name)}", "ci_check", "independent", f"github:{gh.repo}",
                           f"check run '{name}': {status}/{concl}", head, r.get("completed_at"), name=name,
                           url=r.get("html_url"), app=(r.get("app") or {}).get("slug"))  # fmt: skip
            what = f"CI check '{name}'" + (" (not identifiable as a test job)" if generic else "")
            if status != "completed":
                links.append((Link(eid, "neutral", f"{what} has not finished"), False))
            elif concl == "success":
                links.append(
                    (
                        Link(eid, "supports", f"{what} succeeded on {head[:12]}{uncovered}"),
                        not uncovered and not generic,
                    )
                )
            elif concl in ("failure", "timed_out", "cancelled", "action_required", "startup_failure"):
                links.append((Link(eid, "contradicts", f"{what} {concl} on {head[:12]}"), False))
            else:
                links.append((Link(eid, "neutral", f"{what} concluded '{concl}'"), False))
        for st in statuses:
            ctx = st.get("context", "?")
            if not CHECK_NAME[category].search(ctx):
                continue
            eid = self.add(f"status:{ctx}:{st.get('id')}", "commit_status", "observed", f"github:{gh.repo}",
                           f"commit status '{ctx}': {st.get('state')}", head, st.get("updated_at"), context=ctx)  # fmt: skip
            state = st.get("state")
            stance: Stance = (
                "supports"
                if state == "success"
                else "contradicts"
                if state in ("failure", "error")
                else "neutral"
            )
            links.append(
                (
                    Link(
                        eid,
                        stance,
                        f"commit status '{ctx}' is {state} (statuses can be posted by any token with write access)",
                    ),
                    False,
                )
            )
        return links

    # --- files ---------------------------------------------------------------------------

    def _match(self, name: str, paths: set[str] | list[str]) -> str | None:
        name = name.lstrip("./")
        for p in paths:
            if p == name or p.endswith("/" + name):
                return p
        return None

    def change_links(self, claim: Claim) -> list[tuple[Link, bool]]:
        links: list[tuple[Link, bool]] = []
        files: list[str] = claim.details.get("files", [])
        written = [e for e in self.s.events or [] if e.kind == "file_write" and e.path]
        root = str(self.s.repo.path.resolve()) if self.s.repo else None
        written_rel = []
        for e in written:
            p = e.path or ""
            if root and p.startswith(root + os.sep):
                p = p[len(root) + 1 :]
            written_rel.append((p, e))

        if self.s.repo and self.head:
            if self.changed is not None:
                scope, changed = f"since {self.base_label}", self.changed
            else:
                scope = "in the working tree or the last commit"
                changed = {p for _, p in self.uncommitted} | set(self.s.repo.last_commit_files())
            for f in files:
                hit = self._match(f, changed)
                eid = self.add(f"git:changed:{f}", "git_diff", "independent", "git",
                               f"{f}: {'changed' if hit else 'not changed'} {scope}", self.head)  # fmt: skip
                if hit:
                    links.append((Link(eid, "supports", f"{hit} changed {scope}"), self.changed is not None))
                elif self.changed is not None:
                    links.append((Link(eid, "contradicts", f"{f} was not changed {scope}"), False))
                else:
                    links.append(
                        (
                            Link(
                                eid,
                                "neutral",
                                f"{f} not changed {scope} (give --base to check the whole run)",
                            ),
                            False,
                        )
                    )
            if not files:
                n = len(changed)
                eid = self.add(
                    "git:changed:*",
                    "git_diff",
                    "independent",
                    "git",
                    f"{n} file(s) changed {scope}",
                    self.head,
                )
                if n:
                    links.append(
                        (
                            Link(
                                eid,
                                "supports",
                                f"{n} file(s) changed {scope}; whether they do what was described is not checked",
                            ),
                            False,
                        )
                    )
                elif self.changed is not None:
                    links.append((Link(eid, "contradicts", f"nothing changed {scope}"), False))
        for f in files:
            for p, e in written_rel:
                if p == f or p.endswith("/" + f.lstrip("./")):
                    eid = self.add(
                        f"ev:{e.source}",
                        "file_write",
                        "observed",
                        e.source,
                        f"the agent edited {p}",
                        time=e.time,
                        path=p,
                    )
                    links.append((Link(eid, "supports", f"the trace shows an edit of {p}"), False))
                    break
        if not files and written_rel and not (self.s.repo and self.head):
            e = written_rel[-1][1]
            eid = self.add(
                f"ev:{e.source}",
                "file_write",
                "observed",
                e.source,
                f"the agent edited {written_rel[-1][0]}",
                time=e.time,
            )
            links.append((Link(eid, "supports", f"the trace shows {len(written_rel)} file edit(s)"), False))
        return links

    def file_links(self, claim: Claim) -> list[tuple[Link, bool]]:
        path = claim.details.get("path")
        if not path:
            return []
        root = self.s.workspace or (self.s.repo.path if self.s.repo else None)
        if root is None:
            return []
        root = root.resolve()
        target = Path(path) if os.path.isabs(path) else root / path
        try:
            resolved = target.resolve()
        except OSError:
            return []
        if resolved != root and root not in resolved.parents:
            return [(Link(self.add(f"file:{path}", "file", "independent", "filesystem", f"{path}: outside the workspace"),
                          "neutral", "the path is outside the workspace and was not checked"), False)]  # fmt: skip
        if target.is_symlink():
            return [(Link(self.add(f"file:{path}", "file", "independent", "filesystem", f"{path}: symbolic link"),
                          "neutral", "symbolic links are not followed"), False)]  # fmt: skip
        rel = str(resolved.relative_to(root))
        if not resolved.exists():
            eid = self.add(f"file:{path}", "file", "independent", "filesystem", f"{rel}: does not exist")
            return [(Link(eid, "contradicts", f"{rel} does not exist"), False)]
        size = resolved.stat().st_size if resolved.is_file() else -1
        eid = self.add(f"file:{path}", "file", "independent", "filesystem", f"{rel}: {size} bytes", size=size)
        if size == 0:
            return [(Link(eid, "contradicts", f"{rel} is empty"), False)]
        return [(Link(eid, "supports", f"{rel} exists ({size} bytes); its content is not checked"), True)]

    # --- git and GitHub claims -----------------------------------------------------------

    def _trace_cmd(self, category: str, what: str) -> list[tuple[Link, bool]]:
        evs = [
            e
            for e in self.s.events or []
            if e.kind == "command" and category in e.categories and e.exit_code is not None
        ]
        if not evs:
            return []
        ev = evs[-1]
        eid = self.add(f"ev:{ev.source}", "command", "observed", ev.source, f"{ev.command} → exit {ev.exit_code}",
                       ev.revision, ev.time, command=ev.command, exit_code=ev.exit_code, output_tail=ev.output)  # fmt: skip
        if ev.exit_code == 0 and "exit_masked" not in ev.flags:
            if category == "push":
                later = next((e for e in self.s.events or [] if e.index > ev.index and e.kind == "command"
                              and "commit" in e.categories and e.exit_code == 0), None)  # fmt: skip
                if later is not None:
                    return [(Link(eid, "neutral", f"`{ev.command}` exited 0, but a commit was made afterwards "
                                  f"({later.source})"), False)]  # fmt: skip
            if category == "release" and re.search(r"(?:^|\s)--draft\b", ev.command or ""):
                return [
                    (
                        Link(eid, "contradicts", f"`{ev.command}` created a draft, which is not published"),
                        False,
                    )
                ]
            return [(Link(eid, "supports", f"`{ev.command}` exited 0"), False)]
        if ev.exit_code != 0:
            return [(Link(eid, "contradicts", f"{what}: `{ev.command}` exited {ev.exit_code}"), False)]
        return [(Link(eid, "neutral", f"`{ev.command}` hides its exit code"), False)]

    def commit_links(self, claim: Claim) -> list[tuple[Link, bool]]:
        links = self._trace_cmd("commit", "commit failed")
        repo = self.s.repo
        if repo is None or self.head is None:
            return links
        sha = claim.details.get("commit")
        if sha:
            info = repo.commit_info(sha) if re.fullmatch(r"[0-9a-f]{7,40}", sha) else None
            if info is None:
                eid = self.add(
                    f"git:commit:{sha}", "git_commit", "independent", "git", f"commit {sha}: not found"
                )
                return links + [
                    (Link(eid, "contradicts", f"there is no commit {sha} in the repository"), False)
                ]
            eid = self.add(f"git:commit:{sha}", "git_commit", "independent", "git", f"{info['sha'][:12]} {info['subject']}",
                           info["sha"], info["committed"], **info)  # fmt: skip
            on_branch = repo.is_ancestor(info["sha"], "HEAD")
            return links + [(Link(eid, "supports" if on_branch else "neutral",
                                  f"commit {info['sha'][:12]} exists" + ("" if on_branch else " but is not in the current branch")),
                             on_branch)]  # fmt: skip
        if self.s.base:
            new = repo.commits_since(self.s.base)
            eid = self.add(
                "git:commits",
                "git_commit",
                "independent",
                "git",
                f"{len(new)} commit(s) since {self.base_label}",
                self.head,
            )
            if not new:
                links.append((Link(eid, "contradicts", f"no commits since {self.base_label}"), False))
            else:
                links.append(
                    (
                        Link(eid, "supports", f"{len(new)} new commit(s) since {self.base_label}"),
                        not self.dirty_code,
                    )
                )
        written = {e.path for e in self.s.events or [] if e.kind == "file_write" and e.path}
        root = str(repo.path.resolve())
        left = sorted(
            p
            for _, p in self.uncommitted
            if any(w == p or w.endswith("/" + p) or w == os.path.join(root, p) for w in written)
        )
        if left:
            eid = self.add(
                "git:uncommitted",
                "git_status",
                "independent",
                "git",
                f"uncommitted: {', '.join(left[:5])}",
                self.head,
            )
            links.append(
                (
                    Link(
                        eid,
                        "contradicts",
                        f"files the agent edited are still uncommitted: {', '.join(left[:3])}",
                    ),
                    False,
                )
            )
        elif self.dirty_code:
            eid = self.add(
                "git:dirty",
                "git_status",
                "independent",
                "git",
                f"{len(self.dirty_code)} uncommitted file(s)",
                self.head,
            )
            links.append((Link(eid, "neutral", f"{len(self.dirty_code)} file(s) still uncommitted"), False))
        return links

    def push_links(self, claim: Claim) -> list[tuple[Link, bool]]:
        links = self._trace_cmd("push", "push failed")
        repo = self.s.repo
        target = claim.details.get("commit") or self.head
        branch = claim.details.get("branch") or self.branch
        if repo is not None and target:
            sha = repo.resolve(target) if re.fullmatch(r"[0-9a-f]{7,40}", target) else None
            if sha:
                remote = repo.branches_containing(sha, remote=True)
                eid = self.add(f"git:remote:{sha}", "git_ref", "observed", "git",
                               f"remote-tracking branches containing {sha[:12]}: {', '.join(remote) or 'none'}", sha)  # fmt: skip
                if remote:
                    links.append(
                        (
                            Link(
                                eid, "supports", f"{sha[:12]} is on {remote[0]} (local remote-tracking ref)"
                            ),
                            False,
                        )
                    )
                else:
                    links.append(
                        (Link(eid, "neutral", f"no remote-tracking branch contains {sha[:12]}"), False)
                    )
                target = sha
        if self.s.github and target and branch:
            try:
                contains = self.s.github.branch_contains(branch, target)
                exists = self.s.github.branch_exists(branch) if contains is None else True
            except GitHubError as exc:
                self.warn(str(exc))
                return links
            eid = self.add(f"gh:branch:{branch}:{target}", "github_branch", "independent", f"github:{self.s.github.repo}",
                           f"{branch} on GitHub: " + ("contains" if contains else "does not contain") + f" {target[:12]}",
                           target)  # fmt: skip
            if contains:
                links.append((Link(eid, "supports", f"GitHub branch {branch} contains {target[:12]}"), True))
            elif not exists:
                links.append((Link(eid, "contradicts", f"branch {branch} does not exist on GitHub"), False))
            else:
                links.append(
                    (
                        Link(eid, "contradicts", f"GitHub branch {branch} does not contain {target[:12]}"),
                        False,
                    )
                )
        return links

    def pr_links(self, claim: Claim) -> list[tuple[Link, bool]]:
        links = self._trace_cmd("pr", "PR creation failed")
        number = claim.details.get("pr")
        for link, _ in list(links):
            ev = self.evidence[int(link.evidence[1:]) - 1]
            m = re.search(r"/pull/(\d+)", ev.data.get("output_tail", "") or "")
            if number and m and int(m.group(1)) != number:
                links.append(
                    (
                        Link(
                            link.evidence,
                            "contradicts",
                            f"the command created PR #{m.group(1)}, not #{number}",
                        ),
                        False,
                    )
                )
        gh = self.s.github
        if gh is None:
            return links
        try:
            if number:
                pr = gh.pull(number)
                prs = [pr] if pr else []
            elif self.branch:
                prs = gh.pulls_for_branch(self.branch)
            else:
                return links
        except GitHubError as exc:
            self.warn(str(exc))
            return links
        what = f"PR #{number}" if number else f"a PR from {self.branch}"
        if not prs:
            eid = self.add(
                f"gh:pr:{number or self.branch}",
                "github_pr",
                "independent",
                f"github:{gh.repo}",
                f"{what}: not found",
            )
            return links + [(Link(eid, "contradicts", f"{what} does not exist on GitHub"), False)]
        pr = prs[0]
        head_sha = (pr.get("head") or {}).get("sha")
        eid = self.add(f"gh:pr:{pr.get('number')}", "github_pr", "independent", f"github:{gh.repo}",
                       f"PR #{pr.get('number')} ({pr.get('state')}): {pr.get('title', '')}", head_sha, pr.get("created_at"),
                       url=pr.get("html_url"), state=pr.get("state"))  # fmt: skip
        note = (
            ""
            if not (self.head and head_sha) or self.same_revision(head_sha)
            else f"; its head is {head_sha[:12]}, local HEAD is {self.head[:12]}"
        )
        return links + [
            (Link(eid, "supports", f"PR #{pr.get('number')} exists ({pr.get('state')}){note}"), True)
        ]

    def deploy_links(self, claim: Claim) -> list[tuple[Link, bool]]:
        links = self._trace_cmd("deploy", "deployment failed")
        gh, env = self.s.github, claim.details.get("environment")
        if gh is None or self.head is None:
            return links
        try:
            deps = gh.deployments(self.head, env)
            if not deps:
                eid = self.add(f"gh:deploy:{env}", "deployment", "independent", f"github:{gh.repo}",
                               f"no GitHub deployments of {self.head[:12]}" + (f" to {env}" if env else ""), self.head)  # fmt: skip
                return links + [
                    (
                        Link(
                            eid,
                            "neutral",
                            "GitHub has no deployment record for this commit (not every deploy creates one)",
                        ),
                        False,
                    )
                ]
            dep = max(deps, key=lambda d: d.get("created_at", ""))
            states = gh.deployment_statuses(int(dep["id"]))
        except (GitHubError, KeyError, ValueError) as exc:
            self.warn(str(exc))
            return links
        state = max(states, key=lambda s: s.get("created_at", "")).get("state") if states else "pending"
        eid = self.add(f"gh:deploy:{dep.get('id')}", "deployment", "independent", f"github:{gh.repo}",
                       f"deployment {dep.get('id')} to {dep.get('environment')}: {state}", dep.get("sha"), dep.get("created_at"),
                       environment=dep.get("environment"))  # fmt: skip
        if state == "success":
            return links + [
                (
                    Link(
                        eid,
                        "supports",
                        f"deployment to {dep.get('environment')} succeeded for {self.head[:12]}",
                    ),
                    True,
                )
            ]
        if state in ("failure", "error"):
            return links + [
                (Link(eid, "contradicts", f"deployment to {dep.get('environment')} ended in {state}"), False)
            ]
        return links + [(Link(eid, "neutral", f"deployment to {dep.get('environment')} is {state}"), False)]

    def release_links(self, claim: Claim) -> list[tuple[Link, bool]]:
        links = self._trace_cmd("release", "release command failed")
        version = claim.details.get("version")
        if not version:
            return links
        tags = [f"v{version}", version]
        registry = re.search(r"\b(pypi|npm|crates\.io|registry)\b", claim.text, re.IGNORECASE)
        tag_claim = re.search(r"\btagged\b|\btag(?:ged)?\s+(?:v|release|version)|\b(?:created|added|pushed)\s+(?:a\s+|the\s+)?tag\b",
                              claim.text, re.IGNORECASE)  # fmt: skip
        if self.s.repo:
            found = next((t for t in tags if self.s.repo.tag_exists(t)), None)
            eid = self.add(
                f"git:tag:{version}",
                "git_tag",
                "independent",
                "git",
                f"tag {found or 'v' + version}: {'exists' if found else 'not found'}",
            )
            if found:
                links.append((Link(eid, "supports", f"tag {found} exists"), bool(tag_claim)))
            elif tag_claim:
                links.append((Link(eid, "contradicts", f"no tag {tags[0]} or {tags[1]}"), False))
        if self.s.github and not registry and not tag_claim:
            try:
                rel = next((r for r in (self.s.github.release(t) for t in tags) if r), None)
            except GitHubError as exc:
                self.warn(str(exc))
                return links
            eid = self.add(f"gh:release:{version}", "github_release", "independent", f"github:{self.s.github.repo}",
                           f"GitHub release {version}: " + ("found" if rel else "not found"))  # fmt: skip
            if rel and not rel.get("draft"):
                links.append(
                    (Link(eid, "supports", f"GitHub release {rel.get('tag_name')} is published"), True)
                )
            elif rel:
                links.append(
                    (
                        Link(eid, "contradicts", f"GitHub release {rel.get('tag_name')} is still a draft"),
                        False,
                    )
                )
            else:
                links.append((Link(eid, "contradicts", f"no GitHub release for {tags[0]}"), False))
        return links

    # --- decision ------------------------------------------------------------------------

    def decide(self, links: list[tuple[Link, bool]], ceiling: tuple[Verdict, str] | None,
               checkable: bool) -> tuple[Verdict, str]:  # fmt: skip
        """``ceiling``: (highest verdict allowed, why) — "supported" or "insufficient_evidence"."""
        contra = [lk for lk, _ in links if lk.stance == "contradicts" and self.prov(lk.evidence) >= 1]
        if contra:
            return "contradicted", contra[0].reason
        support = [(lk, d) for lk, d in links if lk.stance == "supports"]
        decisive = [lk for lk, d in support if d and self.prov(lk.evidence) >= 2]
        observed = [lk for lk, _ in support if self.prov(lk.evidence) >= 1]
        if (decisive or observed) and ceiling:
            top, why = ceiling
            return top, f"{(decisive or observed)[0].reason}; but {why}"
        if decisive:
            return "confirmed", decisive[0].reason
        if observed:
            return "supported", observed[0].reason + "; no independent evidence for the current revision"
        if any(lk.stance == "neutral" for lk, _ in links):
            return "insufficient_evidence", next(lk.reason for lk, _ in links if lk.stance == "neutral")
        if not checkable:
            return "unverifiable", "no source that could check this kind of claim was given"
        return "insufficient_evidence", "no relevant evidence was found"

    def assess(self, claims: list[Claim]) -> list[Assessment]:
        out: list[Assessment] = []
        s = self.s
        has_git = s.repo is not None and self.head is not None
        for claim in claims:
            ceiling: tuple[Verdict, str] | None = None
            checkable = True
            if claim.type in ("tests_passed", "build_succeeded", "lint_clean"):
                category = {"tests_passed": "test", "build_succeeded": "build", "lint_clean": "lint"}[
                    claim.type
                ]
                links = self.run_links(category, claim)
                checkable = bool(
                    s.events is not None or s.github or (category == "test" and (s.reports or s.runs))
                )
                if category == "test" and self.tampering:
                    ceiling = (
                        "insufficient_evidence",
                        f"tests were disabled or deleted ({self.tampering[0]})",
                    )
            elif claim.type in ("code_changed", "bug_fixed"):
                links = self.change_links(claim)
                checkable = has_git or s.events is not None
                if claim.type == "bug_fixed":
                    failing = self.tests_failing_now()
                    if failing is not None:
                        links.append(
                            (
                                Link(
                                    failing.evidence,
                                    "neutral",
                                    f"tests fail after the change: {failing.reason}",
                                ),
                                False,
                            )
                        )
                        ceiling = ("insufficient_evidence", f"the latest test run fails ({failing.reason})")
                    else:
                        ceiling = (
                            "supported",
                            "whether the change fixes the bug is not something GroundClaim can confirm",
                        )
            elif claim.type == "committed":
                links, checkable = self.commit_links(claim), has_git or s.events is not None
            elif claim.type == "pushed":
                links, checkable = (
                    self.push_links(claim),
                    has_git or s.events is not None or s.github is not None,
                )
            elif claim.type == "pr_opened":
                links, checkable = self.pr_links(claim), s.events is not None or s.github is not None
            elif claim.type == "deployed":
                links, checkable = self.deploy_links(claim), s.events is not None or s.github is not None
            elif claim.type == "released":
                links, checkable = (
                    self.release_links(claim),
                    has_git or s.events is not None or s.github is not None,
                )
            elif claim.type == "file_created":
                links, checkable = self.file_links(claim), bool(s.workspace or has_git)
            else:  # task_completed: judged by the other claims in the same message
                links, checkable = [], False
            verdict, reason = self.decide(links, ceiling, checkable)
            out.append(Assessment(claim, verdict, reason, [replace(lk, decisive=d) for lk, d in links]))
        for a in out:
            if a.claim.type == "task_completed":
                bad = [b for b in out if b.verdict == "contradicted" and b is not a]
                if bad:
                    a.verdict, a.reason = (
                        "contradicted",
                        f"claim {bad[0].claim.id} is contradicted: {bad[0].reason}",
                    )
                else:
                    a.reason = "a whole-task claim cannot be checked mechanically; see the other claims"
        return out


def _parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.astimezone()  # naive times are local time (JUnit timestamps)


def _mtime(path: str) -> str | None:
    try:
        return dt.datetime.fromtimestamp(os.stat(path).st_mtime, dt.timezone.utc).isoformat()
    except OSError:
        return None


def verify(
    message: str, sources: Sources, subject: dict[str, Any] | None = None, claims: list[Claim] | None = None
) -> Report:
    """Extract the claims in ``message`` (or take ``claims`` as given) and assess each against ``sources``."""
    v = Verifier(sources)
    if claims is None:
        claims = extract_claims(message)
    assessments = v.assess(claims)
    subj: dict[str, Any] = dict(subject or {})
    if sources.repo is not None:
        subj.update(repository=str(sources.repo.path), head=v.head, branch=v.branch, base=sources.base,
                    uncommitted_files=len(v.uncommitted))  # fmt: skip
    if sources.trace_name:
        subj["trace"] = sources.trace_name
    if sources.github:
        subj["github"] = sources.github.repo
    if not claims:
        v.warn("no completion claims were found in the message")
    return Report(SCHEMA_VERSION, subj, assessments, v.evidence, v.warnings)
