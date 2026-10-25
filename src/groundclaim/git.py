"""Read-only questions to a git repository (independent evidence).

git is run with fixed argument lists (never through a shell). Values that come
from an agent's message or a trace (commit ids, branch names) are validated
before they are passed, so they cannot inject options or commands.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REF_RE = re.compile(r"^(?!-)[A-Za-z0-9._/-]{1,200}$")
TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec|specs)(/|$)|(^|/)test_[^/]+\.py$|_test\.(py|go)$|\.(test|spec)\.[jt]sx?$"
)
# Markers that disable tests, by language.
SKIP_MARKERS = re.compile(
    r"@pytest\.mark\.(skip|xfail)|pytest\.skip\(|unittest\.skip|\b(it|test|describe)\.(skip|todo)\(|\bx(it|describe)\(|"
    r"@Disabled|@Ignore\b|t\.Skip\(|#\[ignore\]|\.skip\("
)


class GitError(RuntimeError):
    pass


def safe_ref(value: str) -> str:
    if not REF_RE.match(value) or ".." in value:
        raise GitError(f"not a valid git revision or branch name: {value!r}")
    return value


@dataclass
class Repo:
    path: Path
    _filters: list[str] | None = field(default=None, repr=False)

    def git(self, *args: str, check: bool = True) -> str:
        proc = self._run(args)
        if check and proc.returncode != 0:
            raise GitError(proc.stderr.strip() or f"git {args[0]} failed")
        return proc.stdout

    def succeeds(self, *args: str) -> bool:
        return self._run(args).returncode == 0

    def _run(self, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        # The repository may have been prepared by the agent being checked. Its local
        # config could make read commands run programs (core.fsmonitor, external diff
        # drivers, textconv filters), so those are switched off for every call.
        # Content filters (filter.<driver>.clean/smudge/process, used by status and diff) are
        # named by the repository's own config, so each configured one is overridden by name.
        hardened = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "diff.external=",
                    "-c", "core.pager=cat", "-c", "protocol.allow=never", "-c", "log.showSignature=false",
                    "-c", "core.untrackedCache=false", *self._filter_overrides()]  # fmt: skip
        if args and args[0] == "diff":
            args = ("diff", "--no-ext-diff", "--no-textconv", *args[1:])
        try:
            proc = subprocess.run(
                ["git", *hardened, "-C", str(self.path), "--no-pager", *args],
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1"},
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitError(str(exc)) from exc
        return proc

    def _filter_overrides(self) -> list[str]:
        if self._filters is None:
            # "git config" only reads configuration; it does not run filters or hooks.
            try:
                proc = subprocess.run(
                    ["git", "-C", str(self.path), "config", "-z", "--get-regexp", r"^filter\..*\.(clean|smudge|process)$"],
                    capture_output=True, text=True, timeout=30, check=False,
                    env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"},
                )  # fmt: skip
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise GitError(str(exc)) from exc
            self._filters = []
            for entry in proc.stdout.split("\0"):
                key = entry.split("\n", 1)[0]
                if key.startswith("filter."):
                    self._filters += ["-c", f"{key}=", "-c", f"{key.rsplit('.', 1)[0]}.required=false"]
        return self._filters

    def is_repo(self) -> bool:
        try:
            return self.git("rev-parse", "--is-inside-work-tree").strip() == "true"
        except GitError:
            return False

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    def branch(self) -> str | None:
        name = self.git("symbolic-ref", "--short", "-q", "HEAD", check=False).strip()
        return name or None

    def is_ancestor(self, older: str, newer: str = "HEAD") -> bool:
        return self.succeeds("merge-base", "--is-ancestor", safe_ref(older), safe_ref(newer))

    def last_commit_files(self) -> list[str]:
        out = self.git("show", "--name-only", "--format=", "--no-renames", "HEAD", check=False)
        return [x for x in out.splitlines() if x.strip()]

    def resolve(self, rev: str) -> str | None:
        out = self.git("rev-parse", "--verify", "--quiet", f"{safe_ref(rev)}^{{commit}}", check=False).strip()
        return out or None

    def commit_info(self, rev: str) -> dict[str, str] | None:
        sha = self.resolve(rev)
        if not sha:
            return None
        fmt = "%H%x00%an%x00%aI%x00%cI%x00%s"
        h, author, authored, committed, subject = self.git("show", "-s", f"--format={fmt}", sha).split("\x00")
        return {
            "sha": h,
            "author": author,
            "authored": authored,
            "committed": committed,
            "subject": subject.strip(),
        }

    def commits_since(self, base: str) -> list[str]:
        out = self.git("rev-list", f"{safe_ref(base)}..HEAD", check=False)
        return [x for x in out.split() if x]

    def changed_files(self, base: str, head: str | None = "HEAD") -> list[tuple[str, str]]:
        """(status, path) between two revisions (head None = the working tree): A added, M modified, D deleted."""
        out = self.git(
            "diff", "--name-status", "--no-renames", safe_ref(base), *([safe_ref(head)] if head else [])
        )
        rows = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                rows.append((parts[0][0], parts[-1]))
        return rows

    def uncommitted(self) -> list[tuple[str, str]]:
        rows = []
        for line in self.git("status", "--porcelain=v1", "--untracked-files=all").splitlines():
            if len(line) > 3:
                rows.append((line[:2].strip() or "?", line[3:]))
        return rows

    def diff_text(self, base: str, head: str | None, paths: list[str] | None = None) -> str:
        args = ["diff", "--unified=0", safe_ref(base), *([safe_ref(head)] if head else [])]
        if paths:
            args += ["--", *paths]
        return self.git(*args)

    def branches_containing(self, sha: str, remote: bool) -> list[str]:
        out = self.git(
            "branch",
            "-r" if remote else "--list",
            "--contains",
            safe_ref(sha),
            "--format=%(refname:short)",
            check=False,
        )
        return [b.strip() for b in out.splitlines() if b.strip()]

    def tags_pointing_at(self, rev: str) -> list[str]:
        return [t for t in self.git("tag", "--points-at", safe_ref(rev), check=False).split() if t]

    def tag_exists(self, tag: str) -> str | None:
        return self.resolve(f"refs/tags/{safe_ref(tag)}")


def find_test_tampering(repo: Repo, base: str, head: str | None = None) -> list[str]:
    """Signs that tests were weakened since ``base`` (head None = up to the working tree): test files
    deleted, skip markers added."""
    findings = []
    for status, path in repo.changed_files(base, head):
        if TEST_PATH_RE.search(path) and status == "D":
            findings.append(f"test file deleted: {path}")
    diff = repo.diff_text(base, head)
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif line.startswith("+") and not line.startswith("+++") and SKIP_MARKERS.search(line):
            findings.append(f"test disabled in {current}: {line[1:].strip()[:80]}")
    return findings
